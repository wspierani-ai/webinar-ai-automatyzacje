"""Tests for Google OAuth 2.0 + Token Management — Unit 12.

Covers:
- /connect-google generates valid OAuth URL with all required scopes
- Callback with bad state → 400, no token storage
- Callback with expired state (TTL) → 400
- get_valid_token calls refresh when token expired
- get_valid_token does NOT call refresh when token is valid
- Refresh failure → user marked as disconnected + Telegram notification
"""

from __future__ import annotations

import os
import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.example.com")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(doc_data: dict | None = None, doc_exists: bool = True) -> MagicMock:
    """Return a mock Firestore db."""
    db = MagicMock()

    doc = AsyncMock()
    doc.exists = doc_exists
    doc.to_dict = MagicMock(return_value=doc_data or {})

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()
    doc_ref.delete = AsyncMock()

    db.collection.return_value.document.return_value = doc_ref
    return db


def _future_expiry(minutes: int = 60) -> datetime:
    return datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)


def _past_expiry(minutes: int = 10) -> datetime:
    return datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Tests: OAuth URL generation
# ---------------------------------------------------------------------------

class TestConnectGoogleOAuthURL:
    """Tests for /connect-google command and OAuth URL generation."""

    @pytest.mark.asyncio
    async def test_build_oauth_url_contains_required_scopes(self):
        """build_oauth_url should include all required Google scopes."""
        from bot.services.google_auth import build_oauth_url, OAUTH_SCOPES

        url = build_oauth_url(state="test-state-123", redirect_uri="https://test.example.com/auth/google/callback")

        assert "calendar" in url
        assert "tasks" in url
        assert "openid" in url
        assert "test-state-123" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url

    @pytest.mark.asyncio
    async def test_build_oauth_url_includes_client_id(self):
        """build_oauth_url should include the configured client_id."""
        from bot.services.google_auth import build_oauth_url

        url = build_oauth_url(state="state-abc", redirect_uri="https://test.example.com/callback")

        assert "test-client-id" in url

    @pytest.mark.asyncio
    async def test_connect_google_handler_generates_state_and_sends_link(self):
        """handle_connect_google should generate state token and send OAuth URL."""
        from bot.handlers.google_oauth_handler import handle_connect_google

        db = _make_db()
        message = {
            "from": {"id": 111, "first_name": "Jan"},
            "chat": {"id": 111},
        }

        with patch(
            "bot.handlers.google_oauth_handler.generate_oauth_state",
            new=AsyncMock(return_value="generated-state-xyz"),
        ) as mock_gen_state, patch(
            "bot.handlers.google_oauth_handler._send_telegram_message",
            new=AsyncMock(),
        ) as mock_send:
            await handle_connect_google(message, db)

        mock_gen_state.assert_called_once_with(db, 111)
        mock_send.assert_called_once()
        # Link should be in the message text
        call_args = mock_send.call_args
        assert "generated-state-xyz" in call_args[0][1] or "generated-state-xyz" in str(call_args)


# ---------------------------------------------------------------------------
# Tests: State verification
# ---------------------------------------------------------------------------

class TestVerifyOAuthState:
    """Tests for verify_oauth_state function."""

    @pytest.mark.asyncio
    async def test_invalid_state_returns_none(self):
        """verify_oauth_state with non-existent state → None."""
        from bot.services.google_auth import verify_oauth_state

        doc = AsyncMock()
        doc.exists = False

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.delete = AsyncMock()

        db = MagicMock()
        db.collection.return_value.document.return_value = doc_ref

        result = await verify_oauth_state(db, "nonexistent-state")

        assert result is None

    @pytest.mark.asyncio
    async def test_expired_state_returns_none_and_deletes(self):
        """verify_oauth_state with expired state (TTL) → None, document deleted."""
        from bot.services.google_auth import verify_oauth_state

        past_expiry = _past_expiry(15)

        doc = AsyncMock()
        doc.exists = True
        doc.to_dict = MagicMock(
            return_value={
                "telegram_user_id": 123,
                "expires_at": past_expiry,
            }
        )

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.delete = AsyncMock()

        db = MagicMock()
        db.collection.return_value.document.return_value = doc_ref

        result = await verify_oauth_state(db, "expired-state")

        assert result is None
        doc_ref.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_state_returns_user_id_and_consumes_state(self):
        """verify_oauth_state with valid state → telegram_user_id, state deleted."""
        from bot.services.google_auth import verify_oauth_state

        future_expiry = _future_expiry(5)

        doc = AsyncMock()
        doc.exists = True
        doc.to_dict = MagicMock(
            return_value={
                "telegram_user_id": 456,
                "expires_at": future_expiry,
            }
        )

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.delete = AsyncMock()

        db = MagicMock()
        db.collection.return_value.document.return_value = doc_ref

        result = await verify_oauth_state(db, "valid-state")

        assert result == 456
        doc_ref.delete.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: get_valid_token — auto-refresh logic
# ---------------------------------------------------------------------------

