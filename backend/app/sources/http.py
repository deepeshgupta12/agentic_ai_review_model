"""Safe outbound HTTP for collectors (docs/06 scraping rules 1-3; Step 05.4, 05.5).

- https or http on the default ports only; the host must resolve to public addresses (no loopback, private,
  link-local, multicast or reserved ranges), checked again on every redirect hop (SSRF protection);
- redirects followed by hand, at most `max_redirects`, and each hop goes back through the caller's check
  (policy family and robots.txt) before it is requested;
- responses are streamed and cut off at `max_bytes`; only the listed content types are read;
- an honest user agent; a per-host pace; Retry-After and exponential backoff with jitter for 429 and 5xx;
- every failure becomes a FetchError with a safe code, the HTTP status and whether retrying could help.
"""

from __future__ import annotations

import ipaddress
import json
import random
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

RETRY_STATUS = {429, 500, 502, 503, 504}
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
JSON_TYPES = ("application/json",)
Resolver = Callable[[str], list[str]]


class FetchError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.retryable = code, message, status, retryable


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    redirects: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    def text(self) -> str:
        charset = "utf-8"
        for part in self.headers.get("content-type", "").split(";")[1:]:
            if part.strip().lower().startswith("charset="):
                charset = part.split("=", 1)[1].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:  # a charset Python does not know ("utf8mb4", "none"): read as UTF-8, never crash the job
            return self.body.decode("utf-8", errors="replace")


def system_resolver(host: str) -> list[str]:
    try:
        return sorted({str(info[4][0]) for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})
    except socket.gaierror as exc:
        raise FetchError("dns_failed", f"{host} did not resolve", retryable=True) from exc


def public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or getattr(ip, "is_site_local", False)
    )


