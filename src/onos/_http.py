"""Standard-library HTTP session with cookies, pacing, retries, and bounded caching."""

import json
import math
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from http.cookiejar import CookieJar
from urllib.error import HTTPError as UrlHTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .errors import HTTPError, NetworkError, NotFoundError, RateLimitError, ResponseError


class HTTPTransport:
    """Synchronous session. Use one instance per thread; TLS verification stays enabled.

    POST requests made by this package only perform public metadata reads, so they
    are safe to retry. Do not reuse this transport for state-changing requests.
    """

    def __init__(self, *, timeout: float = 30, retries: int = 2,
                 min_interval: float = 0.5, cache_ttl: float = 300,
                 user_agent: str = "onos-india/0.1.0"):
        for name, value in (("timeout", timeout), ("min_interval", min_interval),
                            ("cache_ttl", cache_ttl)):
            if not math.isfinite(value) or value < 0 or (name == "timeout" and value == 0):
                raise ValueError(f"{name} must be finite and {'positive' if name == 'timeout' else 'nonnegative'}")
        if isinstance(retries, bool) or not isinstance(retries, int) or not 0 <= retries <= 5:
            raise ValueError("retries must be an integer between 0 and 5")
        self.timeout, self.retries = timeout, retries
        self.min_interval, self.cache_ttl = min_interval, cache_ttl
        self.user_agent = user_agent
        self._cookies = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._cookies))
        self._cache: OrderedDict[tuple, tuple[float, str]] = OrderedDict()
        self._last_request: float | None = None

    def clear_cache(self) -> None:
        self._cache.clear()

    def close(self) -> None:
        self.clear_cache()
        self._cookies.clear()

    def request(self, method: str, url: str, *, data: dict | None = None,
                headers: dict | None = None, cache: bool = True) -> str:
        body = urlencode(data, doseq=True).encode("utf-8") if data is not None else None
        key = (method, url, body)
        cached = self._cache.get(key) if cache else None
        if cached and time.monotonic() - cached[0] < self.cache_ttl:
            self._cache.move_to_end(key)
            return cached[1]
        request_headers = {"User-Agent": self.user_agent, "Accept": "application/json"}
        request_headers.update(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        for attempt in range(self.retries + 1):
            if self._last_request is not None:
                time.sleep(max(0, self.min_interval - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                req = Request(url, data=body, headers=request_headers, method=method)
                with self._opener.open(req, timeout=self.timeout) as response:
                    result = response.read().decode(response.headers.get_content_charset() or "utf-8")
            except UrlHTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get("Retry-After")
                exc.close()
                delay = self._retry_delay(retry_after, attempt)
                if status in {429, 500, 502, 503, 504} and attempt < self.retries and delay <= 60:
                    time.sleep(delay)
                    continue
                error = RateLimitError if status == 429 else NotFoundError if status == 404 else HTTPError
                raise error(status, url) from exc
            except (URLError, OSError, HTTPException) as exc:
                if attempt < self.retries:
                    time.sleep(2 ** attempt)
                    continue
                raise NetworkError(f"Could not reach {url}: {exc}") from exc
            except (UnicodeError, LookupError) as exc:
                raise ResponseError(f"Invalid response encoding from {url}") from exc
            if cache and self.cache_ttl > 0:
                self._cache[key] = (time.monotonic(), result)
                self._cache.move_to_end(key)
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
            return result
        raise AssertionError("unreachable")

    def json(self, method: str, url: str, **kwargs):
        try:
            return json.loads(self.request(method, url, **kwargs))
        except json.JSONDecodeError as exc:
            raise ResponseError(f"Expected JSON from {url}; the remote interface may have changed") from exc

    @staticmethod
    def _retry_delay(value: str | None, attempt: int) -> float:
        if value:
            try:
                delay = float(value)
                if math.isfinite(delay):
                    return max(0, delay)
            except ValueError:
                try:
                    date = parsedate_to_datetime(value)
                    if date.tzinfo is None:
                        date = date.replace(tzinfo=timezone.utc)
                    return max(0, (date - datetime.now(timezone.utc)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    pass
        return float(2 ** attempt)
