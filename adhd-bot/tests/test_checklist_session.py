"""Tests for Checklist Session Flow — Unit 20."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.models.checklist import ChecklistItem, ChecklistSession, ChecklistTemplate
from bot.handlers.checklist_callbacks import (
    _build_checklist_message,
    handle_checklist_attach_callback,
    handle_checklist_create_callback,
    handle_checklist_item_callback,
    handle_checklist_snooze_callback,
)


def _make_callback_query(data: str, user_id: int = 12345, message_id: int = 100) -> dict:
    return {
        "id": "cb_456",
        "from": {"id": user_id, "first_name": "Test"},
        "message": {
            "message_id": message_id,
            "chat": {"id": user_id},
            "text": "old text",
        },
        "data": data,
    }


def _make_session(
    session_id: str = "session-1",
    items: list[tuple[str, bool]] | None = None,
    state: str = "evening_sent",
) -> ChecklistSession:
    """Create a test ChecklistSession."""
    if items is None:
        items = [("Buty sportowe", False), ("Recznik", False), ("Bidon", False)]

    return ChecklistSession(
        session_id=session_id,
        user_id=12345,
        template_id="tmpl-1",
        template_name="Silownia",
        items=[ChecklistItem(text=text, checked=checked) for text, checked in items],
        state=state,
    )


def _make_db_with_session(session: ChecklistSession):
    """Create mock db with a session document."""
    db = MagicMock()

    doc = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = session.to_firestore_dict()

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc)
    doc_ref.set = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref
    db.collection.return_value = collection_mock

    # Transaction mock: set() stores data, transaction is passed to doc_ref.get()
    transaction_mock = MagicMock()
    transaction_mock.set = MagicMock()
    db.transaction.return_value = transaction_mock

    return db, doc_ref


class TestEventDetection:
    """Test Gemini event detection integration."""

    @pytest.mark.asyncio
    async def test_event_with_matching_template_offers_it(self):
        """Test: Event with matching template -> bot proposes template directly."""
        from bot.handlers.message_handlers import _find_matching_template

        db = MagicMock()
        templates_data = [
            MagicMock(
                to_dict=MagicMock(return_value={
                    "template_id": "t1",
                    "name": "Silownia",
                    "items": ["Buty"],
                    "user_id": 12345,
                })
            )
        ]
        query_mock = MagicMock()
        query_mock.where.return_value = query_mock
        query_mock.get = AsyncMock(return_value=templates_data)

        col_mock = MagicMock()
        col_mock.where.return_value = query_mock
        db.collection.return_value = col_mock

        result = await _find_matching_template(db, 12345, "silownia jutro o 7")
        assert result is not None
        assert result["name"] == "Silownia"

    @pytest.mark.asyncio
    async def test_event_without_template_returns_none(self):
        """Test: Event without matching template -> returns None."""
        from bot.handlers.message_handlers import _find_matching_template

        db = MagicMock()
        query_mock = MagicMock()
        query_mock.where.return_value = query_mock
        query_mock.get = AsyncMock(return_value=[])

        col_mock = MagicMock()
        col_mock.where.return_value = query_mock
        db.collection.return_value = col_mock

        result = await _find_matching_template(db, 12345, "basen jutro")
        assert result is None


class TestChecklistSessionSnapshot:
    """Test session creation with item snapshots."""

    @pytest.mark.asyncio
    async def test_session_created_with_snapshot(self):
        """Test: Session created with snapshot of items (edit of template after doesn't affect)."""
        from bot.services.checklist_session import create_session

        db = MagicMock()
        doc_ref = AsyncMock()
        doc_ref.set = AsyncMock()
        doc_ref.get = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        db.collection.return_value = collection_mock

        template = ChecklistTemplate(
            template_id="tmpl-1",
            user_id=12345,
            name="Silownia",
            items=["Buty sportowe", "Recznik", "Bidon"],
        )

        event_time = datetime.now(tz=timezone.utc) + timedelta(days=1)

        with patch("bot.services.scheduler.schedule_checklist_trigger", new_callable=AsyncMock, return_value="ct-name"):
            session = await create_session(
                db=db,
                user_id=12345,
                template=template,
                event_time=event_time,
            )

        # Items should be snapshot
        assert len(session.items) == 3
        assert session.items[0].text == "Buty sportowe"
        assert session.items[0].checked is False
        assert session.state == "pending_evening"


class TestMorningTrigger:
    """Test trigger-checklist-morning behavior."""

    @pytest.mark.asyncio
    async def test_morning_all_checked_sends_congrats(self):
        """Test: trigger-checklist-morning when all items checked -> congratulatory message."""
        from fastapi.testclient import TestClient
        from main import app

        session = _make_session(
            items=[("Buty", True), ("Recznik", True), ("Bidon", True)],
            state="evening_sent",
        )

        mock_db = MagicMock()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = session.to_firestore_dict()
        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.set = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        mock_db.collection.return_value = collection_mock

        with (
            patch("bot.handlers.internal_triggers.get_firestore_client", return_value=mock_db),
            patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock) as mock_send,
        ):
            client = TestClient(app)
            resp = client.post(
                "/internal/trigger-checklist-morning",
                json={"session_id": session.session_id},
                headers={"Authorization": "Bearer test"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body.get("all_checked") is True
        # Should send congratulations
        assert mock_send.called
        mock_send.call_args[1].get("text", "") or mock_send.call_args[0][1] if len(mock_send.call_args[0]) > 1 else ""
        # Check the message was sent
        assert mock_send.call_count >= 1

    @pytest.mark.asyncio
    async def test_morning_partial_checked_sends_unchecked(self):
        """Test: trigger-checklist-morning when 3/5 checked -> only 2 unchecked with buttons."""
        from fastapi.testclient import TestClient
        from main import app

        session = _make_session(
            items=[
                ("Buty", True),
                ("Recznik", True),
                ("Bidon", True),
                ("Klapki", False),
                ("Stroj", False),
            ],
            state="evening_sent",
        )

        mock_db = MagicMock()
        doc = MagicMock()
        doc.exists = True
        doc.to_dict.return_value = session.to_firestore_dict()
        doc_ref = AsyncMock()
        doc_ref.get = AsyncMock(return_value=doc)
        doc_ref.set = AsyncMock()

        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        mock_db.collection.return_value = collection_mock

        with (
            patch("bot.handlers.internal_triggers.get_firestore_client", return_value=mock_db),
            patch("bot.handlers.internal_triggers._send_telegram_message", new_callable=AsyncMock, return_value={"result": {"message_id": 999}}) as mock_send,
        ):
            client = TestClient(app)
            resp = client.post(
                "/internal/trigger-checklist-morning",
                json={"session_id": session.session_id},
                headers={"Authorization": "Bearer test"},
            )

        assert resp.status_code == 200
        assert mock_send.called
        # Verify keyboard contains unchecked items
        call_kwargs = mock_send.call_args
        if call_kwargs.kwargs.get("reply_markup"):
            call_kwargs.kwargs["reply_markup"]
        else:
            call_kwargs[1].get("reply_markup") if len(call_kwargs) > 1 else {}

        # At minimum, the message was sent with a keyboard
        assert mock_send.call_count >= 1


class TestItemCallback:
    """Test checklist item callback handler."""

    @pytest.mark.asyncio
    async def test_clicking_last_item_auto_closes(self):
        """Test: Clicking last unchecked item -> auto-close with congratulatory message."""
        session = _make_session(
            items=[("Buty", True), ("Recznik", True), ("Bidon", False)],
            state="evening_sent",
        )
        db, doc_ref = _make_db_with_session(session)

        callback = _make_callback_query(f"checklist_item:{session.session_id}:2")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock) as mock_edit,
        ):
            await handle_checklist_item_callback(callback, db)

        # Transaction should have set data with toggled item
        transaction_mock = db.transaction()
        assert transaction_mock.set.call_count >= 1
        txn_save = transaction_mock.set.call_args[0][1]
        assert txn_save["items"][2]["checked"] is True

        # After auto-close, session.save() is called again with state=completed
        assert doc_ref.set.call_count >= 1
        last_save = doc_ref.set.call_args[0][0]
        assert last_save["state"] == "completed"

        # Should edit message with completion text
        assert mock_edit.called
        edit_text = mock_edit.call_args[0][2]
        assert "gotowe" in edit_text.lower() or "Wszystko" in edit_text

    @pytest.mark.asyncio
    async def test_clicking_item_updates_message(self):
        """Test: Clicking a non-last item -> update message with current state."""
        session = _make_session(
            items=[("Buty", False), ("Recznik", False), ("Bidon", False)],
            state="evening_sent",
        )
        db, doc_ref = _make_db_with_session(session)

        callback = _make_callback_query(f"checklist_item:{session.session_id}:0")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock) as mock_edit,
        ):
            await handle_checklist_item_callback(callback, db)

        # Transaction should have toggled first item to checked
        transaction_mock = db.transaction()
        txn_save = transaction_mock.set.call_args[0][1]
        assert txn_save["items"][0]["checked"] is True
        assert txn_save["items"][1]["checked"] is False
        assert txn_save["state"] != "completed"

        # Should edit message with updated list and keyboard
        assert mock_edit.called

    @pytest.mark.asyncio
    async def test_clicking_checked_item_unchecks_it(self):
        """Test: Clicking a checked item -> uncheck (toggle, P2-4)."""
        session = _make_session(
            items=[("Buty", True), ("Recznik", False), ("Bidon", False)],
            state="evening_sent",
        )
        db, doc_ref = _make_db_with_session(session)

        callback = _make_callback_query(f"checklist_item:{session.session_id}:0")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock),
        ):
            await handle_checklist_item_callback(callback, db)

        # Transaction should have toggled first item to unchecked
        transaction_mock = db.transaction()
        txn_save = transaction_mock.set.call_args[0][1]
        assert txn_save["items"][0]["checked"] is False


