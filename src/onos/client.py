"""Public ONOS catalog discovery with a separate Crossref article adapter."""

import re
from collections.abc import Sequence

from ._http import HTTPTransport
from ._parsers import TokenParser, optional, parse_publishers, required, rows
from ._utils import BASE_URL, access_url, normalize_issn, positive_int
from .crossref import CrossrefClient
from .errors import HTTPError, ResponseError
from .models import AccessResult, Article, ArticlePage, Institution, Journal, Publisher, Subject


class ONOSClient:
    """Unofficial client for public One Nation One Subscription discovery.

    ONOS endpoints are website implementation details, not a documented public API.
    Authentication remains in the user's browser. Instances are not thread safe.
    Injected transports remain owned by their caller.
    """

    def __init__(self, *, timeout: float = 30, retries: int = 2, cache_ttl: float = 300,
                 mailto: str | None = None, transport: HTTPTransport | None = None,
                 crossref_transport: HTTPTransport | None = None):
        self._transport = transport if transport is not None else HTTPTransport(
            timeout=timeout, retries=retries, cache_ttl=cache_ttl)
        self._owns_transport = transport is None
        self.crossref = CrossrefClient(mailto=mailto, transport=crossref_transport,
            timeout=timeout, retries=retries, cache_ttl=cache_ttl)
        self._csrf_token: str | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self) -> None:
        if self._owns_transport:
            self._transport.close()
        self.crossref.close()
        self._csrf_token = None

    def clear_cache(self) -> None:
        """Discard cached public metadata in both service transports."""
        self._transport.clear_cache()
        self.crossref.clear_cache()

    def _session(self) -> None:
        page = self._transport.request("GET", BASE_URL + "/journalSearch",
                                       headers={"Accept": "text/html"}, cache=False)
        parser = TokenParser()
        parser.feed(page)
        if not parser.token:
            raise ResponseError("ONOS did not provide a CSRF token; the portal may have changed")
        self._csrf_token = parser.token

    def _post(self, path: str, data: dict | None = None):
        for attempt in range(2):
            if self._csrf_token is None:
                self._session()
            try:
                return self._transport.json("POST", BASE_URL + path, data=data or {},
                    headers={"X-CSRF-TOKEN": self._csrf_token,
                             "X-Requested-With": "XMLHttpRequest",
                             "Referer": BASE_URL + "/journalSearch"})
            except HTTPError as exc:
                if exc.status != 419 or attempt:
                    raise
                self._csrf_token = None
        raise AssertionError("unreachable")

    def search_journals(self, query: str | None = None, *,
                        subject_codes: Sequence[str | int] = (),
                        limit: int | None = None) -> list[Journal]:
        """Search titles/ISSNs OR up to five broad subject codes from list_subjects.

        ONOS returns a complete result list for each query. limit slices this list
        locally; it does not reduce the size of the upstream response.
        """
        if limit is not None:
            positive_int(limit, "limit")
        if isinstance(subject_codes, (str, bytes)):
            raise ValueError("subject_codes must be a sequence of codes, not a string")
        codes = tuple(str(c) for c in subject_codes)
        if bool(query and query.strip()) == bool(codes):
            raise ValueError("Provide either a nonempty query or subject_codes")
        if codes:
            if len(codes) > 5 or any(not re.fullmatch(r"[0-9]{4}", code) for code in codes):
                raise ValueError("Provide at most five four-digit subject codes")
            data = {"type": "subject", "subjects[]": codes}
        else:
            query = query.strip()
            if re.fullmatch(r"[0-9]{4}-?[0-9]{3}[0-9Xx]", query):
                query = normalize_issn(query)
            data = {"type": "title", "searchTitle": query}
        records = rows(self._post("/searchJournal", data))
        results = [Journal(title=required(r, "title"), publisher=optional(r, "publisher"),
            url=required(r, "url"), print_issn=optional(r, "pissn") or None,
            online_issn=optional(r, "eissn") or None, subject=optional(r, "subject"))
            for r in records]
        return results[:limit]

    def list_subjects(self) -> list[Subject]:
        payload = self._post("/fetchSubject")
        if not isinstance(payload, dict) or not payload:
            raise ResponseError("Expected ONOS subject groups")
        result = []
        for discipline, records in payload.items():
            if not isinstance(records, list) or not records:
                raise ResponseError("Invalid ONOS subject group")
            for record in records:
                if not isinstance(record, dict):
                    raise ResponseError("Invalid ONOS subject")
                result.append(Subject(required(record, "code"),
                                      required(record, "description"), discipline))
        return result

    def list_publishers(self, query: str = "") -> list[Publisher]:
        page = self._transport.request("GET", BASE_URL + "/publishers",
                                       headers={"Accept": "text/html"})
        return [p for p in parse_publishers(page) if query.casefold() in p.name.casefold()]

    def search_institutions(self, query: str = "", *, state: str | None = None,
                            city: str | None = None, aishe_code: str | None = None,
                            limit: int | None = None) -> list[Institution]:
        """Filter the public directory locally; state, city, AISHE are exact ignoring case."""
        if limit is not None:
            positive_int(limit, "limit")
        records = rows(self._transport.json("GET", BASE_URL + "/instituteDetails"))
        result = []
        for r in records:
            code = optional(r, "remark")
            item = Institution(id=required(r, "id"), name=required(r, "memname"),
                aishe_code=code if re.fullmatch(r"[CSUR]-[0-9]+", code) else None,
                city=optional(r, "city"), state=optional(r, "state"),
                access_type={"Yes": "campus_ip", "College-Yes": "institutional_login"}.get(
                    optional(r, "onos_status"), "unknown"))
            if query.strip().casefold() not in " ".join(
                    (item.name, item.aishe_code or "", item.city, item.state)).casefold():
                continue
            if any(wanted is not None and (actual or "").casefold() != wanted.strip().casefold()
                   for actual, wanted in ((item.state, state), (item.city, city),
                                          (item.aishe_code, aishe_code))):
                continue
            result.append(item)
        return result[:limit]

    def get_article(self, doi: str) -> Article:
        """Look up article metadata in Crossref, independently of ONOS coverage."""
        return self.crossref.get_article(doi)

    def search_articles(self, query: str, *, issn: str | None = None,
                        limit: int = 20, cursor: str = "*") -> ArticlePage:
        return self.crossref.search_articles(query, issn=issn, limit=limit, cursor=cursor)

    def check_article_access(self, article: Article | str) -> AccessResult:
        """Match article ISSNs to ONOS journals and produce an institutional-login link.

        This checks catalog membership only. It never confirms subscription year
        coverage, institutional eligibility, or full-text access.
        """
        if isinstance(article, str):
            article = self.get_article(article)
        matches = []
        valid_issns = set()
        for issn in article.issns:
            try:
                normalized = normalize_issn(issn)
            except ValueError:
                continue
            if normalized in valid_issns:
                continue
            valid_issns.add(normalized)
            for journal in self.search_journals(normalized):
                journal_issns = set()
                for identifier in journal.issns:
                    try:
                        journal_issns.add(normalize_issn(identifier))
                    except ValueError:
                        pass
                if normalized in journal_issns and journal not in matches:
                    matches.append(journal)
        status = "matched" if matches else "not_found" if valid_issns else "unknown"
        return AccessResult(article, tuple(matches), status, access_url(article.url))

    @staticmethod
    def access_url(target: str | None = None) -> str:
        return access_url(target)
