"""Web security helpers: a rate limiter, cross-site request checks and security headers.

Three small pieces, each easy to test on its own:

* ``RateLimiter`` allows N events per time window per key (a sliding window kept in memory).
* ``CrossSiteGuard`` rejects state-changing requests that a browser says came from another
  site (CSRF protection without form tokens, see ADR 0020).
* ``SecurityHeadersMiddleware`` adds the response headers that stop framing and sniffing.
"""

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class RateLimiter:
    """Sliding-window limiter: at most ``limit`` hits per ``window_seconds`` for each key.

    State lives in this process's memory, which is right for one web process (the demo and
    the Docker setup). Behind several processes each would count separately; use a shared
    store such as Redis then.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window_seconds:
            hits.popleft()
        if not hits:
            self._hits.pop(key, None)
            return deque()
        return hits

    def allow(self, key: str) -> bool:
        """Count one hit for ``key``. Returns False (and does not count) when over the limit."""
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) >= self.limit:
            return False
        if not hits:
            hits = self._hits[key]
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        """Whole seconds until ``key`` may try again (0 when it is not blocked)."""
        now = self._clock()
        hits = self._prune(key, now)
        if len(hits) < self.limit:
            return 0
        return max(1, int(hits[0] + self.window_seconds - now) + 1)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


def client_ip(request: Request) -> str:
    """The caller's address.

    Only behind a reverse proxy you control (Render, Fly, nginx) does the first
    ``X-Forwarded-For`` entry hold the real address, so it is read only when
    ``GBA_TRUST_PROXY`` is on. Otherwise anyone could pick their own address and dodge the
    limiter by sending the header.
    """
    if request.app.state.settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def is_cross_site(request: Request) -> bool:
    """True when a browser marks this request as coming from another site.

    Browsers send ``Sec-Fetch-Site`` (and ``Origin`` on POSTs) themselves; a page on another
    site cannot forge them. Clients that send neither (curl, test clients, native apps) carry
    no ambient login cookie, so they are not a CSRF risk and are let through.
    """
    if request.method in SAFE_METHODS:
        return False
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site not in ("same-origin", "none")
    origin = request.headers.get("origin")
    if origin is not None:
        host = request.headers.get("host", "")
        return origin == "null" or urlsplit(origin).netloc != host
    return False


class CrossSiteGuard(BaseHTTPMiddleware):
    """Answer 403 to cross-site state-changing requests before any route runs."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if is_cross_site(request):
            return PlainTextResponse("Cross-site request refused.", status_code=403)
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add headers that stop clickjacking, content sniffing and leaking the URL elsewhere."""

    def __init__(self, app: Callable[..., Awaitable[None]], *, hsts: bool) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # A full script policy needs the Tailwind CDN and inline scripts removed first (ADR 0020);
        # these directives are the parts that already hold today.
        headers.setdefault(
            "Content-Security-Policy",
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
        )
        if self.hsts:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response
