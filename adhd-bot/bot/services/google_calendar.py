"""Google Calendar integration — unit-directional sync (bot → Calendar).

Functions:
- create_calendar_event(user_id, task) → event_id | None
- update_calendar_event_time(user_id, task, new_time) → None
- complete_calendar_event(user_id, task) → None
- delete_calendar_event(user_id, task) → None

All functions are graceful no-ops when user has no Google connection.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from bot.services.google_auth import get_valid_token

logger = logging.getLogger(__name__)

_EVENT_DURATION_MINUTES = 30
_COMPLETED_COLOR_ID = "2"  # Google Calendar color: sage/green
_COMPLETED_PREFIX = "✅ "


def _build_google_service(access_token: str):
    """Build Google API resource object for Calendar.

    Uses google-api-python-client (already in requirements.txt).
    """
    import httplib2
    from googleapiclient.discovery import build  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore

    creds = Credentials(token=access_token)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service


def _format_event_datetime(dt: datetime) -> dict:
    """Format datetime for Google Calendar event start/end."""
    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return {"dateTime": dt.isoformat(), "timeZone": "UTC"}


async def create_calendar_event(db, telegram_user_id: int, task) -> Optional[str]:
    """Create a Google Calendar event for a scheduled task.

    Returns the event_id on success, None if user has no Google or on error.
    Saves google_calendar_event_id to the task document in Firestore.
    """
    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return None

    if not task.scheduled_time:
        logger.debug("Task %s has no scheduled_time — skipping calendar event", task.task_id)
        return None

    # Fetch user's calendar ID
    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return None

    user_data = user_doc.to_dict()
    calendar_id = user_data.get("google_calendar_id", "primary")

    scheduled_time = task.scheduled_time
    end_time = scheduled_time + timedelta(minutes=_EVENT_DURATION_MINUTES)

    event_body = {
        "summary": task.content,
        "description": "Zadanie z ADHD Bot",
        "start": _format_event_datetime(scheduled_time),
        "end": _format_event_datetime(end_time),
    }

    try:
        service = _build_google_service(access_token)
        event = await asyncio.to_thread(
            service.events().insert(calendarId=calendar_id, body=event_body).execute
        )
        event_id: str = event.get("id", "")

        if event_id:
            # Save event_id to task document
            task_doc_ref = db.collection("tasks").document(task.task_id)
            await task_doc_ref.update({"google_calendar_event_id": event_id})
            task.google_calendar_event_id = event_id
            logger.info(
                "Created Calendar event %s for task %s", event_id, task.task_id
            )

        return event_id or None

    except Exception as exc:
        logger.error(
            "Failed to create Calendar event for task %s: %s", task.task_id, exc
        )
        return None


async def update_calendar_event_time(
    db, telegram_user_id: int, task, new_time: datetime
) -> None:
    """Update the start/end time of a Calendar event (used on snooze)."""
    if not task.google_calendar_event_id:
        return

    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return

    user_data = user_doc.to_dict()
    calendar_id = user_data.get("google_calendar_id", "primary")

    end_time = new_time + timedelta(minutes=_EVENT_DURATION_MINUTES)

    patch_body = {
        "start": _format_event_datetime(new_time),
        "end": _format_event_datetime(end_time),
    }

    try:
        service = _build_google_service(access_token)
        await asyncio.to_thread(
            service.events().patch(
                calendarId=calendar_id,
                eventId=task.google_calendar_event_id,
                body=patch_body,
            ).execute
        )
        logger.info(
            "Updated Calendar event %s time to %s", task.google_calendar_event_id, new_time
        )
    except Exception as exc:
        logger.error(
            "Failed to update Calendar event %s: %s",
            task.google_calendar_event_id,
            exc,
        )


async def complete_calendar_event(db, telegram_user_id: int, task) -> None:
    """Mark Calendar event as completed (green color + ✅ prefix in summary)."""
    if not task.google_calendar_event_id:
        return

    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return

    user_data = user_doc.to_dict()
    calendar_id = user_data.get("google_calendar_id", "primary")

    summary = task.content or ""
    if not summary.startswith(_COMPLETED_PREFIX):
        summary = f"{_COMPLETED_PREFIX}{summary}"

    patch_body = {
        "colorId": _COMPLETED_COLOR_ID,
        "summary": summary,
    }

    try:
        service = _build_google_service(access_token)
        await asyncio.to_thread(
            service.events().patch(
                calendarId=calendar_id,
                eventId=task.google_calendar_event_id,
                body=patch_body,
            ).execute
        )
        logger.info("Marked Calendar event %s as completed", task.google_calendar_event_id)
    except Exception as exc:
        logger.error(
            "Failed to complete Calendar event %s: %s",
            task.google_calendar_event_id,
            exc,
        )


async def delete_calendar_event(db, telegram_user_id: int, task) -> None:
    """Delete a Calendar event (used when task is rejected)."""
    if not task.google_calendar_event_id:
        return

    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return

    user_data = user_doc.to_dict()
    calendar_id = user_data.get("google_calendar_id", "primary")

    try:
        service = _build_google_service(access_token)
        await asyncio.to_thread(
            service.events().delete(
                calendarId=calendar_id,
                eventId=task.google_calendar_event_id,
            ).execute
        )
        logger.info("Deleted Calendar event %s", task.google_calendar_event_id)
    except Exception as exc:
        logger.error(
            "Failed to delete Calendar event %s: %s",
            task.google_calendar_event_id,
            exc,
        )
