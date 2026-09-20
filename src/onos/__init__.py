"""Unofficial client for India's One Nation One Subscription initiative."""

from ._http import HTTPTransport
from ._utils import access_url, normalize_doi, normalize_issn
from .client import ONOSClient
from .crossref import CrossrefClient
from .errors import HTTPError, NetworkError, NotFoundError, ONOSError, RateLimitError, ResponseError
from .models import AccessResult, Article, ArticlePage, Institution, Journal, Publisher, Subject

__version__ = "0.1.0"
__all__ = [
    "ONOSClient", "CrossrefClient", "HTTPTransport", "Journal", "Publisher", "Subject",
    "Institution", "Article", "ArticlePage", "AccessResult", "ONOSError", "NetworkError",
    "HTTPError", "NotFoundError", "RateLimitError", "ResponseError", "access_url",
    "normalize_doi", "normalize_issn",
]
