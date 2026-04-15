"""Tests for Nudge System — Unit 9.

Verifies the /internal/trigger-nudge endpoint behavior:
- Sends nudge and transitions to NUDGED when task is in REMINDED state
- Idempotent guards for all other states (COMPLETED, SNOOZED, NUDGED)
- Nudge message contains task content
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from bot.models.task import Task, TaskState


def make_app() -> FastAPI:
    from bot.handlers.internal_triggers import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_db_with_task(task: Task):
    """Create mock Firestore db with a task document."""
    db = MagicMock()

    task_doc = MagicMock()
    task_doc.exists = True
    task_doc.to_dict.return_value = task.to_firestore_dict()

    user_doc = MagicMock()
    user_doc.exists = False

    task_doc_ref = AsyncMock()
    task_doc_ref.get = AsyncMock(return_value=task_doc)
    task_doc_ref.set = AsyncMock()
    task_doc_ref.update = AsyncMock()

    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)

    def _document(doc_id):
        return task_doc_ref if "task" in str(doc_id).lower() else user_doc_ref

    collection_mock = MagicMock()
    collection_mock.document.side_effect = _document

    db.collection.return_value = collection_mock
    return db, task_doc_ref


class TestTriggerNudgeWithRemindedTask:
    """Test nudge sent when task is in REMINDED state."""

    @pytest.mark.asyncio
    async def test_nudge_reminded_task_sends_message(self, monkeypatch):
        """trigger-nudge with task.state=REMINDED → sends nudge message."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-001",
            telegram_user_id=99999,
            content="Zadzwonić do dentysty",
            state=TaskState.REMINDED,
        )
        db, task_doc_ref = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"ok": True, "result": {"message_id": 42}}
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-001"},
                )

        assert response.status_code == 200
        assert response.json().get("ok") is True
        mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_nudge_reminded_task_transitions_to_nudged(self, monkeypatch):
        """trigger-nudge with task.state=REMINDED → task.state transitions to NUDGED."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-002",
            telegram_user_id=99999,
            content="Kupić mleko",
            state=TaskState.REMINDED,
        )
        db, task_doc_ref = _make_db_with_task(task)


        async def capture_save(*args, **kwargs):
            # Capture what was saved
            pass

        task_doc_ref.set.side_effect = capture_save

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"ok": True, "result": {"message_id": 42}}
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-002"},
                )

        assert response.status_code == 200
        # Verify save was called (state persisted)
        task_doc_ref.set.assert_called_once()
        # Verify saved state is NUDGED
        saved_dict = task_doc_ref.set.call_args[0][0]
        assert saved_dict["state"] == TaskState.NUDGED.value

    @pytest.mark.asyncio
    async def test_nudge_message_contains_task_content(self, monkeypatch):
        """Nudge message text contains task.content."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-003",
            telegram_user_id=88888,
            content="Zapłacić rachunki za prąd",
            state=TaskState.REMINDED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"ok": True, "result": {"message_id": 99}}
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-003"},
                )

        assert mock_send.called
        call_kwargs = mock_send.call_args
        text_sent = call_kwargs[1].get("text") or call_kwargs[0][1]
        assert "Zapłacić rachunki za prąd" in text_sent


class TestTriggerNudgeIdempotency:
    """Test idempotency guards — nudge must NOT be sent for non-REMINDED states."""

    @pytest.mark.asyncio
    async def test_nudge_completed_task_returns_200_no_nudge(self, monkeypatch):
        """trigger-nudge with task.state=COMPLETED → 200, brak nudge."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-004",
            telegram_user_id=99999,
            content="Zrobione zadanie",
            state=TaskState.COMPLETED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-004"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_snoozed_task_returns_200_no_nudge(self, monkeypatch):
        """trigger-nudge with task.state=SNOOZED → 200, brak nudge."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-005",
            telegram_user_id=99999,
            content="Odłożone zadanie",
            state=TaskState.SNOOZED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-005"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_already_nudged_task_returns_200_no_second_nudge(self, monkeypatch):
        """trigger-nudge with task.state=NUDGED → 200, brak drugiego nudge (idempotent)."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-006",
            telegram_user_id=99999,
            content="Już nudge'owane zadanie",
            state=TaskState.NUDGED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-006"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_rejected_task_returns_200_no_nudge(self, monkeypatch):
        """trigger-nudge with task.state=REJECTED → 200, brak nudge."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        task = Task(
            task_id="nudge-task-007",
            telegram_user_id=99999,
            content="Odrzucone zadanie",
            state=TaskState.REJECTED,
        )
        db, _ = _make_db_with_task(task)

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "nudge-task-007"},
                )

        assert response.status_code == 200
        mock_send.assert_not_called()


class TestTriggerNudgeMissingTask:
    """Test nudge behavior when task does not exist."""

    @pytest.mark.asyncio
    async def test_nudge_missing_task_returns_200_skipped(self, monkeypatch):
        """trigger-nudge with non-existent task_id → 200, skipped."""
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

        db = MagicMock()
        task_doc = MagicMock()
        task_doc.exists = False

        task_doc_ref = AsyncMock()
        task_doc_ref.get = AsyncMock(return_value=task_doc)

        collection_mock = MagicMock()
        collection_mock.document.return_value = task_doc_ref
        db.collection.return_value = collection_mock

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=db), \
             patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={"task_id": "non-existent-task"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data.get("skipped") == "task not found"
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_missing_task_id_returns_400(self, monkeypatch):
        """trigger-nudge without task_id → 400."""
        monkeypatch.setenv("TESTING", "1")

        with patch("bot.handlers.internal_triggers.get_firestore_client", return_value=MagicMock()):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/internal/trigger-nudge",
                    json={},
                )

        assert response.status_code == 400
