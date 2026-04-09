"""Tests for Auto-Archival + Orphan Cloud Task Cleanup — Unit 10.

Verifies the /internal/cleanup endpoint behavior:
- Blocks expired trial users
- Blocks expired grace_period users
- Cleans orphaned Cloud Tasks for COMPLETED/REJECTED tasks
- Requires OIDC auth (401 without token)
- Handles empty data gracefully (200, no errors)
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport


def make_app() -> FastAPI:
    from bot.handlers.cleanup_handler import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_user_doc(telegram_user_id: int, subscription_status: str, **kwargs) -> MagicMock:
    """Create a mock Firestore user document."""
    now = datetime.now(tz=timezone.utc)
    data = {
        "telegram_user_id": telegram_user_id,
        "subscription_status": subscription_status,
        "trial_ends_at": kwargs.get("trial_ends_at"),
        "grace_period_until": kwargs.get("grace_period_until"),
        "created_at": now,
        "updated_at": now,
    }
    doc = MagicMock()
    doc.to_dict.return_value = data
    doc.reference = AsyncMock()
    doc.reference.update = AsyncMock()
    return doc


def _make_task_doc(task_id: str, state: str, cloud_task_name: str | None = None, nudge_task_name: str | None = None) -> MagicMock:
    """Create a mock Firestore task document."""
    now = datetime.now(tz=timezone.utc)
    data = {
        "task_id": task_id,
        "state": state,
        "cloud_task_name": cloud_task_name,
        "nudge_task_name": nudge_task_name,
        "telegram_user_id": 12345,
        "content": "Test task",
        "created_at": now,
        "updated_at": now,
    }
    doc = MagicMock()
    doc.to_dict.return_value = data
    doc.reference = AsyncMock()
    doc.reference.update = AsyncMock()
    return doc


def _make_db_with_users_and_tasks(user_docs: list, task_docs: list) -> MagicMock:
    """Build a mock Firestore db with configurable user and task collections."""
    db = MagicMock()

    # Build query mock that returns appropriate docs based on collection
    def _make_collection_mock(docs_for_state: dict[str, list]):
        """Returns a collection mock where .where(...).get() yields matching docs."""
        collection = MagicMock()

        def _where(field, op, value):
            query = MagicMock()
            matching = docs_for_state.get(value, [])
            query.get = AsyncMock(return_value=matching)
            return query

        collection.where.side_effect = _where
        return collection

    user_by_status: dict[str, list] = {}
    for doc in user_docs:
        status = doc.to_dict()["subscription_status"]
        user_by_status.setdefault(status, []).append(doc)

    task_by_state: dict[str, list] = {}
    for doc in task_docs:
        state = doc.to_dict()["state"]
        task_by_state.setdefault(state, []).append(doc)

    users_collection = _make_collection_mock(user_by_status)
    tasks_collection = _make_collection_mock(task_by_state)

    def _collection(name: str):
        if name == "users":
            return users_collection
        return tasks_collection

    db.collection.side_effect = _collection
    return db


class TestCleanupBlocksExpiredTrialUsers:
    """Test that cleanup blocks users with expired trials."""

    @pytest.mark.asyncio
    async def test_blocks_expired_trial_user(self, monkeypatch):
        """Cleanup sets subscription_status=blocked for expired trial users."""
        monkeypatch.setenv("TESTING", "1")

        expired_user = _make_user_doc(
            telegram_user_id=111,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) - timedelta(days=1),
        )
        db = _make_db_with_users_and_tasks([expired_user], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["results"]["trial_blocked"] == 1
        expired_user.reference.update.assert_called_once()
        update_call = expired_user.reference.update.call_args[0][0]
        assert update_call["subscription_status"] == "blocked"

    @pytest.mark.asyncio
    async def test_does_not_block_active_trial_user(self, monkeypatch):
        """Cleanup does NOT block users whose trial has not yet expired."""
        monkeypatch.setenv("TESTING", "1")

        active_user = _make_user_doc(
            telegram_user_id=222,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) + timedelta(days=3),
        )
        db = _make_db_with_users_and_tasks([active_user], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["results"]["trial_blocked"] == 0
        active_user.reference.update.assert_not_called()


class TestCleanupBlocksExpiredGracePeriodUsers:
    """Test that cleanup blocks users with expired grace periods."""

    @pytest.mark.asyncio
    async def test_blocks_expired_grace_period_user(self, monkeypatch):
        """Cleanup sets subscription_status=blocked for expired grace_period users."""
        monkeypatch.setenv("TESTING", "1")

        expired_grace = _make_user_doc(
            telegram_user_id=333,
            subscription_status="grace_period",
            grace_period_until=datetime.now(tz=timezone.utc) - timedelta(hours=1),
        )
        db = _make_db_with_users_and_tasks([expired_grace], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["results"]["grace_period_blocked"] == 1
        expired_grace.reference.update.assert_called_once()
        update_call = expired_grace.reference.update.call_args[0][0]
        assert update_call["subscription_status"] == "blocked"

    @pytest.mark.asyncio
    async def test_does_not_block_active_grace_period_user(self, monkeypatch):
        """Cleanup does NOT block users still within grace period."""
        monkeypatch.setenv("TESTING", "1")

        active_grace = _make_user_doc(
            telegram_user_id=444,
            subscription_status="grace_period",
            grace_period_until=datetime.now(tz=timezone.utc) + timedelta(days=2),
        )
        db = _make_db_with_users_and_tasks([active_grace], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["results"]["grace_period_blocked"] == 0
        active_grace.reference.update.assert_not_called()


class TestCleanupOrphanedCloudTasks:
    """Test cleanup of orphaned Cloud Tasks for archived tasks."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_orphaned_cloud_task_for_completed(self, monkeypatch):
        """Cleanup cancels Cloud Task and clears cloud_task_name for COMPLETED task."""
        monkeypatch.setenv("TESTING", "1")

        completed_task = _make_task_doc(
            task_id="task-completed-001",
            state="COMPLETED",
            cloud_task_name="reminder-task-completed-001-1234567890",
        )
        db = _make_db_with_users_and_tasks([], [completed_task])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.cleanup_handler.cancel_reminder", new_callable=AsyncMock) as mock_cancel:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["results"]["orphaned_tasks_cleaned"] == 1
        mock_cancel.assert_called_once_with("reminder-task-completed-001-1234567890")

    @pytest.mark.asyncio
    async def test_cleanup_removes_orphaned_nudge_task(self, monkeypatch):
        """Cleanup cancels nudge Cloud Task for REJECTED task."""
        monkeypatch.setenv("TESTING", "1")

        rejected_task = _make_task_doc(
            task_id="task-rejected-001",
            state="REJECTED",
            nudge_task_name="nudge-task-rejected-001-9876543210",
        )
        db = _make_db_with_users_and_tasks([], [rejected_task])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.cleanup_handler.cancel_reminder", new_callable=AsyncMock) as mock_cancel:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["results"]["orphaned_tasks_cleaned"] == 1
        mock_cancel.assert_called_once_with("nudge-task-rejected-001-9876543210")


