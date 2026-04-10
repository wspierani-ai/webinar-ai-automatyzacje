"""Tests for bot.admin.auth and bot.admin.middleware — Admin authentication."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_SECRET_TOKEN", "test-secret")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.run.app")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-jwt-secret-for-dev")

from bot.admin.auth import (
    _COOKIE_NAME,
    _JWT_ALGORITHM,
    _get_jwt_secret,
    create_audit_log,
    create_jwt_token,
    decode_jwt_token,
    router as auth_router,
)
from bot.admin.middleware import (
    AdminAuditMiddleware,
    AdminSession,
    require_admin,
    require_admin_write,
)


class TestJwtTokenCreation:
    """Test JWT token creation and decoding."""

    def test_create_and_decode_valid_token(self):
        token = create_jwt_token("admin@example.com", "admin")
        payload = decode_jwt_token(token)
        assert payload is not None
        assert payload["email"] == "admin@example.com"
        assert payload["role"] == "admin"

    def test_expired_token_returns_none(self):
        """Token with expiry in the past returns None."""
        secret = _get_jwt_secret()
        payload = {
            "email": "admin@example.com",
            "role": "admin",
            "iat": datetime.now(tz=timezone.utc) - timedelta(hours=10),
            "exp": datetime.now(tz=timezone.utc) - timedelta(hours=1),
        }
        token = jwt.encode(payload, secret, algorithm=_JWT_ALGORITHM)
        result = decode_jwt_token(token)
        assert result is None

    def test_invalid_token_returns_none(self):
        result = decode_jwt_token("invalid.jwt.token")
        assert result is None

    def test_wrong_secret_returns_none(self):
        payload = {
            "email": "admin@example.com",
            "role": "admin",
            "iat": datetime.now(tz=timezone.utc),
            "exp": datetime.now(tz=timezone.utc) + timedelta(hours=8),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm=_JWT_ALGORITHM)
        result = decode_jwt_token(token)
        assert result is None


class TestAuthCallback:
    """Test /admin/auth/callback endpoint."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.include_router(auth_router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=False)

    def test_callback_with_non_admin_email_returns_403(self, client):
        """Email not in admin_users collection returns 403."""
        mock_db = MagicMock()
        mock_admin_doc = AsyncMock()
        mock_admin_doc.exists = False
        mock_db.collection.return_value.document.return_value.get = AsyncMock(
            return_value=mock_admin_doc
        )

        with (
            patch("bot.admin.auth.get_firestore_client", return_value=mock_db),
            patch(
                "bot.admin.auth._exchange_code_for_token",
                new_callable=AsyncMock,
                return_value={"access_token": "fake-access"},
            ),
            patch(
                "bot.admin.auth._get_google_userinfo",
                new_callable=AsyncMock,
                return_value={"email": "notadmin@example.com", "name": "Not Admin"},
            ),
        ):
            response = client.get(
                "/admin/auth/callback?code=fake-code", follow_redirects=False
            )

        assert response.status_code == 403

    def test_callback_with_admin_email_sets_jwt_cookie(self, client):
        """Valid admin email results in JWT cookie and redirect to /admin."""
        mock_db = MagicMock()
        mock_admin_doc = MagicMock()  # MagicMock, not AsyncMock — to_dict() is sync
        mock_admin_doc.exists = True
        mock_admin_doc.to_dict.return_value = {"role": "admin", "name": "Admin User"}
        mock_db.collection.return_value.document.return_value.get = AsyncMock(
            return_value=mock_admin_doc
        )
        mock_db.collection.return_value.document.return_value.update = AsyncMock()

        with (
            patch("bot.admin.auth.get_firestore_client", return_value=mock_db),
            patch(
                "bot.admin.auth._exchange_code_for_token",
                new_callable=AsyncMock,
                return_value={"access_token": "fake-access"},
            ),
            patch(
                "bot.admin.auth._get_google_userinfo",
                new_callable=AsyncMock,
                return_value={"email": "admin@example.com", "name": "Admin User"},
            ),
        ):
            response = client.get(
                "/admin/auth/callback?code=fake-code", follow_redirects=False
            )

        assert response.status_code == 302
        assert response.headers.get("location") == "/admin"
        assert _COOKIE_NAME in response.cookies