def retry_after_seconds(value: str | None, now: float | None = None) -> float | None:
    """Retry-After as seconds, from either delta-seconds or an HTTP date."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, when.timestamp() - (now if now is not None else time.time()))


class HostPacer:
    """At most one request per host every `interval` seconds within this process."""

    def __init__(
        self, interval: float, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep
    ):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self._lock:
            now = self.clock()
            ready = self._next.get(host, now)
            self._next[host] = max(now, ready) + self.interval
        if ready > now:
            self.sleep(ready - now)


class SafeClient:
    def __init__(
        self,
        *,
        user_agent: str,
        max_bytes: int,
        max_redirects: int,
        timeout: float,
        pacer: HostPacer,
        resolver: Resolver = system_resolver,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 3,
        max_retry_after: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.user_agent, self.max_bytes, self.max_redirects = user_agent, max_bytes, max_redirects
        self.pacer, self.resolver, self.max_attempts = pacer, resolver, max_attempts
        self.max_retry_after, self.sleep = max_retry_after, sleep
        self._client = httpx.Client(timeout=timeout, follow_redirects=False, transport=transport, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _check_target(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ("https", "http"):
            raise FetchError("scheme_refused", f"only http and https are fetched, not {parts.scheme or 'none'}")
        if parts.port not in (None, 80, 443):
            raise FetchError("port_refused", f"port {parts.port} is not fetched")
        if parts.username or parts.password:
            raise FetchError("credentials_in_url", "URLs with credentials are not fetched")
        host = (parts.hostname or "").lower()
        if not host:
            raise FetchError("no_host", "the URL has no host")
        addresses = self.resolver(host)
        if not addresses or not all(public_address(a) for a in addresses):
            raise FetchError("address_refused", f"{host} resolves to a non-public address")
        return host

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        accept: tuple[str, ...] = TEXT_TYPES,
        check_hop: Callable[[str], None] | None = None,
    ) -> Response:
        """GET with SSRF checks, a redirect budget, a size cap and bounded retries. `check_hop(url)` may raise
        FetchError to stop at a hop the policy or robots.txt does not allow."""
        redirects: list[str] = []
        current = url
        for _ in range(self.max_redirects + 1):
            host = self._check_target(current)
            if check_hop is not None:
                check_hop(current)
            response = self._request(host, current, headers, params if current == url else None, accept)
            if response.status in (301, 302, 303, 307, 308) and "location" in response.headers:
                redirects.append(current)
                current = urljoin(current, response.headers["location"])
                continue
            response.redirects = redirects
            return response
        raise FetchError("too_many_redirects", f"more than {self.max_redirects} redirects")

    def post_json(
        self,
        url: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        accept: tuple[str, ...] = TEXT_TYPES,
    ) -> Response:
        """POST a JSON body to a provider's API (Firecrawl, D62): the same address checks, size cap and bounded retries;
        redirects are not followed."""
        host = self._check_target(url)
        sent = {"Content-Type": "application/json", **(headers or {})}
        return self._request(host, url, sent, None, accept, method="POST", content=json.dumps(body).encode())

    def _request(
        self,
        host: str,
        url: str,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        accept: tuple[str, ...],
        method: str = "GET",
        content: bytes | None = None,
    ) -> Response:
        last: FetchError | None = None
        # A POST to a paid provider (Firecrawl) is never sent again after a timeout or a dropped connection: the first
        # may have been done and billed. Only "too many requests" (not processed) is retried.
        unsafe = method != "GET"
        for attempt in range(1, self.max_attempts + 1):
            self.pacer.wait(host)
            try:
                with self._client.stream(
                    method,
                    url,
                    params=params,
                    headers={"User-Agent": self.user_agent, **(headers or {})},
                    content=content,
                ) as raw:
                    status = raw.status_code
                    response_headers = {k.lower(): v for k, v in raw.headers.items()}
                    if status in RETRY_STATUS and not (unsafe and status != 429):
                        wait = retry_after_seconds(response_headers.get("retry-after"))
                        last = FetchError(
                            "provider_busy" if status == 429 else "server_error",
                            f"HTTP {status}",
                            status=status,
                            retryable=True,
                        )
                        if wait is not None and wait > self.max_retry_after:
                            raise last
                        if attempt < self.max_attempts:
                            self.sleep(wait if wait is not None else random.uniform(0, 2.0 * 2 ** (attempt - 1)))  # noqa: S311
                        continue
                    if status in (301, 302, 303, 307, 308):
                        return Response(url, status, response_headers, b"")
                    if status >= 400:
                        return Response(url, status, response_headers, raw.read()[: 64 * 1024])
                    content_type = response_headers.get("content-type", "").split(";")[0].strip().lower()
                    if accept and content_type not in accept:
                        raise FetchError(
                            "content_type_refused", f"{content_type or 'unknown'} is not read", status=status
                        )
                    declared = response_headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > self.max_bytes:
                        raise FetchError(
                            "too_large", f"{declared} bytes is over the {self.max_bytes} limit", status=status
                        )
                    body = bytearray()
                    for chunk in raw.iter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise FetchError("too_large", f"over the {self.max_bytes} byte limit", status=status)
                    return Response(url, status, response_headers, bytes(body))
            except httpx.TimeoutException as exc:
                last = FetchError("timeout", "the request timed out", retryable=True)
                if attempt < self.max_attempts and not unsafe:
                    self.sleep(random.uniform(0, 2.0 * 2 ** (attempt - 1)))  # noqa: S311
                    continue
                raise last from exc
            except httpx.TransportError as exc:
                last = FetchError("connection_failed", "the connection failed", retryable=True)
                if attempt < self.max_attempts and not unsafe:
                    self.sleep(random.uniform(0, 2.0 * 2 ** (attempt - 1)))  # noqa: S311
                    continue
                raise last from exc
            except httpx.HTTPError as exc:  # a corrupt body (DecodingError) and the like: this page fails, not the job
                raise FetchError("bad_response", f"the response could not be read: {type(exc).__name__}") from exc
        assert last is not None
        raise last
