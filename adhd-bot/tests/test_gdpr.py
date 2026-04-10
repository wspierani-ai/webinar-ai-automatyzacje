"""Tests for GDPR — Unit 21: /delete_my_data + Privacy Policy."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.command_handlers import handle_delete_my_data
from bot.handlers.gdpr_handler import (
    cascade_delete_user_data,
    handle_gdpr_cancel_callback,
    handle_gdpr_confirm_callback,
)


def _make_message(text: str, user_id: int = 12345) -> dict:
    return {
        "message_id": 1,
        "from": {"id": user_id, "first_name": "Test", "username": "testuser"},
        "chat": {"id": user_id},
        "text": text,
        "date": 1700000000,
    }


def _make_callback_query(data: str, user_id: int = 12345) -> dict:
    return {
        "id": "cb_789",
        "from": {"id": user_id, "first_name": "Test"},
        "message": {
            "message_id": 100,
            "chat": {"id": user_id},
            "text": "warning text",
        },
        "data": data,
    }


def _make_user_db(
    user_id: int = 12345,
    stripe_subscription_id: str | None = None,
    google_connected: bool = False,
):
    """Create mock db with user document and per-user collections."""
    db = MagicMock()

    user_data = {
        "telegram_user_id": user_id,
        "subscription_status": "active",
        "stripe_subscription_id": stripe_subscription_id,
        "stripe_customer_id": "cus_123" if stripe_subscription_id else None,
        "google_connected": google_connected,
    }

    # User document
    user_doc = MagicMock()
    user_doc.exists = True
    user_doc.to_dict.return_value = user_data

    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)
    user_doc_ref.set = AsyncMock()
    user_doc_ref.delete = AsyncMock()

    # Per-collection docs (tasks, token_usage, etc.)
    collection_docs = {
        "tasks": [_make_doc_mock({"telegram_user_id": user_id, "task_id": "t1"})],
        "token_usage": [_make_doc_mock({"user_id": user_id})],
        "checklist_templates": [],
        "checklist_sessions": [],
        "processed_updates": [],
        "users": [],
    }

    def collection_factory(name):
        col = MagicMock()

        if name == "users":
            col.document.return_value = user_doc_ref
            return col

        # For other collections, return query results
        query_mock = MagicMock()
        query_mock.where.return_value = query_mock
        docs = collection_docs.get(name, [])
        query_mock.get = AsyncMock(return_value=docs)
        col.where.return_value = query_mock
        col.document.return_value = user_doc_ref

        return col

    db.collection = MagicMock(side_effect=collection_factory)
    return db, user_doc_ref


def _make_doc_mock(data: dict):
    doc = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = data
    doc.reference = MagicMock()
    doc.reference.delete = AsyncMock()
    return doc


class TestDeleteMyDataCommand:
    """Test /delete_my_data command without confirmation."""

    @pytest.mark.asyncio
    async def test_sends_warning_without_deleting(self):
        """Test: /delete_my_data without confirmation -> no deletion."""
        db, doc_ref = _make_user_db()

        with patch("bot.handlers.command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_delete_my_data(_make_message("/delete_my_data"), db)

        # Should send warning message with buttons
        assert mock_send.called
        call_kwargs = mock_send.call_args
        sent_text = call_kwargs[0][1]
        assert "usunie" in sent_text.lower() or "WSZYSTKIE" in sent_text

        # Should have reply_markup with confirm/cancel buttons
        reply_markup = call_kwargs[1].get("reply_markup") if call_kwargs[1] else call_kwargs.kwargs.get("reply_markup")
        assert reply_markup is not None

        # Should NOT delete anything
        doc_ref.delete.assert_not_called()


class TestCascadeDeleteUserData:
    """Test cascade deletion of all user data."""

    @pytest.mark.asyncio
    async def test_deletes_all_collections(self):
        """Test: /delete_my_data with confirmation -> all user collections deleted from Firestore."""
        db, user_doc_ref = _make_user_db()

        summary = await cascade_delete_user_data(db, 12345)

        # User document should be deleted
        user_doc_ref.delete.assert_called()
        assert summary["user_deleted"] is True

        # tasks and token_usage should have docs deleted
        assert summary["collections_deleted"]["tasks"] == 1
        assert summary["collections_deleted"]["token_usage"] == 1

    @pytest.mark.asyncio
    async def test_cancels_stripe_subscription_if_exists(self):
        """Test: /delete_my_data cancels Stripe subscription if exists."""
        db, _ = _make_user_db(stripe_subscription_id="sub_abc123")

        with patch("stripe.Subscription.cancel") as mock_cancel:
            summary = await cascade_delete_user_data(db, 12345)

        assert summary["stripe_cancelled"] is True
        mock_cancel.assert_called_once_with("sub_abc123")

    @pytest.mark.asyncio
    async def test_no_stripe_cancel_when_no_subscription(self):
        """Test: /delete_my_data without Stripe subscription -> no cancel."""
        db, _ = _make_user_db(stripe_subscription_id=None)

        summary = await cascade_delete_user_data(db, 12345)
        assert summary["stripe_cancelled"] is False

    @pytest.mark.asyncio
    async def test_revokes_google_token_if_connected(self):
        """Test: /delete_my_data revokes Google token if connected."""
        db, _ = _make_user_db(google_connected=True)

        with patch("bot.services.google_auth.disconnect_google", new_callable=AsyncMock) as mock_disconnect:
            summary = await cascade_delete_user_data(db, 12345)

        assert summary["google_revoked"] is True
        mock_disconnect.assert_called_once_with(db, 12345)

    @pytest.mark.asyncio
    async def test_no_google_revoke_when_not_connected(self):
        """Test: /delete_my_data without Google connection -> no revoke."""
        db, _ = _make_user_db(google_connected=False)

        summary = await cascade_delete_user_data(db, 12345)
        assert summary["google_revoked"] is False


class TestGdprConfirmCallback:
    """Test GDPR confirm/cancel callbacks."""

    @pytest.mark.asyncio
    async def test_confirm_triggers_deletion(self):
        db, _ = _make_user_db()
        callback = _make_callback_query("gdpr_confirm_delete")

        with (
            patch("bot.handlers.gdpr_handler._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.gdpr_handler._send_message", new_callable=AsyncMock) as mock_send,
            patch("bot.handlers.gdpr_handler.cascade_delete_user_data", new_callable=AsyncMock, return_value={"user_deleted": True}) as mock_delete,
        ):
            await handle_gdpr_confirm_callback(callback, db)

        mock_delete.assert_called_once_with(db, 12345)
        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "usuniete" in sent_text

    @pytest.mark.asyncio
    async def test_cancel_does_not_delete(self):
        db, _ = _make_user_db()
        callback = _make_callback_query("gdpr_cancel_delete")

        with (
            patch("bot.handlers.gdpr_handler._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.gdpr_handler._send_message", new_callable=AsyncMock) as mock_send,
        ):
            await handle_gdpr_cancel_callback(callback, db)

        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "Anulowano" in sent_text


class TestPrivacyEndpoint:
    """Test GET /privacy endpoint."""

    def test_privacy_returns_200_with_html(self):
        """Test: GET /privacy returns 200 with HTML."""
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        resp = client.get("/privacy")

        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "Polityka Prywatności" in resp.text or "Polityka Prywatnosci" in resp.text
        assert "RODO" in resp.text or "delete_my_data" in resp.text