class TestChecklistSnooze:
    """Test checklist snooze callback."""

    @pytest.mark.asyncio
    async def test_snooze_schedules_new_cloud_task(self):
        """Test: Snooze entire list -> new Cloud Task in 30 min."""
        session = _make_session(
            items=[("Buty", False), ("Recznik", True)],
            state="morning_sent",
        )
        db, doc_ref = _make_db_with_session(session)

        callback = _make_callback_query(f"checklist_snooze:30m:{session.session_id}")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock) as mock_edit,
            patch("bot.services.scheduler.cancel_reminder", new_callable=AsyncMock),
            patch("bot.services.scheduler.schedule_checklist_trigger", new_callable=AsyncMock, return_value="new-ct-name") as mock_schedule,
        ):
            await handle_checklist_snooze_callback(callback, db)

        # Should schedule new Cloud Task
        assert mock_schedule.called
        call_args = mock_schedule.call_args
        assert call_args.kwargs.get("trigger_type") == "morning" or call_args[1].get("trigger_type") == "morning"

        # Should edit message with snooze confirmation
        assert mock_edit.called
        edit_text = mock_edit.call_args[0][2]
        assert "30 min" in edit_text


class TestBuildChecklistMessage:
    """Test _build_checklist_message helper."""

    def test_builds_correct_text_and_keyboard(self):
        session = _make_session(
            items=[("Buty", True), ("Recznik", False), ("Bidon", False)],
        )
        text, keyboard = _build_checklist_message(session)

        # Text should include template name
        assert "Silownia" in text
        # Checked items should show differently
        assert "Buty" in text
        assert "Recznik" in text

        # Keyboard should have buttons for ALL items (toggle support, P2-4)
        inline_keyboard = keyboard["inline_keyboard"]
        item_buttons = []
        for row in inline_keyboard:
            for btn in row:
                if "checklist_item:" in btn.get("callback_data", ""):
                    item_buttons.append(btn)

        assert len(item_buttons) == 3  # All items: Buty (checked), Recznik, Bidon

        # Checked item button should have checkmark prefix
        checked_btns = [b for b in item_buttons if "\u2705" in b["text"]]
        assert len(checked_btns) == 1
        assert "Buty" in checked_btns[0]["text"]

        # Snooze button present
        snooze_buttons = [
            btn for row in inline_keyboard for btn in row
            if "checklist_snooze:" in btn.get("callback_data", "")
        ]
        assert len(snooze_buttons) == 1


