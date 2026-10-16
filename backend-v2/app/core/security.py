"""
HTTP hardening shared by the clinical API and the platform routers.

* ``RateLimitMiddleware`` -- per-client sliding window. Its ``client_identity``
  is the single rule for "who is this client", used by the app-level limiter.
* ``SecurityHeadersMiddleware`` -- conservative response headers.
* ``BodySizeLimitMiddleware`` -- rejects oversized request bodies before they
  are buffered.
* ``require_secure_configuration`` -- refuses to start a production deployment
  that is missing its signing secret or allows any origin.
* ``normalize_token`` -- turns an ``Authorization`` header value into the raw
  token ``realtime.auth`` verifies.
"""

from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict, deque
from typing import Deque, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Upper bound on distinct clients tracked by the limiter.
MAX_TRACKED_CLIENTS = 10_000

_TOKEN_SCHEMES = ("bearer ", "dedan ")


def _is_production() -> bool:
    return get_settings().ENVIRONMENT.strip().lower() == "production"


def _error_body(error: str, error_code: str, details=None) -> dict:
    return {
        "error": error,
        "error_code": error_code,
        "details": details if details is not None else [],
        "timestamp": time.time(),
    }


def normalize_token(value: Optional[str]) -> Optional[str]:
    """Strip an optional ``Bearer``/``DEDAN`` scheme. Returns ``None`` when empty."""
    if not value:
        return None
    token = value.strip()
    lowered = token.lower()
    if lowered in {scheme.strip() for scheme in _TOKEN_SCHEMES}:
        return None
    for scheme in _TOKEN_SCHEMES:
        if lowered.startswith(scheme):
            token = token[len(scheme):].strip()
            break
    return token or None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter keyed by ``client_identity``.

    ``X-Forwarded-For`` is honoured only when ``TRUST_PROXY_HEADERS=true``;
    otherwise any client could mint a new identity per request by setting it.
    """

    EXEMPT_PATHS = frozenset({"/api/health", "/health", "/docs", "/redoc", "/openapi.json"})

    def __init__(self, app: ASGIApp, requests_per_window: int = 30, window_seconds: int = 60):
        super().__init__(app)
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._hits: "OrderedDict[str, Deque[float]]" = OrderedDict()

    @staticmethod
    def client_identity(request: Request) -> str:
        if os.getenv("TRUST_PROXY_HEADERS", "false").strip().lower() == "true":
            forwarded = request.headers.get("x-forwarded-for", "")
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        return request.client.host if request.client else "unknown"

    def hit(self, identity: str, now: Optional[float] = None) -> bool:
        """Record a request. Returns ``False`` when the client is over the limit."""
        now = time.time() if now is None else now
        window_start = now - self.window_seconds

        hits = self._hits.pop(identity, None)
        if hits is None:
            hits = deque()
        while hits and hits[0] <= window_start:
            hits.popleft()
        # Re-inserted at the end, so the dict stays ordered by last activity
        # and eviction below removes the least recently seen clients first.
        self._hits[identity] = hits

        if len(hits) >= self.requests_per_window:
            return False
        hits.append(now)

        while len(self._hits) > MAX_TRACKED_CLIENTS:
            self._hits.popitem(last=False)
        return True

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)
        if not self.hit(self.client_identity(request)):
            return JSONResponse(
                status_code=429,
                content=_error_body(
                    "Rate limit exceeded",
                    "RATE_LIMIT_EXCEEDED",
                    {
                        "limit": self.requests_per_window,
                        "window_seconds": self.window_seconds,
                        "retry_after": self.window_seconds,
                    },
                ),
                headers={"Retry-After": str(self.window_seconds)},
            )
        return await call_next(request)


class SecurityHeadersMiddleware:
    """Adds conservative security headers to every HTTP response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        production = _is_production()

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}

                def add(name: str, value: str) -> None:
                    if name.encode("latin-1") not in present:
                        headers.append((name.encode("latin-1"), value.encode("latin-1")))

                add("x-content-type-options", "nosniff")
                add("x-frame-options", "DENY")
                add("referrer-policy", "no-referrer")
                add("permissions-policy", "camera=(self), microphone=(self), geolocation=(self)")
                add("cross-origin-opener-policy", "same-origin")
                if production:
                    add("strict-transport-security", "max-age=31536000; includeSubDomains")
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodySizeLimitMiddleware:
    """Rejects request bodies larger than ``max_bytes`` with a 413.

    ``Content-Length`` is checked up front; bodies without it (chunked) are
    counted as they stream, so the limit cannot be bypassed by omitting the
    header.
    """

    def __init__(self, app: ASGIApp, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    def _too_large(self) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content=_error_body(
                "Request body too large",
                "PAYLOAD_TOO_LARGE",
                {"max_bytes": self.max_bytes},
            ),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
                if declared > self.max_bytes:
                    await self._too_large()(scope, receive, send)
                    return
                break

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if not response_started:
                await self._too_large()(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


def require_secure_configuration() -> None:
    """Fail closed on an insecure production configuration.

    Outside production the same problems are logged as warnings so local
    development keeps working without secrets.
    """
    settings = get_settings()
    problems = []

    from realtime.auth import signing_secret

    if not signing_secret():
        problems.append(
            "REALTIME_TOKEN_SECRET (or ADMIN_API_KEY) is not set: login tokens cannot be signed."
        )
    if "*" in (settings.CORS_ORIGINS or []):
        problems.append(
            "CORS_ORIGINS contains '*': credentialed requests would be accepted from any site."
        )
    if settings.DEBUG and _is_production():
        problems.append("DEBUG is true in production: API docs and error details would be exposed.")

    if not problems:
        return
    if _is_production():
        raise RuntimeError("Insecure production configuration: " + " ".join(problems))
    for problem in problems:
        logger.warning("insecure_configuration: %s", problem)