class TestGetValidToken:
    """Tests for get_valid_token with auto-refresh."""

    @pytest.mark.asyncio
    async def test_returns_none_when_user_not_connected(self):
        """get_valid_token → None when google_connected=False."""
        from bot.services.google_auth import get_valid_token

        db = _make_db(
            doc_data={
                "google_connected": False,
                "google_refresh_token": None,
            },
            doc_exists=True,
        )

        result = await get_valid_token(db, 789)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_user_does_not_exist(self):
        """get_valid_token → None when user document not found."""
        from bot.services.google_auth import get_valid_token

        db = _make_db(doc_exists=False)

        result = await get_valid_token(db, 999)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_access_token_without_refresh_when_still_valid(self):
        """get_valid_token does NOT call refresh when token is valid (far future expiry)."""
        from bot.services.google_auth import get_valid_token, _encrypt_token

        valid_expiry = _future_expiry(60)  # 60 min in the future — well above 5 min buffer
        encrypted_access = _encrypt_token("valid-access-token")
        encrypted_refresh = _encrypt_token("valid-refresh-token")

        db = _make_db(
            doc_data={
                "google_connected": True,
                "google_access_token": encrypted_access,
                "google_refresh_token": encrypted_refresh,
                "google_token_expiry": valid_expiry,
            }
        )

        with patch(
            "bot.services.google_auth._refresh_access_token",
            new=AsyncMock(return_value="new-token"),
        ) as mock_refresh:
            result = await get_valid_token(db, 123)

        assert result == "valid-access-token"
        mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_refresh_when_token_expired(self):
        """get_valid_token calls refresh when token is expired."""
        from bot.services.google_auth import get_valid_token, _encrypt_token

        past_expiry = _past_expiry(30)  # 30 min in the past
        encrypted_access = _encrypt_token("old-access-token")
        encrypted_refresh = _encrypt_token("valid-refresh-token")

        db = _make_db(
            doc_data={
                "google_connected": True,
                "google_access_token": encrypted_access,
                "google_refresh_token": encrypted_refresh,
                "google_token_expiry": past_expiry,
            }
        )

        with patch(
            "bot.services.google_auth._refresh_access_token",
            new=AsyncMock(return_value="new-access-token"),
        ) as mock_refresh:
            result = await get_valid_token(db, 123)

        mock_refresh.assert_called_once()
        assert result == "new-access-token"

    @pytest.mark.asyncio
    async def test_calls_refresh_when_token_near_expiry(self):
        """get_valid_token calls refresh when token expires within 5 min buffer."""
        from bot.services.google_auth import get_valid_token, _encrypt_token

        near_expiry = datetime.now(tz=timezone.utc) + timedelta(minutes=3)  # within 5 min buffer
        encrypted_access = _encrypt_token("almost-expired-token")
        encrypted_refresh = _encrypt_token("refresh-token")

        db = _make_db(
            doc_data={
                "google_connected": True,
                "google_access_token": encrypted_access,
                "google_refresh_token": encrypted_refresh,
                "google_token_expiry": near_expiry,
            }
        )

        with patch(
            "bot.services.google_auth._refresh_access_token",
            new=AsyncMock(return_value="refreshed-token"),
        ) as mock_refresh:
            result = await get_valid_token(db, 123)

        mock_refresh.assert_called_once()
        assert result == "refreshed-token"


# ---------------------------------------------------------------------------
# Tests: Refresh failure → disconnect + notification
# ---------------------------------------------------------------------------

class TestRefreshFailure:
    """Tests for refresh failure behavior."""

    @pytest.mark.asyncio
    async def test_refresh_failure_marks_user_as_disconnected(self):
        """On refresh failure, user is marked as google_connected=False."""
        from bot.services.google_auth import _refresh_access_token

        db = MagicMock()
        doc_ref = AsyncMock()
        doc_ref.update = AsyncMock()
        db.collection.return_value.document.return_value = doc_ref

        with patch(
            "bot.services.google_auth._mark_google_disconnected",
            new=AsyncMock(),
        ) as mock_disconnect, patch(
            "bot.services.google_auth._send_reconnect_notification",
            new=AsyncMock(),
        ) as mock_notify, patch(
            "httpx.AsyncClient",
            side_effect=Exception("network error"),
        ):
            result = await _refresh_access_token(db, 123, "bad-refresh-token")

        assert result is None
        mock_disconnect.assert_called_once_with(db, 123)

    @pytest.mark.asyncio
    async def test_refresh_failure_sends_telegram_notification(self):
        """On refresh failure, Telegram reconnect notification is sent."""
        from bot.services.google_auth import _refresh_access_token

        db = MagicMock()
        doc_ref = AsyncMock()
        doc_ref.update = AsyncMock()
        db.collection.return_value.document.return_value = doc_ref

        with patch(
            "bot.services.google_auth._mark_google_disconnected",
            new=AsyncMock(),
        ), patch(
            "bot.services.google_auth._send_reconnect_notification",
            new=AsyncMock(),
        ) as mock_notify, patch(
            "httpx.AsyncClient",
            side_effect=Exception("network error"),
        ):
            await _refresh_access_token(db, 456, "bad-refresh-token")

        mock_notify.assert_called_once_with(456)


