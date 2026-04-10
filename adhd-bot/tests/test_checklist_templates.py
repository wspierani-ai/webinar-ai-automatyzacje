"""Tests for Checklist Template Management — Unit 19."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models.checklist import (
    ChecklistTemplate,
    ChecklistValidationError,
    MAX_CHECKLIST_ITEMS,
)
from bot.handlers.checklist_command_handlers import (
    _validate_evening_time,
    handle_checklists,
    handle_evening,
    handle_new_checklist,
)
from bot.handlers.checklist_command_handlers import handle_checklist_delete_callback
from bot.models.user import User


def _make_message(text: str, user_id: int = 12345) -> dict:
    return {
        "message_id": 1,
        "from": {"id": user_id, "first_name": "Test", "username": "testuser"},
        "chat": {"id": user_id},
        "text": text,
        "date": 1700000000,
    }


def _make_callback_query(data: str, user_id: int = 12345, message_id: int = 100) -> dict:
    return {
        "id": "cb_123",
        "from": {"id": user_id, "first_name": "Test"},
        "message": {
            "message_id": message_id,
            "chat": {"id": user_id},
            "text": "old text",
        },
        "data": data,
    }


def _make_db_with_templates(templates: list[dict] | None = None):
    """Create mock db, optionally with pre-existing checklist templates."""
    db = MagicMock()

    # Template collection mock
    template_docs = []
    if templates:
        for tmpl_data in templates:
            doc = MagicMock()
            doc.exists = True
            doc.to_dict.return_value = tmpl_data
            doc.reference = MagicMock()
            doc.reference.delete = AsyncMock()
            template_docs.append(doc)

    query_mock = MagicMock()
    query_mock.where.return_value = query_mock
    query_mock.get = AsyncMock(return_value=template_docs)

    # Individual doc mock
    single_doc = MagicMock()
    if templates:
        single_doc.exists = True
        single_doc.to_dict.return_value = templates[0]
    else:
        single_doc.exists = False
        single_doc.to_dict.return_value = {}

    single_doc_ref = AsyncMock()
    single_doc_ref.get = AsyncMock(return_value=single_doc)
    single_doc_ref.set = AsyncMock()
    single_doc_ref.delete = AsyncMock()

    def collection_factory(name):
        col = MagicMock()
        col.where.return_value = query_mock
        col.document.return_value = single_doc_ref
        return col

    db.collection = MagicMock(side_effect=collection_factory)

    # Also make user collection work
    user_doc = MagicMock()
    user_doc.exists = False
    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)
    user_doc_ref.set = AsyncMock()

    return db, single_doc_ref


class TestNewChecklistCommand:
    """Test /new_checklist command behavior."""

    @pytest.mark.asyncio
    async def test_new_checklist_gemini_suggests_items(self):
        """Test: /new_checklist Silownia -> Gemini suggests <=8 items."""
        db, doc_ref = _make_db_with_templates()
        suggested = ["Buty sportowe", "Recznik", "Bidon", "Odzyz", "Sluchawki"]

        with (
            patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send,
            patch("bot.services.checklist_ai.suggest_items", new_callable=AsyncMock, return_value=suggested),
        ):
            await handle_new_checklist(_make_message("/new_checklist Silownia"), db)

        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "Silownia" in sent_text
        # Template should be saved
        doc_ref.set.assert_called_once()
        saved = doc_ref.set.call_args[0][0]
        assert len(saved["items"]) <= 8
        assert saved["name"] == "Silownia"

    @pytest.mark.asyncio
    async def test_new_checklist_no_name_sends_usage(self):
        """Test: /new_checklist without name shows usage."""
        db, _ = _make_db_with_templates()

        with patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_new_checklist(_make_message("/new_checklist"), db)

        sent_text = mock_send.call_args[0][1]
        assert "Uzycie" in sent_text


class TestChecklistTemplateValidation:
    """Test template validation constraints."""

    def test_template_with_more_than_12_items_raises(self):
        """Test: Szablon z >12 itemami -> blad walidacji."""
        items = [f"Item {i}" for i in range(MAX_CHECKLIST_ITEMS + 1)]
        template = ChecklistTemplate(
            user_id=12345,
            name="Too Many",
            items=items,
        )
        with pytest.raises(ChecklistValidationError):
            template.validate()

    def test_template_with_12_items_ok(self):
        items = [f"Item {i}" for i in range(MAX_CHECKLIST_ITEMS)]
        template = ChecklistTemplate(
            user_id=12345,
            name="Just Right",
            items=items,
        )
        template.validate()  # Should not raise

    def test_template_with_empty_name_raises(self):
        template = ChecklistTemplate(user_id=12345, name="", items=["Item 1"])
        with pytest.raises(ChecklistValidationError):
            template.validate()


class TestChecklistsCommand:
    """Test /checklists command behavior."""

    @pytest.mark.asyncio
    async def test_no_templates_shows_message(self):
        """Test: /checklists for user with no templates -> 'Nie masz jeszcze zadnych list'."""
        db, _ = _make_db_with_templates(templates=None)

        with patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_checklists(_make_message("/checklists"), db)

        sent_text = mock_send.call_args[0][1]
        assert "Nie masz jeszcze" in sent_text

    @pytest.mark.asyncio
    async def test_with_templates_lists_them(self):
        templates = [
            {
                "template_id": "t1",
                "user_id": 12345,
                "name": "Silownia",
                "items": ["Buty", "Recznik"],
                "evening_enabled": True,
                "created_at": None,
                "updated_at": None,
            }
        ]
        db, _ = _make_db_with_templates(templates=templates)

        with patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_checklists(_make_message("/checklists"), db)

        sent_text = mock_send.call_args[0][1]
        assert "Silownia" in sent_text


class TestDeleteTemplate:
    """Test template deletion via callback."""

    @pytest.mark.asyncio
    async def test_delete_template_removes_from_firestore(self):
        """Test: [Usun] template -> deleted from Firestore."""
        db = MagicMock()

        # Setup doc that exists
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = {"name": "Silownia", "template_id": "t1"}

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.delete = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        db.collection.return_value = collection_mock

        callback = _make_callback_query("checklist_delete:t1")

        # Mock both _send_message AND httpx.AsyncClient (used for answerCallbackQuery)
        mock_httpx_client = AsyncMock()
        mock_httpx_client.post = AsyncMock()

        with (
            patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send,
            patch("httpx.AsyncClient") as mock_httpx_cls,
        ):
            mock_httpx_cls.return_value.__aenter__ = AsyncMock(return_value=mock_httpx_client)
            mock_httpx_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            await handle_checklist_delete_callback(callback, db)

        doc_ref.delete.assert_called_once()
        assert mock_send.called
        sent_text = mock_send.call_args[0][1]
        assert "usuniety" in sent_text


class TestEveningCommand:
    """Test /evening command behavior."""

    @pytest.mark.asyncio
    async def test_valid_evening_time_updates_user(self):
        """Test: /evening 20:30 -> user.evening_time = '20:30'."""
        db = MagicMock()

        existing_user = User(telegram_user_id=12345)
        doc_mock = MagicMock()
        doc_mock.exists = True
        doc_mock.to_dict.return_value = existing_user.to_firestore_dict()

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc_mock)
        doc_ref.set = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        db.collection.return_value = collection_mock

        with patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_evening(_make_message("/evening 20:30"), db)

        doc_ref.set.assert_called()
        saved = doc_ref.set.call_args[0][0]
        assert saved["evening_time"] == "20:30"

    @pytest.mark.asyncio
    async def test_invalid_evening_time_25_00(self):
        """Test: /evening 25:00 -> error validation."""
        db = MagicMock()

        existing_user = User(telegram_user_id=12345)
        doc_mock = MagicMock()
        doc_mock.exists = True
        doc_mock.to_dict.return_value = existing_user.to_firestore_dict()

        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc_mock)
        doc_ref.set = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        db.collection.return_value = collection_mock

        with patch("bot.handlers.checklist_command_handlers._send_message", new_callable=AsyncMock) as mock_send:
            await handle_evening(_make_message("/evening 25:00"), db)

        # Should NOT save
        doc_ref.set.assert_not_called()
        sent_text = mock_send.call_args[0][1]
        assert "Nieprawidlowa" in sent_text


class TestEveningTimeValidator:
    """Unit tests for _validate_evening_time."""

    def test_valid_times(self):
        assert _validate_evening_time("20:30") is True
        assert _validate_evening_time("21:00") is True
        assert _validate_evening_time("00:00") is True
        assert _validate_evening_time("23:59") is True

    def test_invalid_times(self):
        assert _validate_evening_time("25:00") is False
        assert _validate_evening_time("24:00") is False
        assert _validate_evening_time("08:60") is False
        assert _validate_evening_time("abc") is False
        assert _validate_evening_time("8:00") is False