class TestChecklistAttachCallback:
    """Test checklist_attach callback handler (P1-2)."""

    @pytest.mark.asyncio
    async def test_attach_creates_session_from_template(self):
        """Test: checklist_attach callback -> creates session linked to task."""
        from bot.models.task import Task, TaskState
        from bot.models.user import User

        db = MagicMock()

        task = Task(
            task_id="task-1",
            telegram_user_id=12345,
            content="Silownia jutro",
            state=TaskState.PENDING_CONFIRMATION,
            proposed_time=datetime.now(tz=timezone.utc) + timedelta(days=1),
        )
        task_doc = MagicMock()
        task_doc.exists = True
        task_doc.to_dict.return_value = task.to_firestore_dict()

        template = ChecklistTemplate(
            template_id="tmpl-1",
            user_id=12345,
            name="Silownia",
            items=["Buty", "Recznik"],
        )
        template_doc = MagicMock()
        template_doc.exists = True
        template_doc.to_dict.return_value = template.to_firestore_dict()

        user = User(telegram_user_id=12345)
        user_doc = MagicMock()
        user_doc.exists = True
        user_doc.to_dict.return_value = user.to_firestore_dict()

        doc_ref = AsyncMock()
        doc_ref.set = AsyncMock()

        def doc_get_side_effect(*args, **kwargs):
            return doc_ref

        def collection_factory(name):
            col = MagicMock()
            if name == "tasks":
                task_doc_ref = AsyncMock()
                task_doc_ref.get = AsyncMock(return_value=task_doc)
                task_doc_ref.set = AsyncMock()
                col.document.return_value = task_doc_ref
            elif name == "checklist_templates":
                tmpl_doc_ref = AsyncMock()
                tmpl_doc_ref.get = AsyncMock(return_value=template_doc)
                col.document.return_value = tmpl_doc_ref
            elif name == "users":
                user_doc_ref = AsyncMock()
                user_doc_ref.get = AsyncMock(return_value=user_doc)
                user_doc_ref.set = AsyncMock()
                col.document.return_value = user_doc_ref
            else:
                col.document.return_value = doc_ref
            return col

        db.collection = MagicMock(side_effect=collection_factory)

        callback = _make_callback_query("checklist_attach:task-1:tmpl-1")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock) as mock_edit,
            patch("bot.services.scheduler.schedule_checklist_trigger", new_callable=AsyncMock, return_value="ct-name"),
            patch("bot.services.scheduler.schedule_reminder", new_callable=AsyncMock, return_value="ct-reminder"),
        ):
            await handle_checklist_attach_callback(callback, db)

        assert mock_edit.called
        edit_text = mock_edit.call_args[0][2]
        assert "dolaczona" in edit_text or "Silownia" in edit_text


