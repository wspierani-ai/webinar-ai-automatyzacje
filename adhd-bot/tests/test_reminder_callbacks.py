"""Tests for reminder delivery + inline button callbacks — Unit 8."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models.task import Task, TaskState
from bot.models.user import User
from bot.handlers.callback_handlers import (
    handle_done_callback,
    handle_reject_callback,
    handle_snooze_callback,
)


def _make_callback_query(data: str, user_id: int = 12345, message_id: int = 100) -> dict:
    return {
        "id": "cq-001",
        "from": {"id": user_id, "first_name": "Test"},
        "message": {
            "message_id": message_id,
            "chat": {"id": user_id},
            "text": "Reminder",
        },
        "data": data,
    }


def _make_reminded_task(task_id: str = "task-001", user_id: int = 12345) -> Task:
    task = Task(
        task_id=task_id,
        telegram_user_id=user_id,
        content="Kupić mleko",
        state=TaskState.REMINDED,
        cloud_task_name=f"reminder-{task_id}-1234567890",
        nudge_task_name=f"nudge-{task_id}-1234567890",
    )
    return task


def _make_completed_task(task_id: str = "task-002") -> Task:
    task = Task(
        task_id=task_id,
        telegram_user_id=12345,
        content="Kupić mleko",
        state=TaskState.COMPLETED,
    )
    return task


def _make_db_with_task_and_user(task: Task, user: User):
    """Create mock db with both task and user."""
    db = MagicMock()

    task_doc = MagicMock()
    task_doc.exists = True
    task_doc.to_dict.return_value = task.to_firestore_dict()

    user_doc = MagicMock()
    user_doc.exists = True
    user_doc.to_dict.return_value = user.to_firestore_dict()

    task_doc_ref = AsyncMock()
    task_doc_ref.get = AsyncMock(return_value=task_doc)
    task_doc_ref.set = AsyncMock()
    task_doc_ref.update = AsyncMock()

    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)
    user_doc_ref.set = AsyncMock()
    user_doc_ref.update = AsyncMock()

    def _document(doc_id):
        # Simple heuristic: numeric IDs → user docs
        try:
            int(doc_id)
            return user_doc_ref
        except (ValueError, TypeError):
            return task_doc_ref

    collection_mock = MagicMock()
    collection_mock.document.side_effect = _document

    db.collection.return_value = collection_mock
    # Store refs for easy access in tests
    db._task_doc_ref = task_doc_ref
    db._user_doc_ref = user_doc_ref
    return db


class TestSnooze30Min:
    """Snooze +30 min."""

    @pytest.mark.asyncio
    async def test_snooze_30m_creates_new_task_with_correct_time(self):
        task = _make_reminded_task()
        user = User(
            telegram_user_id=12345,
            timezone="Europe/Warsaw",
            morning_time="08:00",
        )
        db = _make_db_with_task_and_user(task, user)
        before = datetime.now(tz=timezone.utc)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.snooze_reminder", new_callable=AsyncMock, return_value="new-task-name") as mock_snooze, \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_snooze_callback(
                _make_callback_query("snooze:30m:task-001"), "30m", "task-001", db
            )

        after = datetime.now(tz=timezone.utc)
        # Verify snooze_reminder was called with new_fire_at ≈ now + 30min (±5s tolerance)
        mock_snooze.assert_called_once()
        _task_id_arg, _old_ct_name_arg, new_fire_at, _db_arg = mock_snooze.call_args[0]
        expected_min = before + timedelta(minutes=30)
        expected_max = after + timedelta(minutes=30)
        assert expected_min <= new_fire_at <= expected_max, (
            f"Expected new_fire_at between {expected_min} and {expected_max}, got {new_fire_at}"
        )


class TestSnooze2h:
    """Snooze +2h."""

    @pytest.mark.asyncio
    async def test_snooze_2h_runs_successfully(self):
        task = _make_reminded_task()
        user = User(telegram_user_id=12345, timezone="Europe/Warsaw")
        db = _make_db_with_task_and_user(task, user)
        before = datetime.now(tz=timezone.utc)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.snooze_reminder", new_callable=AsyncMock, return_value="new-name") as mock_snooze, \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_snooze_callback(
                _make_callback_query("snooze:2h:task-001"), "2h", "task-001", db
            )

        after = datetime.now(tz=timezone.utc)
        # Verify snooze_reminder was called with new_fire_at ≈ now + 2h (±5s tolerance)
        mock_snooze.assert_called_once()
        _task_id_arg, _old_ct_name_arg, new_fire_at, _db_arg = mock_snooze.call_args[0]
        expected_min = before + timedelta(hours=2)
        expected_max = after + timedelta(hours=2)
        assert expected_min <= new_fire_at <= expected_max, (
            f"Expected new_fire_at between {expected_min} and {expected_max}, got {new_fire_at}"
        )
        # Verify task transitioned to SNOOZED state
        task_doc_ref = db._task_doc_ref
        task_doc_ref.set.assert_called()
        saved = task_doc_ref.set.call_args[0][0]
        from bot.models.task import TaskState
        assert saved["state"] == TaskState.SNOOZED.value


class TestSnoozeMorningWithMorningTime:
    """Snooze to morning when user has morning_time set."""

    @pytest.mark.asyncio
    async def test_snooze_morning_with_time_set_schedules_for_tomorrow(self):
        task = _make_reminded_task()
        user = User(
            telegram_user_id=12345,
            timezone="Europe/Warsaw",
            morning_time="08:30",
        )
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.snooze_reminder", new_callable=AsyncMock, return_value="new-name") as mock_snooze, \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_snooze_callback(
                _make_callback_query("snooze:morning:task-001"), "morning", "task-001", db
            )

        # Should schedule for tomorrow 08:30
        mock_snooze.assert_called_once()
        _, _, new_fire_at, _ = mock_snooze.call_args[0]
        # Verify time is in the future (tomorrow)
        assert new_fire_at > datetime.now(tz=timezone.utc)


class TestSnoozeMorningWithoutMorningTime:
    """Snooze to morning when user has no morning_time — triggers R9 flow."""

    @pytest.mark.asyncio
    async def test_snooze_morning_without_time_triggers_r9_flow(self):
        task = _make_reminded_task()
        user = User(
            telegram_user_id=12345,
            timezone="Europe/Warsaw",
            morning_time=None,
        )
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.snooze_reminder", new_callable=AsyncMock) as mock_snooze, \
             patch("bot.handlers.callback_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_snooze_callback(
                _make_callback_query("snooze:morning:task-001"), "morning", "task-001", db
            )

        # R9 flow: ask for morning time
        mock_snooze.assert_not_called()
        assert mock_send.called
        sent = mock_send.call_args[0][1]
        assert "poranek" in sent.lower() or "rano" in sent.lower() or "godzin" in sent.lower()


class TestDoneCallback:
    """Done callback tests."""

    @pytest.mark.asyncio
    async def test_done_transitions_task_to_completed(self):
        task = _make_reminded_task("task-done-1")
        user = User(telegram_user_id=12345)
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_done_callback(_make_callback_query("done:task-done-1"), "task-done-1", db)

        # Verify task was saved with COMPLETED state (task_doc_ref is the non-numeric doc ref)
        task_doc_ref = db._task_doc_ref
        task_doc_ref.set.assert_called()
        saved = task_doc_ref.set.call_args[0][0]
        assert saved["state"] == TaskState.COMPLETED.value
        assert saved["expires_at"] is not None

    @pytest.mark.asyncio
    async def test_done_cancels_nudge(self):
        task = _make_reminded_task("task-done-2")
        user = User(telegram_user_id=12345)
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock) as mock_cancel, \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_done_callback(_make_callback_query("done:task-done-2"), "task-done-2", db)

        # nudge should be cancelled
        mock_cancel.assert_called()

    @pytest.mark.asyncio
    async def test_done_on_already_completed_task_is_idempotent(self):
        task = _make_completed_task("task-done-3")
        user = User(telegram_user_id=12345)
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock) as mock_answer, \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock):
            # Should NOT raise
            await handle_done_callback(_make_callback_query("done:task-done-3"), "task-done-3", db)

        # answerCallbackQuery should still be called (acknowledge the tap)
        mock_answer.assert_called()


class TestRejectCallback:
    """Reject callback tests."""

    @pytest.mark.asyncio
    async def test_reject_transitions_task_to_rejected(self):
        task = _make_reminded_task("task-rej-1")
        user = User(telegram_user_id=12345)
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=True):
            await handle_reject_callback(_make_callback_query("reject:task-rej-1"), "task-rej-1", db)

        task_doc_ref = db._task_doc_ref
        task_doc_ref.set.assert_called()
        saved = task_doc_ref.set.call_args[0][0]
        assert saved["state"] == TaskState.REJECTED.value
        assert saved["expires_at"] is not None


class TestEditMessageFallback:
    """When edit_message fails, a new message is sent (degraded mode)."""

    @pytest.mark.asyncio
    async def test_done_fallback_sends_new_message_when_edit_fails(self):
        task = _make_reminded_task("task-fall-1")
        user = User(telegram_user_id=12345)
        db = _make_db_with_task_and_user(task, user)

        with patch("bot.handlers.callback_handlers._answer_callback_query", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers.cancel_reminder", new_callable=AsyncMock), \
             patch("bot.handlers.callback_handlers._edit_message_reply_markup", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.callback_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_done_callback(_make_callback_query("done:task-fall-1"), "task-fall-1", db)

        # Should send a new fallback message
        mock_send.assert_called_once()
