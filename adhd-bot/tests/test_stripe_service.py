"""Tests for Stripe service — Unit 11.

Covers:
- create_or_get_stripe_customer (existing and new)
- create_checkout_session (currency=PLN, price_id)
- is_event_duplicate / mark_event_processed (deduplication)
- handle_checkout_session_completed → subscription_status=active
- handle_invoice_payment_failed → grace_period + 3 days
- handle_invoice_payment_succeeded → subscription_status=active, grace cleared
- handle_subscription_deleted → subscription_status=blocked
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(telegram_user_id: int = 12345, **kwargs) -> MagicMock:
    """Return a mock User with sensible defaults."""
    user = MagicMock()
    user.telegram_user_id = telegram_user_id
    user.first_name = kwargs.get("first_name", "Jan")
    user.stripe_customer_id = kwargs.get("stripe_customer_id", None)
    user.subscription_status = kwargs.get("subscription_status", "trial")
    return user


def _make_db() -> MagicMock:
    """Return a mock Firestore db that supports collection/document access."""
    db = MagicMock()
    doc_ref = AsyncMock()
    doc_ref.update = AsyncMock()
    doc_ref.set = AsyncMock()
    doc = AsyncMock()
    doc.exists = False
    doc_ref.get = AsyncMock(return_value=doc)

    db.collection.return_value.document.return_value = doc_ref
    db.collection.return_value.where.return_value.get = AsyncMock(return_value=[])
    return db


def _make_stripe_mock(customer_id: str = "cus_test123", session_url: str = "https://checkout.stripe.com/test") -> MagicMock:
    """Return a mock stripe module."""
    stripe_mock = MagicMock()
    stripe_mock.Customer.create.return_value = {"id": customer_id}
    stripe_mock.checkout.Session.create.return_value = {
        "id": "cs_test123",
        "url": session_url,
    }
    return stripe_mock


# ---------------------------------------------------------------------------
# Tests: create_or_get_stripe_customer
# ---------------------------------------------------------------------------

class TestCreateOrGetStripeCustomer:
    """Tests for create_or_get_stripe_customer."""

    @pytest.mark.asyncio
    async def test_returns_existing_customer_id_without_stripe_call(self):
        """If user already has stripe_customer_id, return it without API call."""
        from bot.services.stripe_service import create_or_get_stripe_customer

        user = _make_user(stripe_customer_id="cus_existing")
        db = _make_db()
        stripe_mock = _make_stripe_mock()

        result = await create_or_get_stripe_customer(db, user, stripe=stripe_mock)

        assert result == "cus_existing"
        stripe_mock.Customer.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_customer_and_persists(self):
        """If user has no stripe_customer_id, create and persist to Firestore."""
        from bot.services.stripe_service import create_or_get_stripe_customer

        user = _make_user(stripe_customer_id=None)
        db = _make_db()
        stripe_mock = _make_stripe_mock(customer_id="cus_new456")

        result = await create_or_get_stripe_customer(db, user, stripe=stripe_mock)

        assert result == "cus_new456"
        stripe_mock.Customer.create.assert_called_once()
        # Firestore update called with new customer_id
        db.collection.return_value.document.return_value.update.assert_called_once()
        update_args = db.collection.return_value.document.return_value.update.call_args[0][0]
        assert update_args["stripe_customer_id"] == "cus_new456"

    @pytest.mark.asyncio
    async def test_sets_customer_id_on_user_object(self):
        """After creation, user.stripe_customer_id is updated in-memory."""
        from bot.services.stripe_service import create_or_get_stripe_customer

        user = _make_user(stripe_customer_id=None)
        db = _make_db()
        stripe_mock = _make_stripe_mock(customer_id="cus_inmem")

        await create_or_get_stripe_customer(db, user, stripe=stripe_mock)

        assert user.stripe_customer_id == "cus_inmem"


# ---------------------------------------------------------------------------
# Tests: create_checkout_session
# ---------------------------------------------------------------------------

class TestCreateCheckoutSession:
    """Tests for create_checkout_session."""

    @pytest.mark.asyncio
    async def test_creates_session_with_pln_currency(self, monkeypatch):
        """Checkout session created with currency='pln'."""
        from bot.services.stripe_service import create_checkout_session

        monkeypatch.setenv("STRIPE_PRICE_ID", "price_test_abc")
        user = _make_user(stripe_customer_id="cus_abc")
        stripe_mock = _make_stripe_mock(session_url="https://checkout.stripe.com/pay/abc")

        result = await create_checkout_session(
            user,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            stripe=stripe_mock,
        )

        assert result == "https://checkout.stripe.com/pay/abc"
        call_kwargs = stripe_mock.checkout.Session.create.call_args[1]
        assert call_kwargs["currency"] == "pln"

    @pytest.mark.asyncio
    async def test_creates_session_with_correct_price_id(self, monkeypatch):
        """Checkout session uses STRIPE_PRICE_ID from environment."""
        from bot.services.stripe_service import create_checkout_session

        monkeypatch.setenv("STRIPE_PRICE_ID", "price_29pln")
        user = _make_user(stripe_customer_id="cus_xyz")
        stripe_mock = _make_stripe_mock()

        await create_checkout_session(
            user,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            stripe=stripe_mock,
        )

        call_kwargs = stripe_mock.checkout.Session.create.call_args[1]
        line_items = call_kwargs["line_items"]
        assert line_items[0]["price"] == "price_29pln"

    @pytest.mark.asyncio
    async def test_attaches_customer_if_present(self, monkeypatch):
        """Checkout session includes customer= when user has stripe_customer_id."""
        from bot.services.stripe_service import create_checkout_session

        monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
        user = _make_user(stripe_customer_id="cus_attached")
        stripe_mock = _make_stripe_mock()

        await create_checkout_session(
            user,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            stripe=stripe_mock,
        )

        call_kwargs = stripe_mock.checkout.Session.create.call_args[1]
        assert call_kwargs["customer"] == "cus_attached"

    @pytest.mark.asyncio
    async def test_no_customer_param_when_none(self, monkeypatch):
        """Checkout session excludes customer= when user.stripe_customer_id is None."""
        from bot.services.stripe_service import create_checkout_session

        monkeypatch.setenv("STRIPE_PRICE_ID", "price_test")
        user = _make_user(stripe_customer_id=None)
        stripe_mock = _make_stripe_mock()

        await create_checkout_session(
            user,
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
            stripe=stripe_mock,
        )

        call_kwargs = stripe_mock.checkout.Session.create.call_args[1]
        assert "customer" not in call_kwargs


# ---------------------------------------------------------------------------
# Tests: event deduplication
# ---------------------------------------------------------------------------

class TestEventDeduplication:
    """Tests for is_event_duplicate and mark_event_processed."""

    @pytest.mark.asyncio
    async def test_new_event_is_not_duplicate(self):
        """is_event_duplicate returns False for new event_id."""
        from bot.services.stripe_service import is_event_duplicate

        doc = AsyncMock()
        doc.exists = False

        db = MagicMock()
        db.collection.return_value.document.return_value.get = AsyncMock(return_value=doc)

        result = await is_event_duplicate(db, "evt_new123")
        assert result is False

    @pytest.mark.asyncio
    async def test_existing_event_is_duplicate(self):
        """is_event_duplicate returns True for already-processed event_id."""
        from bot.services.stripe_service import is_event_duplicate

        doc = AsyncMock()
        doc.exists = True

        db = MagicMock()
        db.collection.return_value.document.return_value.get = AsyncMock(return_value=doc)

        result = await is_event_duplicate(db, "evt_existing456")
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_event_processed_writes_to_firestore(self):
        """mark_event_processed sets stripe_events/{event_id} in Firestore."""
        from bot.services.stripe_service import mark_event_processed

        db = MagicMock()
        doc_ref = AsyncMock()
        doc_ref.set = AsyncMock()
        db.collection.return_value.document.return_value = doc_ref

        await mark_event_processed(db, "evt_tomark789")

        doc_ref.set.assert_called_once()
        set_data = doc_ref.set.call_args[0][0]
        assert set_data["event_id"] == "evt_tomark789"
        assert "processed_at" in set_data


# ---------------------------------------------------------------------------
# Tests: handle_checkout_session_completed
# ---------------------------------------------------------------------------

class TestHandleCheckoutSessionCompleted:
    """Tests for checkout.session.completed event handler."""

    @pytest.mark.asyncio
    async def test_sets_subscription_active(self):
        """checkout.session.completed → subscription_status=active, stripe_subscription_id set."""
        from bot.services.stripe_service import handle_checkout_session_completed

        doc_ref = AsyncMock()
        doc_ref.update = AsyncMock()
        db = MagicMock()
        db.collection.return_value.document.return_value = doc_ref

        session_data = {
            "metadata": {"telegram_user_id": "99999"},
            "subscription": "sub_abc123",
        }
        await handle_checkout_session_completed(db, session_data)

        doc_ref.update.assert_called_once()
        update_data = doc_ref.update.call_args[0][0]
        assert update_data["subscription_status"] == "active"
        assert update_data["stripe_subscription_id"] == "sub_abc123"
        assert update_data["grace_period_until"] is None

    @pytest.mark.asyncio
    async def test_handles_missing_telegram_user_id(self):
        """checkout.session.completed without telegram_user_id in metadata → no Firestore write."""
        from bot.services.stripe_service import handle_checkout_session_completed

        db = MagicMock()
        doc_ref = AsyncMock()
        db.collection.return_value.document.return_value = doc_ref

        session_data = {"metadata": {}, "subscription": "sub_xyz"}
        await handle_checkout_session_completed(db, session_data)

        doc_ref.update.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: handle_invoice_payment_failed
# ---------------------------------------------------------------------------

class TestHandleInvoicePaymentFailed:
    """Tests for invoice.payment_failed event handler."""

    @pytest.mark.asyncio
    async def test_sets_grace_period_3_days(self):
        """invoice.payment_failed → subscription_status=grace_period, grace_period_until=now+3d."""
        from bot.services.stripe_service import handle_invoice_payment_failed

        user_doc = AsyncMock()
        user_doc.to_dict.return_value = {"telegram_user_id": 12345, "stripe_customer_id": "cus_fail"}
        user_doc.reference = AsyncMock()
        user_doc.reference.update = AsyncMock()

        db = MagicMock()
        db.collection.return_value.where.return_value.get = AsyncMock(return_value=[user_doc])

        before = datetime.now(tz=timezone.utc)
        await handle_invoice_payment_failed(db, {"customer": "cus_fail"})
        after = datetime.now(tz=timezone.utc)

        user_doc.reference.update.assert_called_once()
        update_data = user_doc.reference.update.call_args[0][0]
        assert update_data["subscription_status"] == "grace_period"

        grace = update_data["grace_period_until"]
        from datetime import timedelta
        assert before + timedelta(days=2) < grace < after + timedelta(days=4)

    @pytest.mark.asyncio
    async def test_skips_when_user_not_found(self):
        """invoice.payment_failed with unknown customer → no writes, no exception."""
        from bot.services.stripe_service import handle_invoice_payment_failed

        db = MagicMock()
        db.collection.return_value.where.return_value.get = AsyncMock(return_value=[])

        # Should not raise
        await handle_invoice_payment_failed(db, {"customer": "cus_unknown"})


# ---------------------------------------------------------------------------
# Tests: handle_invoice_payment_succeeded
# ---------------------------------------------------------------------------

class TestHandleInvoicePaymentSucceeded:
    """Tests for invoice.payment_succeeded event handler."""

    @pytest.mark.asyncio
    async def test_sets_active_and_clears_grace_period(self):
        """invoice.payment_succeeded → subscription_status=active, grace_period_until=None."""
        from bot.services.stripe_service import handle_invoice_payment_succeeded

        user_doc = AsyncMock()
        user_doc.reference = AsyncMock()
        user_doc.reference.update = AsyncMock()

        db = MagicMock()
        db.collection.return_value.where.return_value.get = AsyncMock(return_value=[user_doc])

        await handle_invoice_payment_succeeded(db, {"customer": "cus_ok"})

        user_doc.reference.update.assert_called_once()
        update_data = user_doc.reference.update.call_args[0][0]
        assert update_data["subscription_status"] == "active"
        assert update_data["grace_period_until"] is None


# ---------------------------------------------------------------------------
# Tests: handle_subscription_deleted
# ---------------------------------------------------------------------------

class TestHandleSubscriptionDeleted:
    """Tests for customer.subscription.deleted event handler."""

    @pytest.mark.asyncio
    async def test_sets_blocked(self):
        """customer.subscription.deleted → subscription_status=blocked."""
        from bot.services.stripe_service import handle_subscription_deleted

        user_doc = AsyncMock()
        user_doc.reference = AsyncMock()
        user_doc.reference.update = AsyncMock()

        db = MagicMock()
        db.collection.return_value.where.return_value.get = AsyncMock(return_value=[user_doc])

        await handle_subscription_deleted(db, {"customer": "cus_del"})

        user_doc.reference.update.assert_called_once()
        update_data = user_doc.reference.update.call_args[0][0]
        assert update_data["subscription_status"] == "blocked"
        assert update_data["stripe_subscription_id"] is None
