"""Google OAuth 2.0 service — token management with auto-refresh.

Handles:
- OAuth state token generation (nanoid, TTL=10 min, stored in Firestore)
- OAuth URL building with required scopes
- Token exchange and storage (AES-256 encrypted in Firestore)
- get_valid_token: auto-refresh when access_token expires within 5 min
- disconnect_google: clear tokens from Firestore
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.security.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

GOOGLE_AUTH_BASE = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/tasks",
]

_STATE_TTL_MINUTES = 10
_TOKEN_REFRESH_BUFFER_MINUTES = 5


def _nanoid(length: int = 21) -> str:
    """Generate a URL-safe random ID (nanoid replacement without extra deps)."""
    alphabet = string.ascii_letters + string.digits + "-_"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _encrypt_token(plaintext: str) -> str:
    """Encrypt token string. Delegates to bot.security.encryption."""
    return encrypt(plaintext)


def _decrypt_token(encrypted: str) -> str:
    """Decrypt token string. Delegates to bot.security.encryption."""
    return decrypt(encrypted)


async def generate_oauth_state(db, telegram_user_id: int) -> str:
    """Generate an OAuth state token, persist to Firestore with TTL, return it."""
    state = _nanoid(32)
    now = datetime.now(tz=timezone.utc)
    expires_at = now + timedelta(minutes=_STATE_TTL_MINUTES)

    doc_ref = db.collection("oauth_states").document(state)
    await doc_ref.set(
        {
            "telegram_user_id": telegram_user_id,
            "created_at": now,
            "expires_at": expires_at,
        }
    )
    return state


async def verify_oauth_state(db, state: str) -> Optional[int]:
    """Verify OAuth state token. Returns telegram_user_id or None if invalid/expired."""
    doc_ref = db.collection("oauth_states").document(state)
    doc = await doc_ref.get()

    if not doc.exists:
        return None

    data = doc.to_dict()
    expires_at = data.get("expires_at")

    if expires_at is not None:
        now = datetime.now(tz=timezone.utc)
        # Handle both timezone-aware and naive datetimes from Firestore
        if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            await doc_ref.delete()
            return None

    # Consume state (single-use)
    await doc_ref.delete()

    user_id = data.get("telegram_user_id")
    return user_id if isinstance(user_id, int) else None


def build_oauth_url(state: str, redirect_uri: str) -> str:
    """Build Google OAuth authorization URL."""
    from urllib.parse import urlencode

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{GOOGLE_AUTH_BASE}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens.

    Returns dict with keys: access_token, refresh_token, expires_in.
    Raises ValueError on failure.
    """
    import httpx

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )

    if resp.status_code != 200:
        raise ValueError(f"Token exchange failed: {resp.text}")

    return resp.json()


async def save_tokens(
    db,
    telegram_user_id: int,
    access_token: str,
    refresh_token: str,
    expires_in: int,
    google_calendar_id: str = "primary",
    google_tasks_list_id: str = "@default",
) -> None:
    """Encrypt and persist Google tokens to Firestore user document."""
    now = datetime.now(tz=timezone.utc)
    token_expiry = now + timedelta(seconds=expires_in)

    encrypted_access = _encrypt_token(access_token)
    encrypted_refresh = _encrypt_token(refresh_token)

    doc_ref = db.collection("users").document(str(telegram_user_id))
    await doc_ref.update(
        {
            "google_access_token": encrypted_access,
            "google_refresh_token": encrypted_refresh,
            "google_token_expiry": token_expiry,
            "google_connected": True,
            "google_calendar_id": google_calendar_id,
            "google_tasks_list_id": google_tasks_list_id,
            "updated_at": now,
        }
    )


async def get_valid_token(db, telegram_user_id: int) -> Optional[str]:
    """Return a valid access token for the user, refreshing if near expiry.

    Returns None if user has no Google connection or refresh fails.
    """
    doc_ref = db.collection("users").document(str(telegram_user_id))
    doc = await doc_ref.get()

    if not doc.exists:
        return None

    data = doc.to_dict()
    if not data.get("google_connected") or not data.get("google_refresh_token"):
        return None

    encrypted_access = data.get("google_access_token")
    encrypted_refresh = data.get("google_refresh_token")
    token_expiry = data.get("google_token_expiry")

    # Check if access token is still valid (with buffer)
    if token_expiry is not None and encrypted_access:
        now = datetime.now(tz=timezone.utc)
        if hasattr(token_expiry, "tzinfo") and token_expiry.tzinfo is None:
            token_expiry = token_expiry.replace(tzinfo=timezone.utc)
        if now < token_expiry - timedelta(minutes=_TOKEN_REFRESH_BUFFER_MINUTES):
            return _decrypt_token(encrypted_access)

    # Token expired or missing — refresh it
    if not encrypted_refresh:
        return None

    refresh_token = _decrypt_token(encrypted_refresh)
    new_access_token = await _refresh_access_token(
        db, telegram_user_id, refresh_token
    )
    return new_access_token


async def _refresh_access_token(
    db, telegram_user_id: int, refresh_token: str
) -> Optional[str]:
    """Perform a token refresh. Returns new access token or None on failure."""
    import httpx

    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    # Phase 1: HTTP request to Google token endpoint
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "grant_type": "refresh_token",
                },
            )
    except Exception as exc:
        logger.error(
            "Network error during token refresh for user %s: %s",
            telegram_user_id,
            exc,
        )
        await _mark_google_disconnected(db, telegram_user_id)
        await _send_reconnect_notification(telegram_user_id)
        return None

    if resp.status_code != 200:
        logger.warning(
            "Token refresh failed for user %s: %s", telegram_user_id, resp.text
        )
        await _mark_google_disconnected(db, telegram_user_id)
        await _send_reconnect_notification(telegram_user_id)
        return None

    # Phase 2: Parse response and persist tokens (errors here should propagate)
    token_data = resp.json()
    access_token = token_data.get("access_token", "")
    expires_in = token_data.get("expires_in", 3600)

    now = datetime.now(tz=timezone.utc)
    token_expiry = now + timedelta(seconds=expires_in)

    doc_ref = db.collection("users").document(str(telegram_user_id))
    await doc_ref.update(
        {
            "google_access_token": _encrypt_token(access_token),
            "google_token_expiry": token_expiry,
            "updated_at": now,
        }
    )
    return access_token


async def _mark_google_disconnected(db, telegram_user_id: int) -> None:
    """Clear Google tokens and mark user as disconnected."""
    doc_ref = db.collection("users").document(str(telegram_user_id))
    try:
        await doc_ref.update(
            {
                "google_connected": False,
                "google_access_token": None,
                "google_refresh_token": None,
                "google_token_expiry": None,
                "updated_at": datetime.now(tz=timezone.utc),
            }
        )
    except Exception as exc:
        logger.error("Failed to mark user %s as disconnected: %s", telegram_user_id, exc)


async def _send_reconnect_notification(telegram_user_id: int) -> None:
    """Notify user that Google integration needs to be reconnected."""
    if os.environ.get("TESTING") == "1":
        return

    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    text = (
        "⚠️ Połączenie z Google zostało przerwane. "
        "Aby je odnowić, użyj komendy /connect-google."
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                url,
                json={"chat_id": telegram_user_id, "text": text},
            )
    except Exception as exc:
        logger.error("Failed to send reconnect notification to %s: %s", telegram_user_id, exc)


async def disconnect_google(db, telegram_user_id: int) -> None:
    """Remove all Google tokens from user document."""
    await _mark_google_disconnected(db, telegram_user_id)
    logger.info("Google disconnected for user %s", telegram_user_id)
