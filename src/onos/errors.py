"""Stable exceptions for callers and the command-line interface."""


class ONOSError(Exception):
    """Base class for remote service and response errors."""


class NetworkError(ONOSError):
    """A connection, TLS, or timeout failure."""


class HTTPError(ONOSError):
    """An unsuccessful HTTP response, excluding its potentially sensitive body."""

    def __init__(self, status: int, url: str):
        self.status = status
        self.url = url
        super().__init__(f"HTTP {status} from {url}")


class RateLimitError(HTTPError):
    """The service is rate limiting requests; try again later."""


class NotFoundError(HTTPError):
    """The requested resource was not found."""


class ResponseError(ONOSError):
    """The service returned an unsuccessful or unexpected response schema."""
