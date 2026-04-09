"""Tests for User model — Unit 3."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from bot.models.user import User


def _make_db(doc_exists: bool, doc_data: dict | None = None):
    """Create a mock Firestore db."""
    db = MagicMock()
    doc_mock = MagicMock()
    doc_mock.exists = doc_exists
    if doc_data:
        doc_mock.to_dict.return_value = doc_data

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc_mock)
    doc_ref.set = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref

    db.collection.return_value = collection_mock
    return db, doc_ref


class TestGetOrCreate:
    """Test User.get_or_create."""

    @pytest.mark.asyncio
    async def test_creates_new_user_with_defaults(self):
        db, doc_ref = _make_db(doc_exists=False)
        user = await User.get_or_create(db, telegram_user_id=12345)

        assert user.telegram_user_id == 12345
        assert user.timezone == "Europe/Warsaw"
        assert user.subscription_status == "trial"
        assert user.trial_ends_at is not None
        doc_ref.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_trial_ends_at_is_7_days_from_now(self):
        db, _ = _make_db(doc_exists=False)
        before = datetime.now(tz=timezone.utc)
        user = await User.get_or_create(db, telegram_user_id=12345)
        after = datetime.now(tz=timezone.utc)

        assert user.trial_ends_at is not None
        expected_min = before + timedelta(days=7)
        expected_max = after + timedelta(days=7)
        assert expected_min <= user.trial_ends_at <= expected_max

    @pytest.mark.asyncio
    async def test_returns_existing_user_without_overwriting(self):
        existing_data = {
            "telegram_user_id": 12345,
            "timezone": "America/New_York",
            "subscription_status": "active",
            "trial_ends_at": None,
            "grace_period_until": None,
            "stripe_customer_id": "cus_abc123",
            "stripe_subscription_id": "sub_abc123",
            "morning_time": "08:00",
            "conversation_state": None,
            "conversation_state_expires_at": None,
            "google_connected": True,
            "first_name": "John",
            "username": "john",
            "created_at": datetime.now(tz=timezone.utc),
            "updated_at": datetime.now(tz=timezone.utc),
        }
        db, doc_ref = _make_db(doc_exists=True, doc_data=existing_data)
        user = await User.get_or_create(db, telegram_user_id=12345)

        # Should return existing user — not overwrite
        assert user.subscription_status == "active"
        assert user.timezone == "America/New_York"
        assert user.stripe_customer_id == "cus_abc123"
        doc_ref.set.assert_not_called()


class TestIsSubscriptionActive:
    """Test User.is_subscription_active."""

    def test_active_subscription_returns_true(self):
        user = User(telegram_user_id=1, subscription_status="active")
        assert user.is_subscription_active() is True

    def test_blocked_returns_false(self):
        user = User(telegram_user_id=1, subscription_status="blocked")
        assert user.is_subscription_active() is False

    def test_trial_not_expired_returns_true(self):
        future = datetime.now(tz=timezone.utc) + timedelta(days=3)
        user = User(
            telegram_user_id=1,
            subscription_status="trial",
            trial_ends_at=future,
        )
        assert user.is_subscription_active() is True

    def test_trial_expired_returns_false(self):
        past = datetime.now(tz=timezone.utc) - timedelta(days=1)
        user = User(
            telegram_user_id=1,
            subscription_status="trial",
            trial_ends_at=past,
        )
        assert user.is_subscription_active() is False

    def test_grace_period_not_expired_returns_true(self):
        future = datetime.now(tz=timezone.utc) + timedelta(hours=12)
        user = User(
            telegram_user_id=1,
            subscription_status="grace_period",
            grace_period_until=future,
        )
        assert user.is_subscription_active() is True

    def test_grace_period_expired_returns_false(self):
        past = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        user = User(
            telegram_user_id=1,
            subscription_status="grace_period",
            grace_period_until=past,
        )
        assert user.is_subscription_active() is False