# ---------------------------------------------------------------------------
# Tests: Token encryption
# ---------------------------------------------------------------------------

class TestTokenEncryption:
    """Tests for AES-256 token encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """_encrypt_token and _decrypt_token are inverse operations."""
        from bot.services.google_auth import _encrypt_token, _decrypt_token

        original = "ya29.a0AbcDef-test-access-token"
        encrypted = _encrypt_token(original)

        assert encrypted != original
        decrypted = _decrypt_token(encrypted)
        assert decrypted == original

    def test_encrypted_token_is_base64(self):
        """Encrypted token should be valid base64."""
        from bot.services.google_auth import _encrypt_token

        encrypted = _encrypt_token("some-token")
        # Should not raise
        base64.b64decode(encrypted)

    def test_different_tokens_produce_different_ciphertexts(self):
        """Different tokens should produce different encrypted values."""
        from bot.services.google_auth import _encrypt_token

        enc1 = _encrypt_token("token-a")
        enc2 = _encrypt_token("token-b")
        assert enc1 != enc2


# ---------------------------------------------------------------------------
# Tests: disconnect_google
# ---------------------------------------------------------------------------

class TestDisconnectGoogle:
    """Tests for disconnect_google function."""

    @pytest.mark.asyncio
    async def test_disconnect_clears_google_tokens(self):
        """disconnect_google removes all Google-related fields from user document."""
        from bot.services.google_auth import disconnect_google

        db = MagicMock()
        doc_ref = AsyncMock()
        doc_ref.update = AsyncMock()
        db.collection.return_value.document.return_value = doc_ref

        await disconnect_google(db, 789)

        doc_ref.update.assert_called_once()
        update_data = doc_ref.update.call_args[0][0]
        assert update_data.get("google_connected") is False
        assert update_data.get("google_access_token") is None
        assert update_data.get("google_refresh_token") is None
        assert update_data.get("google_token_expiry") is None


# ---------------------------------------------------------------------------
# Tests: OAuth callback endpoint
# ---------------------------------------------------------------------------

class TestOAuthCallbackEndpoint:
    """Tests for /auth/google/callback endpoint."""

    @pytest.mark.asyncio
    async def test_callback_with_bad_state_returns_400(self):
        """Callback with unknown state → 400."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.google_oauth_handler import router

        app = FastAPI()
        app.include_router(router)

        with patch(
            "bot.handlers.google_oauth_handler.get_firestore_client",
        ) as mock_db_fn, patch(
            "bot.handlers.google_oauth_handler.verify_oauth_state",
            new=AsyncMock(return_value=None),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/auth/google/callback",
                    params={"code": "test-code", "state": "bad-state"},
                )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_with_missing_state_returns_400(self):
        """Callback without state param → 400."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.google_oauth_handler import router

        app = FastAPI()
        app.include_router(router)

        with patch("bot.handlers.google_oauth_handler.get_firestore_client"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/auth/google/callback",
                    params={"code": "test-code"},
                )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_with_oauth_error_returns_400(self):
        """Callback with error param from Google → 400."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.google_oauth_handler import router

        app = FastAPI()
        app.include_router(router)

        with patch("bot.handlers.google_oauth_handler.get_firestore_client"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/auth/google/callback",
                    params={"error": "access_denied", "state": "some-state"},
                )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_callback_saves_tokens_and_sends_telegram_on_success(self):
        """Successful callback → tokens saved, Telegram confirmation sent."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.google_oauth_handler import router

        app = FastAPI()
        app.include_router(router)

        mock_token_data = {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 3600,
        }

        with patch("bot.handlers.google_oauth_handler.get_firestore_client"), \
             patch(
                 "bot.handlers.google_oauth_handler.verify_oauth_state",
                 new=AsyncMock(return_value=123),
             ), \
             patch(
                 "bot.handlers.google_oauth_handler.exchange_code_for_tokens",
                 new=AsyncMock(return_value=mock_token_data),
             ), \
             patch(
                 "bot.handlers.google_oauth_handler.save_tokens",
                 new=AsyncMock(),
             ) as mock_save, \
             patch(
                 "bot.handlers.google_oauth_handler._send_telegram_message",
                 new=AsyncMock(),
             ) as mock_send, \
             patch(
                 "bot.handlers.google_oauth_handler._fetch_google_resource_ids",
                 new=AsyncMock(return_value=("primary", "@default")),
             ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/auth/google/callback",
                    params={"code": "valid-code", "state": "valid-state"},
                )

        assert resp.status_code == 200
        mock_save.assert_called_once()
        mock_send.assert_called_once()
        # Check Telegram message is the success confirmation
        sent_text = mock_send.call_args[0][1]
        assert "połączone" in sent_text.lower() or "połączon" in sent_text.lower()