class TestCleanupEmptyData:
    """Test cleanup handles empty collections gracefully."""

    @pytest.mark.asyncio
    async def test_cleanup_with_no_users_returns_200(self, monkeypatch):
        """Cleanup with empty collections → 200, no errors, counts are 0."""
        monkeypatch.setenv("TESTING", "1")

        db = _make_db_with_users_and_tasks([], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["results"]["trial_blocked"] == 0
        assert data["results"]["grace_period_blocked"] == 0
        assert data["results"]["orphaned_tasks_cleaned"] == 0


class TestCleanupAuth:
    """Test OIDC auth requirement for cleanup endpoint."""

    @pytest.mark.asyncio
    async def test_cleanup_without_auth_returns_401(self, monkeypatch):
        """/internal/cleanup without OIDC auth → 401."""
        # Ensure TESTING env var is NOT set so auth is enforced
        monkeypatch.delenv("TESTING", raising=False)

        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/internal/cleanup")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_cleanup_with_testing_flag_skips_auth(self, monkeypatch):
        """/internal/cleanup with TESTING=1 skips OIDC verification."""
        monkeypatch.setenv("TESTING", "1")

        db = _make_db_with_users_and_tasks([], [])

        with patch("bot.handlers.cleanup_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/internal/cleanup")

        assert response.status_code == 200
