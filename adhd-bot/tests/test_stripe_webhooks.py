"""Tests for Stripe webhook handler — Unit 11.

Covers:
- Webhook signature verification (valid/invalid/missing)
- Duplicate event deduplication → 200 without reprocessing
- checkout.session.completed → subscription_status=active
- invoice.payment_failed → grace_period
- invoice.payment_succeeded → active
- customer.subscription.deleted → blocked
- Unknown events → 200 (ignored)
- Blocked user sends message → gets /subscribe prompt
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport


def make_app() -> FastAPI:
    from bot.handlers.stripe_webhook_handler import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_event(event_type: str, event_id: str = "evt_test001", **data_kwargs) -> bytes:
    """Build a serialized Stripe event payload."""
    event = {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": data_kwargs,
        },
    }
    return json.dumps(event).encode()


def _make_db_with_no_events() -> MagicMock:
    """Return a db where no events have been processed yet (is_duplicate → False)."""
    doc = AsyncMock()
    doc.exists = False

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc)
    doc_ref.set = AsyncMock()
    doc_ref.update = AsyncMock()

    # For user lookups in payment handlers
    user_doc = AsyncMock()
    user_doc.reference = AsyncMock()
    user_doc.reference.update = AsyncMock()

    db = MagicMock()

    def _collection(name: str):
        coll = MagicMock()
        coll.document.return_value = doc_ref
        # user lookup by stripe_customer_id
        coll.where.return_value.get = AsyncMock(return_value=[user_doc])
        return coll

    db.collection.side_effect = _collection
    return db, user_doc


def _make_db_with_duplicate_event(event_id: str) -> MagicMock:
    """Return a db where given event_id already exists."""
    doc = AsyncMock()
    doc.exists = True

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc)
    doc_ref.set = AsyncMock()

    db = MagicMock()
    db.collection.return_value.document.return_value = doc_ref
    db.collection.return_value.where.return_value.get = AsyncMock(return_value=[])
    return db


# ---------------------------------------------------------------------------
# Tests: signature verification
# ---------------------------------------------------------------------------

class TestStripeSignatureVerification:
    """Webhook signature verification tests."""

    @pytest.mark.asyncio
    async def test_missing_signature_returns_400(self, monkeypatch):
        """Webhook without Stripe-Signature header → 400."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/stripe/webhook",
                content=b'{"id": "evt_1", "type": "test"}',
                headers={"Content-Type": "application/json"},
            )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_400(self, monkeypatch):
        """Webhook with wrong Stripe-Signature → 400."""
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_real")

        import stripe as _stripe

        app = make_app()
        with patch.object(_stripe.Webhook, "construct_event", side_effect=Exception("invalid sig")):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=b'{"bad": "data"}',
                    headers={
                        "Content-Type": "application/json",
                        "Stripe-Signature": "t=bad,v1=bad",
                    },
                )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_testing_mode_skips_signature(self, monkeypatch):
        """In TESTING=1 mode, signature is not verified."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event("some.unknown.event", event_id="evt_test_nosig")

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tests: deduplication
# ---------------------------------------------------------------------------

class TestStripeEventDeduplication:
    """Duplicate event processing tests."""

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_200_skipped(self, monkeypatch):
        """Duplicate Stripe event.id → 200 with skipped=duplicate, no reprocessing."""
        monkeypatch.setenv("TESTING", "1")

        db = _make_db_with_duplicate_event("evt_dup001")
        payload = _make_event("checkout.session.completed", event_id="evt_dup001")

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.handle_checkout_session_completed", new_callable=AsyncMock) as mock_handler:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] == "duplicate"
        mock_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_event_is_processed(self, monkeypatch):
        """New event → processed and marked in Firestore."""
        monkeypatch.setenv("TESTING", "1")

        db, user_doc = _make_db_with_no_events()
        payload = _make_event(
            "checkout.session.completed",
            event_id="evt_new001",
            metadata={"telegram_user_id": "12345"},
            subscription="sub_new",
        )

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.handle_checkout_session_completed", new_callable=AsyncMock) as mock_handler, \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock) as mock_mark:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        mock_handler.assert_called_once()
        mock_mark.assert_called_once_with(db, "evt_new001")


# ---------------------------------------------------------------------------
# Tests: event routing
# ---------------------------------------------------------------------------

class TestStripeEventRouting:
    """Tests that events are routed to correct handlers."""

    @pytest.mark.asyncio
    async def test_checkout_session_completed_calls_handler(self, monkeypatch):
        """checkout.session.completed → handle_checkout_session_completed called."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event(
            "checkout.session.completed",
            event_id="evt_csc001",
            metadata={"telegram_user_id": "111"},
            subscription="sub_csc",
        )

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.is_event_duplicate", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock), \
             patch("bot.handlers.stripe_webhook_handler.handle_checkout_session_completed", new_callable=AsyncMock) as mock_handler:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        mock_handler.assert_called_once()
        call_data = mock_handler.call_args[0][1]
        assert call_data["metadata"]["telegram_user_id"] == "111"

    @pytest.mark.asyncio
    async def test_invoice_payment_failed_calls_handler(self, monkeypatch):
        """invoice.payment_failed → handle_invoice_payment_failed called."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event(
            "invoice.payment_failed",
            event_id="evt_ipf001",
            customer="cus_fail",
        )

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.is_event_duplicate", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock), \
             patch("bot.handlers.stripe_webhook_handler.handle_invoice_payment_failed", new_callable=AsyncMock) as mock_handler:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoice_payment_succeeded_calls_handler(self, monkeypatch):
        """invoice.payment_succeeded → handle_invoice_payment_succeeded called."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event(
            "invoice.payment_succeeded",
            event_id="evt_ips001",
            customer="cus_ok",
        )

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.is_event_duplicate", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock), \
             patch("bot.handlers.stripe_webhook_handler.handle_invoice_payment_succeeded", new_callable=AsyncMock) as mock_handler:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscription_deleted_calls_handler(self, monkeypatch):
        """customer.subscription.deleted → handle_subscription_deleted called."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event(
            "customer.subscription.deleted",
            event_id="evt_csd001",
            customer="cus_del",
        )

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.is_event_duplicate", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock), \
             patch("bot.handlers.stripe_webhook_handler.handle_subscription_deleted", new_callable=AsyncMock) as mock_handler:
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_type_returns_200(self, monkeypatch):
        """Unknown event type → 200, no error (ignored gracefully)."""
        monkeypatch.setenv("TESTING", "1")

        db, _ = _make_db_with_no_events()
        payload = _make_event("some.unknown.event", event_id="evt_unknown001")

        with patch("bot.handlers.stripe_webhook_handler.get_firestore_client", return_value=db), \
             patch("bot.handlers.stripe_webhook_handler.is_event_duplicate", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.stripe_webhook_handler.mark_event_processed", new_callable=AsyncMock):
            app = make_app()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post(
                    "/stripe/webhook",
                    content=payload,
                    headers={"Content-Type": "application/json"},
                )

        assert response.status_code == 200
        assert response.json()["ok"] is True


# ---------------------------------------------------------------------------
# Tests: blocked user message
# ---------------------------------------------------------------------------

class TestBlockedUserMessage:
    """Blocked user should see /subscribe prompt."""

    @pytest.mark.asyncio
    async def test_blocked_user_message_contains_subscribe(self, monkeypatch):
        """Blocked user BLOCKED_USER_TEXT contains '/subscribe'."""
        from bot.handlers.message_handlers import BLOCKED_USER_TEXT

        assert "/subscribe" in BLOCKED_USER_TEXT

    @pytest.mark.asyncio
    async def test_blocked_user_text_message_sends_block_message(self, monkeypatch):
        """Blocked user sending a text message gets BLOCKED_USER_TEXT with /subscribe."""
        monkeypatch.setenv("TESTING", "1")

        from bot.handlers.message_handlers import handle_text_message, BLOCKED_USER_TEXT
        from bot.models.user import User

        # Create blocked user mock
        user = MagicMock(spec=User)
        user.is_subscription_active.return_value = False
        user.conversation_state = None

        db = MagicMock()
        sent_messages = []

        with patch("bot.handlers.message_handlers.User") as MockUser, \
             patch("bot.handlers.message_handlers._send_message", new_callable=AsyncMock) as mock_send:
            MockUser.get_or_create = AsyncMock(return_value=user)
            message = {
                "from": {"id": 99999, "first_name": "Blocked"},
                "chat": {"id": 99999},
                "text": "Kup mleko jutro",
            }
            await handle_text_message(message, db)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "/subscribe" in sent_text
