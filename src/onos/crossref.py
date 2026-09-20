"""Article metadata from Crossref's public REST API (not an ONOS article index)."""

from urllib.parse import quote, urlencode

from ._http import HTTPTransport
from ._parsers import optional, required
from ._utils import doi_url, http_url, normalize_doi, normalize_issn, positive_int
from .errors import ResponseError
from .models import Article, ArticlePage


def _strings(record: dict, key: str) -> tuple[str, ...]:
    values = record.get(key) or []
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise ResponseError(f"Invalid Crossref field {key!r}")
    return tuple(values)


def _article(record: dict) -> Article:
    if not isinstance(record, dict):
        raise ResponseError("Expected a Crossref work object")
    doi = required(record, "DOI")
    titles = _strings(record, "title")
    journals = _strings(record, "container-title")
    authors = []
    raw_authors = record.get("author") or []
    if not isinstance(raw_authors, list):
        raise ResponseError("Invalid Crossref authors")
    for author in raw_authors:
        if not isinstance(author, dict):
            raise ResponseError("Invalid Crossref author")
        name = optional(author, "name") or " ".join(
            part for part in (optional(author, "given"), optional(author, "family")) if part
        )
        if name:
            authors.append(name)
    published = None
    for field in ("published", "published-print", "published-online", "issued"):
        date = record.get(field) or {}
        if not isinstance(date, dict):
            raise ResponseError(f"Invalid Crossref date {field!r}")
        parts = date.get("date-parts") or []
        if parts and isinstance(parts, list) and isinstance(parts[0], list) and parts[0]:
            if not 1 <= len(parts[0]) <= 3 or any(type(p) is not int for p in parts[0]):
                raise ResponseError("Invalid Crossref date parts")
            published = "-".join(f"{part:04d}" if i == 0 else f"{part:02d}"
                                 for i, part in enumerate(parts[0]))
            break
    resource = record.get("resource") or {}
    primary = resource.get("primary", {}) if isinstance(resource, dict) else {}
    url = primary.get("URL") if isinstance(primary, dict) else None
    try:
        url = http_url(url) if isinstance(url, str) else doi_url(doi)
    except ValueError:
        url = doi_url(doi)
    return Article(doi=doi, title=titles[0] if titles else "", authors=tuple(authors),
                   journal=journals[0] if journals else "", publisher=optional(record, "publisher"),
                   issns=_strings(record, "ISSN"), published=published, url=url)


class CrossrefClient:
    """Search article metadata or look up a DOI, optionally using the polite pool."""

    def __init__(self, *, mailto: str | None = None, transport: HTTPTransport | None = None,
                 timeout: float = 30, retries: int = 2, cache_ttl: float = 300):
        if mailto is not None and ("@" not in mailto or any(c.isspace() for c in mailto)):
            raise ValueError("mailto must be an email address")
        self.mailto = mailto
        self._transport = transport if transport is not None else HTTPTransport(
            timeout=timeout, retries=retries, cache_ttl=cache_ttl)
        self._owns_transport = transport is None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()

    def clear_cache(self) -> None:
        self._transport.clear_cache()

    def _message(self, path: str, params: dict | None = None):
        params = dict(params or {})
        if self.mailto:
            params["mailto"] = self.mailto
        url = "https://api.crossref.org" + path
        if params:
            url += "?" + urlencode(params)
        payload = self._transport.json("GET", url)
        if (not isinstance(payload, dict) or payload.get("status") != "ok"
                or not isinstance(payload.get("message"), dict)):
            raise ResponseError("Invalid Crossref response envelope")
        return payload["message"]

    def get_article(self, doi: str) -> Article:
        return _article(self._message("/works/" + quote(normalize_doi(doi), safe="")))

    def search_articles(self, query: str, *, issn: str | None = None,
                        limit: int = 20, cursor: str = "*") -> ArticlePage:
        """Return one page of journal articles. Pass next_cursor for the next page.

        Results are Crossref metadata; membership in the ONOS catalog is not implied.
        An ISSN restricts the search to that journal.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        positive_int(limit, "limit", 1000)
        if not isinstance(cursor, str) or not cursor.strip():
            raise ValueError("cursor must be a nonempty string")
        filters = "type:journal-article"
        if issn:
            filters += ",issn:" + normalize_issn(issn)
        message = self._message("/works", {"query.bibliographic": query.strip(),
            "filter": filters, "rows": limit, "cursor": cursor})
        items = message.get("items")
        total = message.get("total-results")
        if not isinstance(items, list) or type(total) is not int or total < 0:
            raise ResponseError("Invalid Crossref search results")
        next_cursor = message.get("next-cursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ResponseError("Invalid Crossref cursor")
        if len(items) < limit:
            next_cursor = None
        return ArticlePage(tuple(_article(item) for item in items), total, next_cursor or None)
