"""Admin authentication middleware — FastAPI dependencies.

Provides require_admin and require_admin_write as FastAPI Depends.
Also provides audit log middleware for POST/PATCH/DELETE on /admin/*.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from bot.admin.auth import (
    _COOKIE_NAME,
    create_audit_log,
    decode_jwt_token,
)
from bot.services.firestore_client import get_firestore_client

logger = logging.getLogger(__name__)


class AdminSession:
    """Represents an authenticated admin session."""

    def __init__(self, email: str, role: str):
        self.email = email
        self.role = role

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_read_only(self) -> bool:
        return self.role == "read-only"


def _get_session_from_request(request: Request) -> Optional[AdminSession]:
    """Extract and validate admin session from request cookie."""
    token = request.cookies.get(_COOKIE_NAME)
    if not token:
        return None

    payload = decode_jwt_token(token)
    if not payload:
        return None

    email = payload.get("email", "")
    role = payload.get("role", "read-only")
    if not email:
        return None

    return AdminSession(email=email, role=role)


async def require_admin(request: Request) -> AdminSession:
    """FastAPI dependency: require any admin role (read-only or admin).

    Returns AdminSession on success, redirects to login on failure.
    """
    session = _get_session_from_request(request)
    if session is None:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return session


async def require_admin_write(request: Request) -> AdminSession:
    """FastAPI dependency: require admin role with write access.

    Returns AdminSession on success, 403 for read-only, redirect for unauthenticated.
    Validates X-Requested-With header for CSRF protection on write operations.
    """
    session = _get_session_from_request(request)
    if session is None:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    if session.is_read_only:
        raise HTTPException(status_code=403, detail="Write access required")

    # CSRF protection: require custom header on write operations
    requested_with = request.headers.get("x-requested-with", "")
    if requested_with != "XMLHttpRequest":
        raise HTTPException(status_code=403, detail="Missing CSRF header")

    return session


class AdminAuditMiddleware(BaseHTTPMiddleware):
    """Middleware that logs POST/PATCH/DELETE actions on /admin/* to audit log."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not request.url.path.startswith("/admin"):
            return await call_next(request)

        if request.method not in ("POST", "PATCH", "DELETE"):
            return await call_next(request)

        session = _get_session_from_request(request)
        response = await call_next(request)

        if session is not None and response.status_code < 400:
            db = get_firestore_client()
            ip = request.client.host if request.client else ""
            user_agent = request.headers.get("user-agent", "")
            action = f"{request.method} {request.url.path}"

            await create_audit_log(
                db=db,
                admin_email=session.email,
                action=action,
                target=request.url.path,
                ip=ip,
                user_agent=user_agent,
            )

        return response
