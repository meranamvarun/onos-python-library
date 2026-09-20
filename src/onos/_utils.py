"""Input normalization shared by public interfaces."""

import base64
import re
from urllib.parse import quote, unquote, urlencode, urlsplit

BASE_URL = "https://www.onos.gov.in"


def normalize_issn(value: str) -> str:
    compact = value.strip().replace("-", "").upper()
    if not re.fullmatch(r"[0-9]{7}[0-9X]", compact):
        raise ValueError("ISSN must contain eight digits (the last may be X)")
    check = sum(int(c) * weight for c, weight in zip(compact[:7], range(8, 1, -1)))
    check += 10 if compact[-1] == "X" else int(compact[-1])
    if check % 11:
        raise ValueError("ISSN checksum is invalid")
    return compact[:4] + "-" + compact[4:]


def normalize_doi(value: str) -> str:
    value = value.strip()
    if value.lower().startswith(("https://", "http://")):
        parsed = urlsplit(value)
        if parsed.hostname not in {"doi.org", "dx.doi.org"} or parsed.username or parsed.password:
            raise ValueError("Expected a DOI or a doi.org URL")
        value = unquote(parsed.path.lstrip("/"))
    elif value.lower().startswith("doi:"):
        value = value[4:].strip()
    if not re.fullmatch(r"10\.[0-9]{4,9}/\S+", value) or any(ord(c) < 32 for c in value):
        raise ValueError("Expected a DOI such as 10.1038/nphys1170")
    return value


def doi_url(doi: str) -> str:
    return "https://doi.org/" + quote(normalize_doi(doi), safe="/")


def http_url(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme not in {"https", "http"} or not parsed.hostname
            or parsed.username or parsed.password or any(c.isspace() for c in value)
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError("Expected an HTTP(S) URL without credentials or whitespace")
    return value


def access_url(target: str | None = None) -> str:
    """Build the portal's own access handoff URL; no request or login is performed."""
    url = BASE_URL + "/ums/check-access"
    if target is None:
        return url
    target = target.strip()
    if not target.lower().startswith(("http://", "https://")):
        target = doi_url(target)
    http_url(target)
    # ONOS decodes target using JavaScript atob, so encode an ASCII URI first.
    target = quote(target, safe=":/?#[]@!$&'()*+,;=%")
    encoded = base64.b64encode(target.encode("ascii")).decode("ascii")
    return url + "?" + urlencode({"target": encoded})


def positive_int(value: int, name: str, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return value