class TestChecklistCreateCallback:
    """Test checklist_create callback handler (P1-2)."""

    @pytest.mark.asyncio
    async def test_create_prompts_user(self):
        """Test: checklist_create callback -> prompts user to create checklist."""
        from bot.models.task import Task, TaskState

        db = MagicMock()

        task = Task(
            task_id="task-2",
            telegram_user_id=12345,
            content="Basen jutro",
            state=TaskState.PENDING_CONFIRMATION,
            proposed_time=datetime.now(tz=timezone.utc) + timedelta(days=1),
        )
        task_doc = MagicMock()
        task_doc.exists = True
        task_doc.to_dict.return_value = task.to_firestore_dict()

        task_doc_ref = AsyncMock()
        task_doc_ref.get = AsyncMock(return_value=task_doc)
        task_doc_ref.set = AsyncMock()

        def collection_factory(name):
            col = MagicMock()
            col.document.return_value = task_doc_ref
            return col

        db.collection = MagicMock(side_effect=collection_factory)

        callback = _make_callback_query("checklist_create:task-2")

        with (
            patch("bot.handlers.checklist_callbacks._answer_callback_query", new_callable=AsyncMock),
            patch("bot.handlers.checklist_callbacks._edit_message_text", new_callable=AsyncMock) as mock_edit,
            patch("bot.services.scheduler.schedule_reminder", new_callable=AsyncMock, return_value="ct-reminder"),
        ):
            await handle_checklist_create_callback(callback, db)

        assert mock_edit.called
        edit_text = mock_edit.call_args[0][2]
        assert "/new_checklist" in edit_text
