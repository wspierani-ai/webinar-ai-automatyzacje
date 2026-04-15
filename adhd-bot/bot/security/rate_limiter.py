"""Rate limiting configuration using slowapi.

Per-endpoint limits:
  /telegram/webhook:     30/minute per IP
  /auth/google/callback: 10/minute per IP (brute-force protection)
  /admin/*:              100/minute per IP
  /stripe/webhook:       unlimited (Stripe IPs)
  /internal/*:           unlimited (OIDC protected)
"""

from __future__ import annotations

import logging

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _key_func(request: Request) -> str:
    """Extract client IP for rate limiting."""
    return get_remote_address(request)


limiter = Limiter(key_func=_key_func)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Handler for 429 Too Many Requests."""
    logger.warning(
        "Rate limit exceeded: %s %s from %s",
        request.method,
        request.url.path,
        _key_func(request),
    )
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "RATE_LIMITED", "message": "Too many requests. Please try again later."}},
    )


# Applied decorators:
# @limiter.limit("30/minute")  → on /telegram/webhook
# @limiter.limit("10/minute")  → on /auth/google/callback
# @limiter.limit("100/minute") → on /admin/* routes
# /stripe/webhook and /internal/* are unlimited (Stripe IPs / OIDC protected)
