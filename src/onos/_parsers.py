"""Parsers for the small amount of HTML exposed by the public portal."""

from html.parser import HTMLParser

from .errors import ResponseError
from .models import Publisher


class TokenParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.token = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "csrf-token":
            self.token = attrs.get("content")


class PublisherParser(HTMLParser):
    """Read publisher cards, ignoring navigation and open-access buttons."""

    def __init__(self):
        super().__init__()
        self.publishers: list[Publisher] = []
        self._depth = 0
        self._card = None
        self._count = False
        self._count_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "div":
            if self._card is not None:
                self._depth += 1
            elif "accordion-item" in classes:
                self._card = {"urls": []}
                self._depth = 1
        if self._card is None:
            return
        if tag == "span" and "journal-count" in classes:
            self._count = True
            self._count_parts = []
        if tag == "a" and attrs.get("data-url"):
            self._card["urls"].append(attrs["data-url"])
        if tag == "button" and "view-journal-btn" in classes:
            self._card.update(id=attrs.get("data-id"), name=attrs.get("data-name"),
                              backfiles_from=attrs.get("data-year") or None)

    def handle_data(self, data):
        if self._count:
            self._count_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "span" and self._count:
            self._count = False
            value = "".join(self._count_parts).strip().replace(",", "")
            if self._card is not None:
                self._card["journal_count"] = int(value) if value.isdigit() else None
        if tag == "div" and self._card is not None:
            self._depth -= 1
            if self._depth == 0:
                if not self._card.get("id") or not self._card.get("name"):
                    raise ResponseError("Publisher card is missing its ID or name")
                self._card["urls"] = tuple(dict.fromkeys(self._card["urls"]))
                self.publishers.append(Publisher(**self._card))
                self._card = None


def parse_publishers(html: str) -> list[Publisher]:
    parser = PublisherParser()
    parser.feed(html)
    parser.close()
    if not parser.publishers or parser._card is not None:
        raise ResponseError("Publisher HTML was not recognized; the ONOS portal may have changed")
    return parser.publishers


def rows(payload, key: str = "result") -> list[dict]:
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ResponseError("ONOS returned an unsuccessful response")
    result = payload.get(key)
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise ResponseError(f"Expected a list in ONOS field {key!r}; the portal may have changed")
    return result


def required(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
        raise ResponseError(f"Missing or invalid required field {key!r}")
    return str(value).strip()


def optional(row: dict, key: str) -> str:
    value = row.get(key)
    if value is None:
        return ""
    if isinstance(value, (dict, list, bool)):
        raise ResponseError(f"Invalid text field {key!r}")
    return str(value).strip()
