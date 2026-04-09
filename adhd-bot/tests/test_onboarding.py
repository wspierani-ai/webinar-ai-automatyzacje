"""Tests for Onboarding Flow — Unit 6."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.command_handlers import (
    _validate_morning_time,
    _validate_timezone,
    handle_morning,
    handle_start,
    handle_timezone,
)
from bot.models.user import User


def _make_message(text: str, user_id: int = 12345) -> dict:
    return {
        "message_id": 1,
        "from": {"id": user_id, "first_name": "Test", "username": "testuser"},
        "chat": {"id": user_id},
        "text": text,
        "date": 1700000000,
    }


def _make_new_user_db(telegram_user_id: int = 12345):
    """Mock db that simulates a NEW user (not yet in Firestore)."""
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


def _make_existing_user_db(user: User):
    """Mock db that simulates an EXISTING user."""
    db = MagicMock()

    doc_mock = MagicMock()
    doc_mock.exists = True
    doc_mock.to_dict.return_value = user.to_firestore_dict()

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc_mock)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref

    db.collection.return_value = collection_mock
    return db, doc_ref


class TestStartCommand:
    """Test /start command behavior."""

    @pytest.mark.asyncio
    async def test_new_user_created_with_trial_status(self):
        db, doc_ref = _make_new_user_db()

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock):
            await handle_start(_make_message("/start"), db)

        doc_ref.set.assert_called_once()
        saved_data = doc_ref.set.call_args[0][0]
        assert saved_data["subscription_status"] == "trial"

    @pytest.mark.asyncio
    async def test_new_user_has_trial_ends_at_7_days(self):
        db, doc_ref = _make_new_user_db()

        before = datetime.now(tz=timezone.utc)
        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock):
            await handle_start(_make_message("/start"), db)
        after = datetime.now(tz=timezone.utc)

        saved_data = doc_ref.set.call_args[0][0]
        trial_ends = saved_data["trial_ends_at"]
        assert trial_ends is not None
        expected_min = before + timedelta(days=7)
        expected_max = after + timedelta(days=7)
        assert expected_min <= trial_ends <= expected_max

    @pytest.mark.asyncio
    async def test_existing_active_user_not_reset(self):
        existing_user = User(
            telegram_user_id=12345,
            subscription_status="active",
            stripe_subscription_id="sub_abc123",
        )
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock):
            await handle_start(_make_message("/start"), db)

        # Should NOT overwrite existing user
        doc_ref.set.assert_not_called()


class TestTimezoneCommand:
    """Test /timezone command behavior."""

    @pytest.mark.asyncio
    async def test_valid_timezone_updates_user(self):
        existing_user = User(telegram_user_id=12345, timezone="UTC")
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_timezone(_make_message("/timezone Europe/Warsaw"), db)

        doc_ref.set.assert_called()
        saved_data = doc_ref.set.call_args[0][0]
        assert saved_data["timezone"] == "Europe/Warsaw"

    @pytest.mark.asyncio
    async def test_invalid_timezone_sends_error_no_save(self):
        existing_user = User(telegram_user_id=12345, timezone="UTC")
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_timezone(_make_message("/timezone Invalid/Zone"), db)

        doc_ref.set.assert_not_called()
        assert mock_send.called
        msg = mock_send.call_args[0][1]
        assert "Nieprawidłowa" in msg or "❌" in msg


class TestMorningCommand:
    """Test /morning command behavior."""

    @pytest.mark.asyncio
    async def test_valid_time_updates_morning_time(self):
        existing_user = User(telegram_user_id=12345)
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock):
            await handle_morning(_make_message("/morning 08:30"), db)

        doc_ref.set.assert_called()
        saved_data = doc_ref.set.call_args[0][0]
        assert saved_data["morning_time"] == "08:30"

    @pytest.mark.asyncio
    async def test_invalid_time_25_00_sends_error_no_save(self):
        existing_user = User(telegram_user_id=12345)
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_morning(_make_message("/morning 25:00"), db)

        doc_ref.set.assert_not_called()
        assert mock_send.called

    @pytest.mark.asyncio
    async def test_invalid_time_wrong_format_sends_error(self):
        existing_user = User(telegram_user_id=12345)
        db, doc_ref = _make_existing_user_db(existing_user)

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_morning(_make_message("/morning 8:3"), db)

        doc_ref.set.assert_not_called()


class TestValidators:
    """Unit tests for validation helpers."""

    def test_validate_timezone_valid(self):
        assert _validate_timezone("Europe/Warsaw") is True
        assert _validate_timezone("America/New_York") is True
        assert _validate_timezone("UTC") is True

    def test_validate_timezone_invalid(self):
        assert _validate_timezone("Invalid/Zone") is False
        assert _validate_timezone("not-a-tz") is False
        assert _validate_timezone("") is False

    def test_validate_morning_time_valid(self):
        assert _validate_morning_time("08:00") is True
        assert _validate_morning_time("00:00") is True
        assert _validate_morning_time("23:59") is True
        assert _validate_morning_time("07:30") is True

    def test_validate_morning_time_invalid_hour(self):
        assert _validate_morning_time("25:00") is False
        assert _validate_morning_time("24:00") is False

    def test_validate_morning_time_invalid_minute(self):
        assert _validate_morning_time("08:60") is False
        assert _validate_morning_time("08:99") is False

    def test_validate_morning_time_wrong_format(self):
        assert _validate_morning_time("8:00") is False
        assert _validate_morning_time("08:0") is False
        assert _validate_morning_time("abc") is False
