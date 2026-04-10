"""Tests for bot.admin.queries and bot.admin.router — Admin Dashboard API."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_SECRET_TOKEN", "test-secret")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.run.app")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-jwt-secret-for-dev")

from bot.admin.auth import _COOKIE_NAME, create_jwt_token
from bot.admin.middleware import AdminSession
from bot.admin.queries import get_overview_stats, get_users_list
from bot.admin.router import router as admin_router


def _make_user_doc(doc_id: str, status: str = "active", **kwargs) -> MagicMock:
    """Create a mock Firestore document for a user."""
    doc = MagicMock()
    doc.id = doc_id
    data = {"subscription_status": status, **kwargs}
    doc.to_dict.return_value = data
    return doc


def _make_chainable_query_mock(docs: list) -> MagicMock:
    """Create a mock that supports chained Firestore query methods.

    Supports patterns like: collection().order_by().limit().get(),
    collection().where().order_by().limit().get(), and
    collection().order_by().start_after().limit().get().
    """
    mock = MagicMock()

    # Make all chaining methods return the same mock
    mock.order_by.return_value = mock
    mock.limit.return_value = mock
    mock.start_after.return_value = mock
    mock.where.return_value = mock
    mock.get = AsyncMock(return_value=docs)

    return mock


class TestGetOverviewStats:
    """Test overview stats aggregation."""

    async def test_returns_correct_counts(self):
        """Overview stats correctly count active/trial/blocked users."""
        mock_users = [
            _make_user_doc("1", "active"),
            _make_user_doc("2", "active"),
            _make_user_doc("3", "trial"),
            _make_user_doc("4", "blocked"),
        ]

        mock_db = MagicMock()
        users_query = _make_chainable_query_mock(mock_users)
        # First call returns users, second call (for next batch) returns empty
        users_query.get = AsyncMock(side_effect=[mock_users, []])

        # Token usage subcollection
        token_query = _make_chainable_query_mock([])

        def collection_router(name: str):
            if name == "users":
                return users_query
            if name == "token_usage":
                result = MagicMock()
                result.document.return_value.collection.return_value = token_query
                return result
            return MagicMock()

        mock_db.collection.side_effect = collection_router

        stats = await get_overview_stats(mock_db)

        assert stats["total_users"] == 4
        assert stats["active_subscriptions"] == 2
        assert stats["trial_users"] == 1
        assert stats["blocked_users"] == 1
        assert stats["mrr_pln"] == round(2 * 29.99, 2)
        assert stats["arr_pln"] == round(2 * 29.99 * 12, 2)


class TestGetUsersList:
    """Test user listing with filters."""

    async def test_returns_all_users(self):
        """No filter returns all users."""
        mock_users = [
            _make_user_doc("100", "active"),
            _make_user_doc("200", "blocked"),
            _make_user_doc("300", "trial"),
        ]

        mock_db = MagicMock()
        query_mock = _make_chainable_query_mock(mock_users)
        mock_db.collection.return_value = query_mock

        result = await get_users_list(mock_db)

        assert result["total"] == 3
        assert len(result["users"]) == 3

    async def test_filter_by_status_blocked(self):
        """Filter by status=blocked returns only blocked users."""
        mock_blocked = [_make_user_doc("200", "blocked")]

        mock_db = MagicMock()
        query_mock = _make_chainable_query_mock(mock_blocked)
        mock_db.collection.return_value = query_mock

        result = await get_users_list(mock_db, status_filter="blocked")

        assert result["total"] == 1
        assert result["users"][0]["user_id"] == "200"
        assert result["users"][0]["subscription_status"] == "blocked"


class TestAdminApiEndpoints:
    """Test admin API endpoints with auth."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        app.include_router(admin_router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app, raise_server_exceptions=False)

    def test_overview_without_auth_redirects(self, client):
        """GET /admin/api/overview without cookie → redirect to login."""
        response = client.get("/admin/api/overview", follow_redirects=False)
        assert response.status_code == 302

    def test_overview_with_read_only_auth_returns_200(self, client):
        """GET /admin/api/overview with read-only admin → 200 with data."""
        mock_users = [_make_user_doc("1", "active")]

        mock_db = MagicMock()
        users_query = _make_chainable_query_mock(mock_users)
        users_query.get = AsyncMock(side_effect=[mock_users, []])
        token_query = _make_chainable_query_mock([])

        def collection_router(name: str):
            if name == "users":
                return users_query
            if name == "token_usage":
                result = MagicMock()
                result.document.return_value.collection.return_value = token_query
                return result
            return MagicMock()

        mock_db.collection.side_effect = collection_router

        token = create_jwt_token("viewer@example.com", "read-only")
        client.cookies.set(_COOKIE_NAME, token)

        with patch("bot.admin.router.get_firestore_client", return_value=mock_db):
            response = client.get("/admin/api/overview")

        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "mrr_pln" in data
        assert "active_subscriptions" in data

    def test_patch_subscription_with_read_only_returns_403(self, client):
        """PATCH subscription with read-only role → 403."""
        token = create_jwt_token("viewer@example.com", "read-only")
        client.cookies.set(_COOKIE_NAME, token)

        response = client.patch(
            "/admin/api/users/123/subscription",
            json={"action": "unblock"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert response.status_code == 403

    def test_patch_subscription_without_csrf_header_returns_403(self, client):
        """PATCH subscription without X-Requested-With header → 403."""
        token = create_jwt_token("admin@example.com", "admin")
        client.cookies.set(_COOKIE_NAME, token)

        response = client.patch(
            "/admin/api/users/123/subscription",
            json={"action": "unblock"},
        )
        assert response.status_code == 403

    def test_patch_subscription_with_admin_returns_200(self, client):
        """PATCH subscription with admin role + CSRF header → 200, audit log created."""
        mock_db = MagicMock()
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_db.collection.return_value.document.return_value.get = AsyncMock(
            return_value=mock_doc
        )
        mock_db.collection.return_value.document.return_value.update = AsyncMock()
        mock_db.collection.return_value.add = AsyncMock()

        token = create_jwt_token("admin@example.com", "admin")
        client.cookies.set(_COOKIE_NAME, token)

        with patch("bot.admin.router.get_firestore_client", return_value=mock_db):
            response = client.patch(
                "/admin/api/users/123/subscription",
                json={"action": "unblock"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["action"] == "unblock"
        # Verify audit log was created
        mock_db.collection.return_value.add.assert_awaited()

    def test_users_filter_by_status(self, client):
        """GET /admin/api/users?status=blocked returns only blocked users."""
        mock_blocked = [_make_user_doc("200", "blocked")]

        mock_db = MagicMock()
        query_mock = _make_chainable_query_mock(mock_blocked)
        mock_db.collection.return_value = query_mock

        token = create_jwt_token("admin@example.com", "admin")
        client.cookies.set(_COOKIE_NAME, token)

        with patch("bot.admin.router.get_firestore_client", return_value=mock_db):
            response = client.get("/admin/api/users?status=blocked")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["users"][0]["subscription_status"] == "blocked"
