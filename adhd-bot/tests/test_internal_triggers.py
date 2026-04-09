"""Tests for internal trigger endpoints — Unit 5."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from bot.models.task import Task, TaskState


def make_app() -> FastAPI:
    from bot.handlers.internal_triggers import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_db_with_task(task: Task, user_data: dict | None = None):
    """Create mock Firestore db with a task document."""
    db = MagicMock()

    # Task doc
    task_doc = MagicMock()
    task_doc.exists = True
    task_doc.to_dict.return_value = task.to_firestore_dict()

    # User doc
    user_doc = MagicMock()
    if user_data:
        user_doc.exists = True
        user_doc.to_dict.return_value = user_data
    else:
        user_doc.exists = False

    task_doc_ref = AsyncMock()
    task_doc_ref.get = AsyncMock(return_value=task_doc)
    task_doc_ref.set = AsyncMock()
    task_doc_ref.update = AsyncMock()

    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)
    user_doc_ref.set = AsyncMock()
    user_doc_ref.update = AsyncMock()

    def _document(doc_id):
        # Return appropriate doc ref based on collection being queried
        return task_doc_ref if "task" in str(doc_id).lower() else user_doc_ref

    collection_mock = MagicMock()
    collection_mock.document.side_effect = _document

    db.collection.return_value = collection_mock
    return db, task_doc_ref


class TestTriggerReminderIdempotency:
    """Test idempotency guard in trigger-reminder."""

    @pytest.mark.asyncio
    async def test_task_already_reminded_returns_200_no_send(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="task-001",
            telegram_user_id=12345,
            content="Test task",
            state=TaskState.REMINDED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-reminder",
                    json={"task_id": "task-001"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data.get("skipped") == "already reminded"
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_task_completed_returns_200_no_send(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="task-002",
            telegram_user_id=12345,
            content="Test task",
            state=TaskState.COMPLETED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-reminder",
                    json={"task_id": "task-002"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()


class TestTriggerNudgeStateGuard:
    """Test state guard in trigger-nudge."""

    @pytest.mark.asyncio
    async def test_nudge_with_completed_task_returns_200_no_nudge(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="task-003",
            telegram_user_id=12345,
            content="Test task",
            state=TaskState.COMPLETED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "task-003"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_with_snoozed_task_returns_200_no_nudge(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="task-004",
            telegram_user_id=12345,
            content="Test task",
            state=TaskState.SNOOZED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "task-004"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_with_nudged_task_returns_200_no_second_nudge(self, monkeypatch):
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="task-005",
            telegram_user_id=12345,
            content="Test task",
            state=TaskState.NUDGED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "task-005"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()
