"""Tests for Task Capture Flow — Unit 7."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models.task import TaskState
from bot.models.user import User
from bot.services.ai_parser import ParsedTask


def _make_db_active_user(user: User):
    """Create mock db with an active user."""
    db = MagicMock()

    user_doc = MagicMock()
    user_doc.exists = True
    user_doc.to_dict.return_value = user.to_firestore_dict()

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=user_doc)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref

    db.collection.return_value = collection_mock
    return db, doc_ref


def _make_db_new_user():
    """Create mock db for a new user (first interaction)."""
    db = MagicMock()

    doc_mock = MagicMock()
    doc_mock.exists = False

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc_mock)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref

    db.collection.return_value = collection_mock
    return db, doc_ref


def _make_message(text: str, user_id: int = 12345) -> dict:
    return {
        "message_id": 1,
        "from": {"id": user_id, "first_name": "Test"},
        "chat": {"id": user_id},
        "text": text,
        "date": int(datetime.now(tz=timezone.utc).timestamp()),
    }


def _make_voice_message(file_id: str = "file_abc123", user_id: int = 12345) -> dict:
    return {
        "message_id": 2,
        "from": {"id": user_id, "first_name": "Test"},
        "chat": {"id": user_id},
        "voice": {"file_id": file_id, "duration": 5},
        "date": int(datetime.now(tz=timezone.utc).timestamp()),
    }


class TestTextMessageWithTime:
    """Text message with parseable time creates PENDING_CONFIRMATION task."""

    @pytest.mark.asyncio
    async def test_message_with_time_creates_pending_task(self):
        user = User(
            telegram_user_id=12345,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) + timedelta(days=5),
            timezone="Europe/Warsaw",
        )
        db, doc_ref = _make_db_active_user(user)

        future_time = datetime.now(tz=timezone.utc) + timedelta(hours=24)
        parsed = ParsedTask(
            content="Kupić mleko",
            scheduled_time=future_time,
            confidence=0.95,
            is_morning_snooze=False,
        )

        with patch("bot.handlers.message_handlers.parse_message", new_callable=AsyncMock, return_value=parsed), \
             patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock):
            from bot.handlers.message_handlers import handle_text_message
            await handle_text_message(_make_message("Kupić mleko jutro o 17"), db)

        doc_ref.set.assert_called()
        # Find the task save call (not user save)
        all_calls = doc_ref.set.call_args_list
        task_saves = [c for c in all_calls if "state" in (c[0][0] if c[0] else {})]
        assert len(task_saves) > 0
        saved = task_saves[0][0][0]
        assert saved["state"] == TaskState.PENDING_CONFIRMATION.value
        assert saved["content"] == "Kupić mleko"


class TestTextMessageWithoutTime:
    """Text message without time creates PENDING_CONFIRMATION with heuristic time."""

    @pytest.mark.asyncio
    async def test_message_without_time_creates_pending_task_with_heuristic(self):
        user = User(
            telegram_user_id=12345,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) + timedelta(days=5),
            timezone="Europe/Warsaw",
        )
        db, doc_ref = _make_db_active_user(user)

        parsed = ParsedTask(
            content="Kupić mleko",
            scheduled_time=None,
            confidence=0.1,
            is_morning_snooze=False,
        )

        with patch("bot.handlers.message_handlers.parse_message", new_callable=AsyncMock, return_value=parsed), \
             patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock) as mock_send:
            from bot.handlers.message_handlers import handle_text_message
            await handle_text_message(_make_message("Kupić mleko"), db)

        # Task should be created and confirmation message sent
        assert mock_send.called


class TestBlockedUser:
    """Blocked user gets blocked message, no task created."""

    @pytest.mark.asyncio
    async def test_blocked_user_gets_blocked_message(self):
        user = User(
            telegram_user_id=12345,
            subscription_status="blocked",
        )
        db, doc_ref = _make_db_active_user(user)

        with patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock) as mock_send, \
             patch("bot.handlers.message_handlers.parse_message", new_callable=AsyncMock):
            from bot.handlers.message_handlers import handle_text_message
            await handle_text_message(_make_message("Kupić mleko"), db)

        # No task creation
        task_saves = [
            c for c in doc_ref.set.call_args_list
            if c[0] and "state" in c[0][0]
        ]
        assert len(task_saves) == 0
        # Blocked message sent
        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "wygasł" in sent_text or "subscribe" in sent_text.lower() or "🔒" in sent_text


class TestVoiceMessage:
    """Voice message handling."""

    @pytest.mark.asyncio
    async def test_voice_message_with_successful_parse_creates_task(self):
        user = User(
            telegram_user_id=12345,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) + timedelta(days=5),
            timezone="Europe/Warsaw",
        )
        db, doc_ref = _make_db_active_user(user)

        future_time = datetime.now(tz=timezone.utc) + timedelta(hours=2)
        parsed = ParsedTask(
            content="Zadzwonić do mamy",
            scheduled_time=future_time,
            confidence=0.9,
            is_morning_snooze=False,
        )

        with patch("bot.handlers.message_handlers._download_voice", new_callable=AsyncMock, return_value=b"fake_audio"), \
             patch("bot.handlers.message_handlers.parse_voice_message", new_callable=AsyncMock, return_value=parsed), \
             patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock):
            from bot.handlers.message_handlers import handle_voice_message
            await handle_voice_message(_make_voice_message(), db)

        task_saves = [
            c for c in doc_ref.set.call_args_list
            if c[0] and "state" in c[0][0]
        ]
        assert len(task_saves) > 0
        assert task_saves[0][0][0]["state"] == TaskState.PENDING_CONFIRMATION.value

    @pytest.mark.asyncio
    async def test_voice_parse_fail_sends_error_message(self):
        user = User(
            telegram_user_id=12345,
            subscription_status="trial",
            trial_ends_at=datetime.now(tz=timezone.utc) + timedelta(days=5),
            timezone="Europe/Warsaw",
        )
        db, doc_ref = _make_db_active_user(user)

        failed_parse = ParsedTask(
            content=None,
            scheduled_time=None,
            confidence=0.0,
            is_morning_snooze=False,
        )

        with patch("bot.handlers.message_handlers._download_voice", new_callable=AsyncMock, return_value=b"fake_audio"), \
             patch("bot.handlers.message_handlers.parse_voice_message", new_callable=AsyncMock, return_value=failed_parse), \
             patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock) as mock_send:
            from bot.handlers.message_handlers import handle_voice_message
            await handle_voice_message(_make_voice_message(), db)

        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "tekst" in sent_text.lower() or "przetworzyć" in sent_text.lower()