class TestRequireAdmin:
    """Test require_admin and require_admin_write dependencies."""

    @pytest.fixture
    def app(self):
        app = FastAPI()

        @app.get("/admin/test-read")
        async def test_read(session: AdminSession = pytest.importorskip("fastapi").Depends(require_admin)):
            return {"email": session.email, "role": session.role}

        @app.get("/admin/test-write")
        async def test_write(session: AdminSession = pytest.importorskip("fastapi").Depends(require_admin_write)):
            return {"email": session.email}

        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=False)

    def test_request_without_cookie_redirects_to_login(self, client):
        """No admin_session cookie → redirect to /admin/login."""
        response = client.get("/admin/test-read", follow_redirects=False)
        assert response.status_code == 302
        assert "/admin/login" in response.headers.get("location", "")

    def test_request_with_expired_jwt_redirects_to_login(self, client):
        """Expired JWT → redirect to /admin/login."""
        secret = _get_jwt_secret()
        expired_payload = {
            "email": "admin@example.com",
            "role": "admin",
            "iat": datetime.now(tz=timezone.utc) - timedelta(hours=10),
            "exp": datetime.now(tz=timezone.utc) - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, secret, algorithm=_JWT_ALGORITHM)
        client.cookies.set(_COOKIE_NAME, expired_token)
        response = client.get("/admin/test-read", follow_redirects=False)
        assert response.status_code == 302

    def test_require_admin_write_with_read_only_role_returns_403(self, client):
        """Read-only admin accessing write endpoint → 403."""
        token = create_jwt_token("viewer@example.com", "read-only")
        client.cookies.set(_COOKIE_NAME, token)
        response = client.get("/admin/test-write")
        assert response.status_code == 403

    def test_require_admin_write_with_admin_role_returns_200(self, client):
        """Admin role can access write endpoint."""
        token = create_jwt_token("admin@example.com", "admin")
        client.cookies.set(_COOKIE_NAME, token)
        response = client.get("/admin/test-write")
        assert response.status_code == 200
        assert response.json()["email"] == "admin@example.com"


class TestAuditLog:
    """Test audit log creation."""

    async def test_create_audit_log_records_correct_fields(self):
        """Audit log entry contains all required fields."""
        mock_db = MagicMock()
        mock_db.collection.return_value.add = AsyncMock()

        await create_audit_log(
            db=mock_db,
            admin_email="admin@example.com",
            action="PATCH /admin/api/users/123/subscription",
            target="/admin/api/users/123/subscription",
            ip="1.2.3.4",
            user_agent="Mozilla/5.0",
        )

        mock_db.collection.assert_called_with("admin_audit_log")
        call_args = mock_db.collection.return_value.add.call_args[0][0]
        assert call_args["admin_email"] == "admin@example.com"
        assert call_args["action"] == "PATCH /admin/api/users/123/subscription"
        assert call_args["ip"] == "1.2.3.4"
        assert "timestamp" in call_args

    async def test_audit_log_post_request_creates_entry(self):
        """POST to /admin/* creates audit log entry."""
        app = FastAPI()
        app.add_middleware(AdminAuditMiddleware)

        @app.post("/admin/api/test")
        async def test_post():
            return {"ok": True}

        mock_db = MagicMock()
        mock_db.collection.return_value.add = AsyncMock()
        admin_token = create_jwt_token("admin@example.com", "admin")

        with patch("bot.admin.middleware.get_firestore_client", return_value=mock_db):
            client = TestClient(app)
            client.cookies.set(_COOKIE_NAME, admin_token)
            response = client.post("/admin/api/test")

        assert response.status_code == 200
        mock_db.collection.assert_called_with("admin_audit_log")
