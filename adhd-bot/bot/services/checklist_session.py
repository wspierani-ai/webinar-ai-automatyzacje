"""Checklist session service — create sessions, schedule evening/morning reminders."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from google.cloud.exceptions import GoogleCloudError

from bot.models.checklist import ChecklistItem, ChecklistSession, ChecklistTemplate

logger = logging.getLogger(__name__)


async def create_session(
    db,
    user_id: int,
    template: ChecklistTemplate,
    event_time: datetime,
    user_timezone: str = "Europe/Warsaw",
    evening_time_str: Optional[str] = None,
    morning_time_str: Optional[str] = None,
) -> ChecklistSession:
    """Create a ChecklistSession from a template with snapshot of items.

    Computes evening_reminder_time and morning_reminder_time based on user settings.
    Schedules two Cloud Tasks for evening and morning triggers.
    """
    tz = ZoneInfo(user_timezone)

    # Snapshot items from template
    items = [ChecklistItem(text=item_text) for item_text in template.items]

    # Compute evening reminder time: day before event_time at user's evening_time
    evening_hour, evening_min = 21, 0
    if evening_time_str:
        parts = evening_time_str.split(":")
        evening_hour, evening_min = int(parts[0]), int(parts[1])

    event_local = event_time.astimezone(tz)
    evening_date = event_local.date() - timedelta(days=1)
    evening_dt = datetime(
        evening_date.year, evening_date.month, evening_date.day,
        evening_hour, evening_min, 0,
        tzinfo=tz,
    ).astimezone(timezone.utc)

    # If evening time is already in the past, use event_time minus 12 hours as fallback
    now = datetime.now(tz=timezone.utc)
    if evening_dt < now:
        evening_dt = max(now + timedelta(minutes=1), event_time - timedelta(hours=12))

    # Compute morning reminder time: event day at user's morning_time
    morning_hour, morning_min = 8, 0
    if morning_time_str:
        parts = morning_time_str.split(":")
        morning_hour, morning_min = int(parts[0]), int(parts[1])

    morning_date = event_local.date()
    morning_dt = datetime(
        morning_date.year, morning_date.month, morning_date.day,
        morning_hour, morning_min, 0,
        tzinfo=tz,
    ).astimezone(timezone.utc)

    session = ChecklistSession(
        user_id=user_id,
        template_id=template.template_id,
        template_name=template.name,
        items=items,
        event_time=event_time,
        evening_reminder_time=evening_dt,
        morning_reminder_time=morning_dt,
        state="pending_evening",
    )

    await session.save(db)

    # Schedule Cloud Tasks for evening and morning triggers
    try:
        from bot.services.scheduler import schedule_checklist_trigger

        evening_ct_name = await schedule_checklist_trigger(
            session_id=session.session_id,
            trigger_type="evening",
            fire_at=evening_dt,
        )
        session.cloud_task_name_evening = evening_ct_name

        morning_ct_name = await schedule_checklist_trigger(
            session_id=session.session_id,
            trigger_type="morning",
            fire_at=morning_dt,
        )
        session.cloud_task_name_morning = morning_ct_name

        await session.save(db)
    except (GoogleCloudError, ValueError) as exc:
        logger.error("Failed to schedule checklist triggers for session %s: %s", session.session_id, exc)

    return session
