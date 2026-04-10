"""Tests for Google Tasks integration — Unit 14.

Covers:
- create_google_task creates task with correct title and due date
- create_google_task skips gracefully when user has no Google
- complete_google_task calls tasks.patch with status: "completed"
- Polling: completed Google Task → bot task → COMPLETED, Telegram notification
- Polling: unchanged Google Task → no action
- Polling for 0 users with Google → 200, no errors
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.example.com")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_doc(
    telegram_user_id: int = 111,
    google_connected: bool = True,
    tasks_list_id: str = "@default",
    sync_token: str | None = None,
) -> MagicMock:
    doc = AsyncMock()
    doc.exists = True
    doc.to_dict = MagicMock(
        return_value={
            "telegram_user_id": telegram_user_id,
            "google_connected": google_connected,
            "google_tasks_list_id": tasks_list_id,
            "google_tasks_sync_token": sync_token,
        }
    )
    return doc


def _make_task_mock(
    task_id: str = "task-001",
    content: str = "Zadzwonić do mamy",
    scheduled_time: datetime | None = None,
    google_task_id: str | None = None,
    state_value: str = "SCHEDULED",
) -> MagicMock:
    task = MagicMock()
    task.task_id = task_id
    task.content = content
    task.scheduled_time = scheduled_time or datetime.now(tz=timezone.utc) + timedelta(hours=2)
    task.google_task_id = google_task_id
    task.state = MagicMock()
    task.state.value = state_value
    return task


def _make_db_for_tasks(user_data: dict | None = None) -> MagicMock:
    db = MagicMock()

    user_doc = AsyncMock()
    user_doc.exists = bool(user_data)
    user_doc.to_dict = MagicMock(return_value=user_data or {})

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=user_doc)
    doc_ref.update = AsyncMock()
    doc_ref.set = AsyncMock()

    db.collection.return_value.document.return_value = doc_ref
    db.collection.return_value.where.return_value.limit.return_value.get = AsyncMock(return_value=[])
    db.collection.return_value.where.return_value.where.return_value.limit.return_value.get = AsyncMock(return_value=[])
    return db


def _make_tasks_service_mock(task_id: str = "gtask-001") -> MagicMock:
    service = MagicMock()
    service.tasks.return_value.insert.return_value.execute.return_value = {"id": task_id}
    service.tasks.return_value.patch.return_value.execute.return_value = {"id": task_id}
    service.tasks.return_value.delete.return_value.execute.return_value = {}
    service.tasks.return_value.list.return_value.execute.return_value = {
        "items": [],
        "nextSyncToken": "new-sync-token",
    }
    return service


# ---------------------------------------------------------------------------
# Tests: create_google_task
# ---------------------------------------------------------------------------

class TestCreateGoogleTask:
    """Tests for create_google_task."""

    @pytest.mark.asyncio
    async def test_skips_gracefully_when_user_has_no_google(self):
        """create_google_task → None + no error when user not connected."""
        from bot.services.google_tasks import create_google_task

        db = _make_db_for_tasks()
        task = _make_task_mock()

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value=None),
        ):
            result = await create_google_task(db, 123, task)

        assert result is None

    @pytest.mark.asyncio
    async def test_creates_task_with_correct_title_and_due(self):
        """create_google_task creates task with correct title and due date."""
        from bot.services.google_tasks import create_google_task

        scheduled_time = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
        task = _make_task_mock(content="Kupić mleko", scheduled_time=scheduled_time)

        db = MagicMock()

        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(
            return_value={"google_tasks_list_id": "@default"}
        )
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)

        task_doc_ref = AsyncMock()
        task_doc_ref.update = AsyncMock()

        def _doc_selector(doc_id):
            if doc_id == "123":
                return user_doc_ref
            return task_doc_ref

        db.collection.return_value.document.side_effect = _doc_selector

        mock_service = _make_tasks_service_mock("new-gtask-id")

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            return_value=mock_service,
        ):
            result = await create_google_task(db, 123, task)

        assert result == "new-gtask-id"

        mock_service.tasks.return_value.insert.assert_called_once()
        insert_call = mock_service.tasks.return_value.insert.call_args
        assert insert_call[1]["tasklist"] == "@default"
        body = insert_call[1]["body"]
        assert body["title"] == "Kupić mleko"
        assert "2026-05-01T14:00:00+00:00" in body["due"]

    @pytest.mark.asyncio
    async def test_saves_google_task_id_to_firestore(self):
        """create_google_task saves google_task_id to task document in Firestore."""
        from bot.services.google_tasks import create_google_task

        task = _make_task_mock(task_id="task-save-test")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_tasks_list_id": "@default"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)

        task_doc_ref = AsyncMock()
        task_doc_ref.update = AsyncMock()

        def _doc_selector(doc_id):
            if doc_id == "123":
                return user_doc_ref
            return task_doc_ref

        db.collection.return_value.document.side_effect = _doc_selector

        mock_service = _make_tasks_service_mock("saved-gtask-id")

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            return_value=mock_service,
        ):
            result = await create_google_task(db, 123, task)

        assert result == "saved-gtask-id"
        task_doc_ref.update.assert_called_once_with({"google_task_id": "saved-gtask-id"})


# ---------------------------------------------------------------------------
# Tests: complete_google_task
# ---------------------------------------------------------------------------

class TestCompleteGoogleTask:
    """Tests for complete_google_task."""

    @pytest.mark.asyncio
    async def test_calls_tasks_patch_with_completed_status(self):
        """complete_google_task calls tasks().patch with status='completed'."""
        from bot.services.google_tasks import complete_google_task

        task = _make_task_mock(google_task_id="gtask-complete-me")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_tasks_list_id": "@default"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_tasks_service_mock()

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            return_value=mock_service,
        ):
            await complete_google_task(db, 123, task)

        mock_service.tasks.return_value.patch.assert_called_once()
        patch_call = mock_service.tasks.return_value.patch.call_args[1]
        assert patch_call["task"] == "gtask-complete-me"
        assert patch_call["body"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_skips_when_no_google_task_id(self):
        """complete_google_task is no-op when task has no google_task_id."""
        from bot.services.google_tasks import complete_google_task

        task = _make_task_mock(google_task_id=None)
        db = MagicMock()

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ) as mock_token:
            await complete_google_task(db, 123, task)

        mock_token.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: poll_user_tasks
# ---------------------------------------------------------------------------

class TestPollUserTasks:
    """Tests for poll_user_tasks function."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_user_not_connected(self):
        """poll_user_tasks → [] when user has no Google token."""
        from bot.services.google_tasks import poll_user_tasks

        db = _make_db_for_tasks()

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value=None),
        ):
            result = await poll_user_tasks(db, 123)

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_completed_task_ids(self):
        """poll_user_tasks returns IDs of completed Google Tasks."""
        from bot.services.google_tasks import poll_user_tasks

        db = MagicMock()

        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(
            return_value={
                "google_tasks_list_id": "@default",
                "google_tasks_sync_token": None,
            }
        )
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        user_doc_ref.update = AsyncMock()
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_tasks_service_mock()
        mock_service.tasks.return_value.list.return_value.execute.return_value = {
            "items": [
                {"id": "gtask-done-1", "status": "completed", "title": "Zadanie 1"},
                {"id": "gtask-pending-2", "status": "needsAction", "title": "Zadanie 2"},
                {"id": "gtask-done-3", "status": "completed", "title": "Zadanie 3"},
            ],
            "nextSyncToken": "token-abc",
        }

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            return_value=mock_service,
        ):
            result = await poll_user_tasks(db, 123)

        assert "gtask-done-1" in result
        assert "gtask-done-3" in result
        assert "gtask-pending-2" not in result
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_saves_next_sync_token(self):
        """poll_user_tasks saves nextSyncToken to user document."""
        from bot.services.google_tasks import poll_user_tasks

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(
            return_value={
                "google_tasks_list_id": "@default",
                "google_tasks_sync_token": None,
            }
        )
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        user_doc_ref.update = AsyncMock()
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_tasks_service_mock()
        mock_service.tasks.return_value.list.return_value.execute.return_value = {
            "items": [],
            "nextSyncToken": "next-token-xyz",
        }

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            return_value=mock_service,
        ):
            await poll_user_tasks(db, 123)

        user_doc_ref.update.assert_called_once()
        update_data = user_doc_ref.update.call_args[0][0]
        assert update_data["google_tasks_sync_token"] == "next-token-xyz"

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_api_error(self):
        """poll_user_tasks returns [] on API error (graceful fail)."""
        from bot.services.google_tasks import poll_user_tasks

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(
            return_value={
                "google_tasks_list_id": "@default",
                "google_tasks_sync_token": None,
            }
        )
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        with patch(
            "bot.services.google_tasks.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_tasks._build_tasks_service",
            side_effect=Exception("API error"),
        ):
            result = await poll_user_tasks(db, 123)

        assert result == []


