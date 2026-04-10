"""Admin authentication — Google SSO + JWT session management.

OAuth flow:
  GET /admin/login → redirect to Google OAuth
  GET /admin/auth/callback?code=... → verify email in admin_users → set JWT cookie
  GET /admin/logout → clear cookie
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from bot.security.rate_limiter import limiter
from bot.services.firestore_client import get_firestore_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin-auth"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_JWT_ALGORITHM = "HS256"
_JWT_EXPIRY_HOURS = 8
_COOKIE_NAME = "admin_session"
_ADMIN_STATE_TTL_MINUTES = 10


def _get_jwt_secret() -> str:
    """Return JWT signing secret from env."""
    return os.environ.get("ADMIN_JWT_SECRET", "test-jwt-secret-for-dev")


def _get_admin_oauth_config() -> dict:
    """Return OAuth config for admin login (separate from user OAuth)."""
    return {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
    }


def create_jwt_token(email: str, role: str) -> str:
    """Create a signed JWT token with email, role, and expiry."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=_JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, _get_jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_jwt_token(token: str) -> Optional[dict]:
    """Decode and verify JWT token. Returns payload dict or None if invalid/expired."""
    try:
        payload = jwt.decode(
            token,
            _get_jwt_secret(),
            algorithms=[_JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("Admin JWT expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid admin JWT: %s", exc)
        return None


async def _exchange_code_for_token(code: str, redirect_uri: str, config: dict) -> Optional[dict]:
    """Exchange OAuth code for tokens. Returns token data or None on failure."""
    async with httpx.AsyncClient(timeout=15.0) as http_client:
        resp = await http_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        logger.warning("Admin OAuth token exchange failed: %s", resp.text)
        return None
    return resp.json()


async def _get_google_userinfo(access_token: str) -> Optional[dict]:
    """Fetch Google user info. Returns user info dict or None on failure."""
    async with httpx.AsyncClient(timeout=10.0) as http_client:
        resp = await http_client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code != 200:
        return None
    return resp.json()


def _generate_admin_state() -> str:
    """Generate a URL-safe random state token for OAuth CSRF protection."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(32))


async def _save_admin_oauth_state(db, state: str) -> None:
    """Persist admin OAuth state to Firestore with TTL."""
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(minutes=_ADMIN_STATE_TTL_MINUTES)
    doc_ref = db.collection("admin_oauth_states").document(state)
    await doc_ref.set({
        "created_at": now,
        "expires_at": expires_at,
    })


async def _verify_admin_oauth_state(db, state: str) -> bool:
    """Verify and consume admin OAuth state token. Returns True if valid."""
    if not state:
        return False

    doc_ref = db.collection("admin_oauth_states").document(state)
    doc = await doc_ref.get()

    if not doc.exists:
        return False

    data = doc.to_dict()
    expires_at = data.get("expires_at")

    if expires_at is not None:
        now = datetime.now(tz=timezone.utc)
        if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            await doc_ref.delete()
            return False

    # Consume state (single-use)
    await doc_ref.delete()
    return True


@router.get("/login")
@limiter.limit("100/minute")
async def admin_login(request: Request) -> RedirectResponse:
    """Redirect to Google OAuth for admin login with state CSRF token."""
    config = _get_admin_oauth_config()
    service_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    redirect_uri = f"{service_url}/admin/auth/callback"

    db = get_firestore_client()
    state = _generate_admin_state()
    await _save_admin_oauth_state(db, state)

    params = {
        "client_id": config["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/auth/callback")
@limiter.limit("100/minute")
async def admin_auth_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> Response:
    """Handle Google OAuth callback for admin login."""
    if error or not code:
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1><p>Brak autoryzacji.</p>",
            status_code=400,
        )

    # Verify OAuth state token (CSRF protection)
    db = get_firestore_client()
    is_valid_state = await _verify_admin_oauth_state(db, state)
    if not is_valid_state:
        logger.warning("Admin OAuth callback with invalid/expired state")
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1><p>Nieprawidłowy lub wygasły token autoryzacji.</p>",
            status_code=400,
        )

    config = _get_admin_oauth_config()
    service_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    redirect_uri = f"{service_url}/admin/auth/callback"

    # Exchange code for tokens
    try:
        token_data = await _exchange_code_for_token(code, redirect_uri, config)
    except Exception as exc:
        logger.error("Admin OAuth token exchange error: %s", exc)
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1><p>Serwer error.</p>",
            status_code=500,
        )

    if token_data is None:
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1><p>Token exchange failed.</p>",
            status_code=400,
        )

    # Get user info
    try:
        access_token = token_data.get("access_token", "")
        userinfo = await _get_google_userinfo(access_token)
    except Exception as exc:
        logger.error("Admin OAuth userinfo error: %s", exc)
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1>",
            status_code=500,
        )

    if userinfo is None:
        return HTMLResponse(
            content="<h1>Logowanie nieudane</h1>",
            status_code=400,
        )

    email = userinfo.get("email", "").lower()
    if not email:
        return HTMLResponse(
            content="<h1>Brak emaila</h1>",
            status_code=400,
        )

    # Check if email is in admin_users (db already obtained above for state verification)
    admin_doc = await db.collection("admin_users").document(email).get()

    if not admin_doc.exists:
        logger.warning("Admin login attempt from non-admin email: %s", email)
        return HTMLResponse(
            content="<h1>Brak dostępu</h1><p>Ten email nie jest uprawniony do panelu admina.</p>",
            status_code=403,
        )

    admin_data = admin_doc.to_dict()
    role = admin_data.get("role", "read-only")

    # Update last_login
    await db.collection("admin_users").document(email).update(
        {"last_login": datetime.now(tz=timezone.utc)}
    )

    # Create JWT and set cookie
    token = create_jwt_token(email, role)
    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=_JWT_EXPIRY_HOURS * 3600,
    )
    return response


@router.get("/logout")
@limiter.limit("100/minute")
async def admin_logout(request: Request) -> RedirectResponse:
    """Clear admin session cookie and redirect to login."""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie(key=_COOKIE_NAME)
    return response


async def create_audit_log(
    db,
    admin_email: str,
    action: str,
    target: Optional[str] = None,
    ip: str = "",
    user_agent: str = "",
) -> None:
    """Record an admin action in the audit log."""
    try:
        await db.collection("admin_audit_log").add(
            {
                "timestamp": datetime.now(tz=timezone.utc),
                "admin_email": admin_email,
                "action": action,
                "target": target,
                "ip": ip,
                "user_agent": user_agent,
            }
        )
    except Exception as exc:
        logger.error("Failed to create audit log: %s", exc)
