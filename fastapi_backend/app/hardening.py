"""Production safety: startup checks, security headers, auth rate limiting.

All three are no-ops in development by default — they only tighten when
APP_ENV=production, except the rate limit, which is always on because
credential stuffing doesn't wait for production.
"""
import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-only-insecure-secret-change-me-in-production-0123456789"


def check_production_config() -> None:
    """Refuse to start a production process with development secrets.

    A default signing key means anyone who has read the repository can mint
    admin tokens, so this is a hard failure rather than a warning.
    """
    if not settings.is_production:
        return

    problems = []
    if settings.JWT_SECRET_KEY == DEFAULT_JWT_SECRET or len(settings.JWT_SECRET_KEY) < 32:
        problems.append(
            "JWT_SECRET_KEY is the built-in development value (or too short). Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    if "*" in settings.CORS_ORIGINS:
        problems.append("CORS_ORIGINS is '*'; list the exact origins the storefront is served from.")
    if settings.DATABASE_URL.startswith("sqlite"):
        problems.append("DATABASE_URL points at SQLite; production expects MySQL.")
    if settings.AUTO_CREATE_SCHEMA:
        problems.append("AUTO_CREATE_SCHEMA is on; production schema changes belong to `alembic upgrade head`.")
    if problems:
        raise RuntimeError(
            "Refusing to start with APP_ENV=production:\n  - " + "\n  - ".join(problems)
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Response headers that cost nothing and close off whole bug classes."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # The storefront never frames itself, and the admin is a separate app.
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if settings.is_production and settings.HSTS_SECONDS > 0:
            response.headers.setdefault(
                "Strict-Transport-Security", f"max-age={settings.HSTS_SECONDS}; includeSubDomains"
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limit on the endpoints worth guessing at.

    In-memory and per-process: it stops casual credential stuffing and
    runaway scripts, not a distributed attack. With more than one worker,
    move this to Redis (or put the limit in the proxy) — see
    docs/DEPLOYMENT.md.
    """

    def __init__(self, app, paths=None, limit: int = 10, window_seconds: int = 60):
        super().__init__(app)
        self.paths = tuple(paths or ())
        self.limit = limit
        self.window = window_seconds
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def _client(self, request: Request) -> str:
        # X-Forwarded-For only when a proxy is declared, so a client can't
        # spoof its way into a fresh bucket.
        if settings.TRUST_PROXY_HEADERS:
            forwarded = request.headers.get("x-forwarded-for", "")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            path = path[4:]
        if request.method != "POST" or not path.startswith(self.paths):
            return await call_next(request)

        key = f"{self._client(request)}:{path}"
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            retry_after = int(self.window - (now - hits[0])) + 1
            logger.warning("Rate limit hit for %s", key)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Too many attempts. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        return await call_next(request)


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