# ---------------------------------------------------------------------------
# Tests: /internal/poll-google-tasks endpoint
# ---------------------------------------------------------------------------

class TestPollGoogleTasksEndpoint:
    """Tests for /internal/poll-google-tasks endpoint."""

    @pytest.mark.asyncio
    async def test_returns_200_with_zero_users(self):
        """Polling with 0 Google-connected users → 200, no errors."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.gtasks_polling_handler import router

        app = FastAPI()
        app.include_router(router)

        # Empty user list
        mock_db = MagicMock()
        mock_db.collection.return_value.where.return_value.limit.return_value.get = AsyncMock(return_value=[])

        with patch(
            "bot.handlers.gtasks_polling_handler.get_firestore_client",
            return_value=mock_db,
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/poll-google-tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["processed_users"] == 0
        assert data["completed_tasks"] == 0

    @pytest.mark.asyncio
    async def test_completed_google_task_triggers_bot_completion_and_notification(self):
        """Polling finds completed Google Task → bot task COMPLETED + Telegram sent."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.gtasks_polling_handler import router
        from bot.models.task import Task, TaskState

        app = FastAPI()
        app.include_router(router)

        # Build user doc
        user_doc = MagicMock()
        user_doc.id = "111"
        user_doc.to_dict = MagicMock(
            return_value={
                "telegram_user_id": 111,
                "google_connected": True,
                "google_tasks_list_id": "@default",
            }
        )

        mock_db = MagicMock()
        mock_db.collection.return_value.where.return_value.limit.return_value.get = AsyncMock(
            return_value=[user_doc]
        )

        with patch(
            "bot.handlers.gtasks_polling_handler.get_firestore_client",
            return_value=mock_db,
        ), patch(
            "bot.handlers.gtasks_polling_handler._process_user_polling",
            new=AsyncMock(return_value=1),
        ) as mock_process:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/poll-google-tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_tasks"] == 1
        mock_process.assert_called_once_with(mock_db, 111)

    @pytest.mark.asyncio
    async def test_polling_unchanged_task_produces_no_action(self):
        """Polling when no Google Tasks are completed → no bot completions."""
        from fastapi import FastAPI
        from httpx import AsyncClient, ASGITransport
        from bot.handlers.gtasks_polling_handler import router

        app = FastAPI()
        app.include_router(router)

        user_doc = MagicMock()
        user_doc.id = "222"
        user_doc.to_dict = MagicMock(
            return_value={
                "telegram_user_id": 222,
                "google_connected": True,
            }
        )

        mock_db = MagicMock()
        mock_db.collection.return_value.where.return_value.limit.return_value.get = AsyncMock(
            return_value=[user_doc]
        )

        with patch(
            "bot.handlers.gtasks_polling_handler.get_firestore_client",
            return_value=mock_db,
        ), patch(
            "bot.handlers.gtasks_polling_handler._process_user_polling",
            new=AsyncMock(return_value=0),
        ):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/internal/poll-google-tasks")

        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_tasks"] == 0

    @pytest.mark.asyncio
    async def test_sync_completed_task_sends_telegram_notification(self):
        """_sync_completed_task sends Telegram notification when task completed."""
        from bot.handlers.gtasks_polling_handler import _sync_completed_task
        from bot.models.task import Task, TaskState

        # Create a real Task object in REMINDED state
        task = Task(
            task_id="task-remind-001",
            telegram_user_id=333,
            content="Kupić chleb",
            state=TaskState.REMINDED,
            google_task_id="gtask-001",
        )

        # Mock task doc from Firestore
        task_doc = MagicMock()
        task_doc.to_dict = MagicMock(return_value=task.to_firestore_dict())

        task_doc_ref = AsyncMock()
        task_doc_ref.update = AsyncMock()

        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.limit.return_value.get = AsyncMock(
            return_value=[task_doc]
        )
        db.collection.return_value.document.return_value = task_doc_ref

        with patch(
            "bot.handlers.gtasks_polling_handler._send_telegram_message",
            new=AsyncMock(),
        ) as mock_send, patch(
            "bot.handlers.gtasks_polling_handler.cancel_reminder",
            new=AsyncMock(),
        ):
            result = await _sync_completed_task(db, 333, "gtask-001")

        assert result == 1
        mock_send.assert_called_once()
        call_text = mock_send.call_args[0][1]
        assert "Kupić chleb" in call_text
        assert "ukończone" in call_text.lower() or "completed" in call_text.lower()

    @pytest.mark.asyncio
    async def test_sync_skips_already_completed_task(self):
        """_sync_completed_task skips tasks already in COMPLETED state."""
        from bot.handlers.gtasks_polling_handler import _sync_completed_task
        from bot.models.task import Task, TaskState

        task = Task(
            task_id="task-already-done",
            telegram_user_id=444,
            content="Już zrobione",
            state=TaskState.COMPLETED,
            google_task_id="gtask-done",
        )

        task_doc = MagicMock()
        task_doc.to_dict = MagicMock(return_value=task.to_firestore_dict())

        db = MagicMock()
        db.collection.return_value.where.return_value.where.return_value.limit.return_value.get = AsyncMock(
            return_value=[task_doc]
        )

        with patch(
            "bot.handlers.gtasks_polling_handler._send_telegram_message",
            new=AsyncMock(),
        ) as mock_send:
            result = await _sync_completed_task(db, 444, "gtask-done")

        assert result == 0
        mock_send.assert_not_called()
