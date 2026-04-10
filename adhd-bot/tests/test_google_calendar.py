"""Tests for Google Calendar integration — Unit 13.

Covers:
- create_calendar_event creates event with correct scheduled_time
- create_calendar_event skips gracefully when user has no Google
- update_calendar_event_time calls events.patch with new time
- complete_calendar_event calls patch with green colorId
- delete_calendar_event calls events.delete
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(user_data: dict | None = None, user_exists: bool = True) -> MagicMock:
    """Return mock Firestore db."""
    db = MagicMock()

    user_doc = AsyncMock()
    user_doc.exists = user_exists
    user_doc.to_dict = MagicMock(
        return_value=user_data or {"google_calendar_id": "primary"}
    )

    task_doc_ref = AsyncMock()
    task_doc_ref.update = AsyncMock()

    user_doc_ref = AsyncMock()
    user_doc_ref.get = AsyncMock(return_value=user_doc)

    def _document_selector(doc_id: str):
        return user_doc_ref

    db.collection.return_value.document.side_effect = _document_selector
    return db


def _make_task(
    task_id: str = "task-001",
    content: str = "Kupić mleko",
    scheduled_time: datetime | None = None,
    google_calendar_event_id: str | None = None,
) -> MagicMock:
    """Return mock Task."""
    task = MagicMock()
    task.task_id = task_id
    task.content = content
    task.scheduled_time = scheduled_time or datetime.now(tz=timezone.utc) + timedelta(hours=1)
    task.google_calendar_event_id = google_calendar_event_id
    return task


def _make_google_service_mock(event_id: str = "event-abc-123") -> MagicMock:
    """Return mock Google Calendar service."""
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {"id": event_id}
    service.events.return_value.patch.return_value.execute.return_value = {"id": event_id}
    service.events.return_value.delete.return_value.execute.return_value = {}
    return service


# ---------------------------------------------------------------------------
# Tests: create_calendar_event
# ---------------------------------------------------------------------------

class TestCreateCalendarEvent:
    """Tests for create_calendar_event."""

    @pytest.mark.asyncio
    async def test_skips_gracefully_when_user_has_no_google(self):
        """create_calendar_event → None + no error when user not connected."""
        from bot.services.google_calendar import create_calendar_event

        db = _make_db()
        task = _make_task()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value=None),
        ):
            result = await create_calendar_event(db, 123, task)

        assert result is None

    @pytest.mark.asyncio
    async def test_creates_event_with_correct_scheduled_time(self):
        """create_calendar_event creates event with correct start time."""
        from bot.services.google_calendar import create_calendar_event

        scheduled_time = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
        task = _make_task(scheduled_time=scheduled_time)

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        task_doc_ref = AsyncMock()
        task_doc_ref.update = AsyncMock()

        def _select_doc(doc_id):
            if doc_id == str(123):
                return user_doc_ref
            return task_doc_ref

        db.collection.return_value.document.side_effect = _select_doc

        mock_service = _make_google_service_mock("new-event-id")

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_calendar._build_google_service",
            return_value=mock_service,
        ):
            result = await create_calendar_event(db, 123, task)

        assert result == "new-event-id"
        # Verify insert was called
        mock_service.events.return_value.insert.assert_called_once()
        insert_call = mock_service.events.return_value.insert.call_args

        # Verify the call kwargs
        kwargs = insert_call[1]
        assert kwargs.get("calendarId") == "primary"
        event_body = kwargs.get("body", {})
        assert event_body.get("summary") == "Kupić mleko"
        assert "2026-05-01T14:00:00+00:00" in event_body["start"]["dateTime"]

    @pytest.mark.asyncio
    async def test_saves_event_id_to_task_document(self):
        """create_calendar_event saves event_id to Firestore task document."""
        from bot.services.google_calendar import create_calendar_event

        task = _make_task(task_id="task-xyz")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)

        task_doc_ref = AsyncMock()
        task_doc_ref.update = AsyncMock()

        def _select_doc(doc_id):
            if doc_id == "123":
                return user_doc_ref
            return task_doc_ref

        db.collection.return_value.document.side_effect = _select_doc

        mock_service = _make_google_service_mock("saved-event-id")

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_calendar._build_google_service",
            return_value=mock_service,
        ):
            result = await create_calendar_event(db, 123, task)

        assert result == "saved-event-id"
        task_doc_ref.update.assert_called_once_with({"google_calendar_event_id": "saved-event-id"})

    @pytest.mark.asyncio
    async def test_skips_when_task_has_no_scheduled_time(self):
        """create_calendar_event → None when task.scheduled_time is None."""
        from bot.services.google_calendar import create_calendar_event

        db = _make_db()
        task = _make_task()
        task.scheduled_time = None

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ):
            result = await create_calendar_event(db, 123, task)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: update_calendar_event_time
# ---------------------------------------------------------------------------

class TestUpdateCalendarEventTime:
    """Tests for update_calendar_event_time."""

    @pytest.mark.asyncio
    async def test_calls_events_patch_with_new_time(self):
        """update_calendar_event_time calls events().patch with updated time."""
        from bot.services.google_calendar import update_calendar_event_time

        new_time = datetime(2026, 5, 1, 16, 0, tzinfo=timezone.utc)
        task = _make_task(google_calendar_event_id="event-to-update")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_google_service_mock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_calendar._build_google_service",
            return_value=mock_service,
        ):
            await update_calendar_event_time(db, 123, task, new_time)

        mock_service.events.return_value.patch.assert_called_once()
        patch_call = mock_service.events.return_value.patch.call_args[1]
        assert patch_call["eventId"] == "event-to-update"
        assert "2026-05-01T16:00:00+00:00" in patch_call["body"]["start"]["dateTime"]

    @pytest.mark.asyncio
    async def test_skips_when_no_google_event_id(self):
        """update_calendar_event_time is no-op when task has no event_id."""
        from bot.services.google_calendar import update_calendar_event_time

        task = _make_task(google_calendar_event_id=None)
        db = MagicMock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ) as mock_token:
            await update_calendar_event_time(db, 123, task, datetime.now(tz=timezone.utc))

        # Should have returned early without calling get_valid_token
        mock_token.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: complete_calendar_event
# ---------------------------------------------------------------------------

class TestCompleteCalendarEvent:
    """Tests for complete_calendar_event."""

    @pytest.mark.asyncio
    async def test_calls_patch_with_green_color_and_checkmark(self):
        """complete_calendar_event patches event with colorId='2' and ✅ prefix."""
        from bot.services.google_calendar import complete_calendar_event

        task = _make_task(content="Kupić mleko", google_calendar_event_id="evt-001")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_google_service_mock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_calendar._build_google_service",
            return_value=mock_service,
        ):
            await complete_calendar_event(db, 123, task)

        mock_service.events.return_value.patch.assert_called_once()
        patch_call = mock_service.events.return_value.patch.call_args[1]
        assert patch_call["eventId"] == "evt-001"
        assert patch_call["body"]["colorId"] == "2"
        assert patch_call["body"]["summary"].startswith("✅")

    @pytest.mark.asyncio
    async def test_skips_when_no_google_event_id(self):
        """complete_calendar_event is no-op when task has no event_id."""
        from bot.services.google_calendar import complete_calendar_event

        task = _make_task(google_calendar_event_id=None)
        db = MagicMock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ) as mock_token:
            await complete_calendar_event(db, 123, task)

        mock_token.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: delete_calendar_event
# ---------------------------------------------------------------------------

class TestDeleteCalendarEvent:
    """Tests for delete_calendar_event."""

    @pytest.mark.asyncio
    async def test_calls_events_delete(self):
        """delete_calendar_event calls events().delete with correct event_id."""
        from bot.services.google_calendar import delete_calendar_event

        task = _make_task(google_calendar_event_id="evt-to-delete")

        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        mock_service = _make_google_service_mock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ), patch(
            "bot.services.google_calendar._build_google_service",
            return_value=mock_service,
        ):
            await delete_calendar_event(db, 123, task)

        mock_service.events.return_value.delete.assert_called_once()
        delete_call = mock_service.events.return_value.delete.call_args[1]
        assert delete_call["eventId"] == "evt-to-delete"

    @pytest.mark.asyncio
    async def test_skips_when_no_google_event_id(self):
        """delete_calendar_event is no-op when task has no event_id."""
        from bot.services.google_calendar import delete_calendar_event

        task = _make_task(google_calendar_event_id=None)
        db = MagicMock()

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value="valid-token"),
        ) as mock_token:
            await delete_calendar_event(db, 123, task)

        mock_token.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_gracefully_when_user_has_no_google(self):
        """delete_calendar_event → no error when user not connected."""
        from bot.services.google_calendar import delete_calendar_event

        task = _make_task(google_calendar_event_id="evt-001")
        db = MagicMock()
        user_doc = AsyncMock()
        user_doc.exists = True
        user_doc.to_dict = MagicMock(return_value={"google_calendar_id": "primary"})
        user_doc_ref = AsyncMock()
        user_doc_ref.get = AsyncMock(return_value=user_doc)
        db.collection.return_value.document.return_value = user_doc_ref

        with patch(
            "bot.services.google_calendar.get_valid_token",
            new=AsyncMock(return_value=None),
        ):
            # Should not raise
            await delete_calendar_event(db, 123, task)
