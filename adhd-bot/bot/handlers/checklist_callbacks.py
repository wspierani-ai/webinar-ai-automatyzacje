"""Checklist item callback handlers — check/uncheck items, snooze list, attach/create."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from google.cloud.exceptions import GoogleCloudError

from bot.models.checklist import ChecklistItem, ChecklistSession, ChecklistTemplate

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"


async def _answer_callback_query(callback_query_id: str, text: str = "") -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_BASE_URL}/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def _edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
) -> bool:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    else:
        payload["reply_markup"] = {"inline_keyboard": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_BASE_URL}/bot{token}/editMessageText",
                json=payload,
            )
            resp.raise_for_status()
            return True
    except httpx.HTTPError as exc:
        logger.warning("Failed to edit checklist message: %s", exc)
        return False


async def _send_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
) -> dict:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


def _build_checklist_message(session: ChecklistSession) -> tuple[str, dict]:
    """Build checklist message text and keyboard from session state.

    Shows buttons for all items: unchecked items get a plain label,
    checked items get a checkmark prefix. Clicking toggles the state (P2-4).
    """
    lines = [f"<b>{session.template_name}</b>\n"]

    for i, item in enumerate(session.items):
        if item.checked:
            lines.append(f"  {item.text}")
        else:
            lines.append(f"[ ] {item.text}")

    text = "\n".join(lines)

    # Build keyboard with ALL items as buttons (toggle support)
    item_buttons = []
    for i, item in enumerate(session.items):
        if item.checked:
            item_buttons.append(
                {"text": f"\u2705 {item.text}", "callback_data": f"checklist_item:{session.session_id}:{i}"}
            )
        else:
            item_buttons.append(
                {"text": f"{item.text}", "callback_data": f"checklist_item:{session.session_id}:{i}"}
            )

    # Arrange buttons in rows of 2
    keyboard_rows = []
    for idx in range(0, len(item_buttons), 2):
        keyboard_rows.append(item_buttons[idx:idx + 2])

    # Add snooze row
    keyboard_rows.append([
        {"text": "+30 min", "callback_data": f"checklist_snooze:30m:{session.session_id}"},
    ])

    return text, {"inline_keyboard": keyboard_rows}


async def handle_checklist_item_callback(callback_query: dict, db) -> None:
    """Handle callback for toggling a checklist item (check/uncheck).

    Uses Firestore transaction for atomic read-modify-write to prevent
    race conditions from rapid concurrent clicks (P1-3).
    """
    callback_data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(callback_query_id)

    # Parse: checklist_item:{session_id}:{item_index}
    parts = callback_data.split(":")
    if len(parts) < 3:
        return

    session_id = parts[1]
    try:
        item_index = int(parts[2])
    except ValueError:
        return

    doc_ref = db.collection("checklist_sessions").document(session_id)

    # Atomic read-modify-write inside a Firestore transaction
    transaction = db.transaction()
    session = await _toggle_item_in_transaction(transaction, doc_ref, item_index)

    if session is None:
        return

    # Check if all items are now checked
    if session.all_checked:
        session.state = "completed"
        await session.save(db)

        completion_text = f"Wszystko gotowe! {session.template_name} czeka"
        await _edit_message_text(chat_id, message_id, completion_text)
        return

    # Update message with current state
    text, keyboard = _build_checklist_message(session)
    await _edit_message_text(chat_id, message_id, text, reply_markup=keyboard)


async def _toggle_item_in_transaction(transaction, doc_ref, item_index: int) -> Optional[ChecklistSession]:
    """Toggle item checked state inside a Firestore transaction.

    Returns the updated session, or None if doc doesn't exist or index is out of bounds.
    """
    doc = await doc_ref.get(transaction=transaction)
    if not doc.exists:
        return None

    session = ChecklistSession.from_firestore_dict(doc.to_dict())

    if item_index < 0 or item_index >= len(session.items):
        return None

    # Toggle: checked -> unchecked, unchecked -> checked (P2-4)
    session.items[item_index].checked = not session.items[item_index].checked

    transaction.set(doc_ref, session.to_firestore_dict())
    return session


async def handle_checklist_snooze_callback(callback_query: dict, db) -> None:
    """Handle callback for snoozing the entire checklist."""
    callback_data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(callback_query_id)

    # Parse: checklist_snooze:30m:{session_id}
    parts = callback_data.split(":")
    if len(parts) < 3:
        return

    session_id = parts[2]

    # Load session
    doc_ref = db.collection("checklist_sessions").document(session_id)
    doc = await doc_ref.get()
    if not doc.exists:
        return

    session = ChecklistSession.from_firestore_dict(doc.to_dict())

    # Schedule new Cloud Task for 30 min
    new_fire_at = datetime.now(tz=timezone.utc) + timedelta(minutes=30)

    try:
        from bot.services.scheduler import cancel_reminder, schedule_checklist_trigger

        # Cancel existing morning task if any
        if session.cloud_task_name_morning:
            await cancel_reminder(session.cloud_task_name_morning)

        new_ct_name = await schedule_checklist_trigger(
            session_id=session.session_id,
            trigger_type="morning",
            fire_at=new_fire_at,
        )
        session.cloud_task_name_morning = new_ct_name
        session.morning_reminder_time = new_fire_at
        await session.save(db)
    except GoogleCloudError as exc:
        logger.error("Failed to snooze checklist %s: %s", session_id, exc)

    snooze_text = "Przypomne za 30 min"
    await _edit_message_text(chat_id, message_id, snooze_text)


async def handle_checklist_attach_callback(callback_query: dict, db) -> None:
    """Handle callback for attaching a checklist template to a task.

    Callback data format: checklist_attach:{task_id}:{template_id}
    Creates a checklist session from the template, linked to the task's proposed time.
    """
    callback_data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(callback_query_id)

    # Parse: checklist_attach:{task_id}:{template_id}
    parts = callback_data.split(":")
    if len(parts) < 3:
        return

    task_id = parts[1]
    template_id = parts[2]

    # Load the task to get event time
    from bot.models.task import Task

    task_doc = await db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        await _send_message(chat_id, "Zadanie nie znalezione.")
        return

    task = Task.from_firestore_dict(task_doc.to_dict())
    event_time = task.proposed_time or (datetime.now(tz=timezone.utc) + timedelta(days=1))

    # Load template
    template_doc = await db.collection("checklist_templates").document(template_id).get()
    if not template_doc.exists:
        await _send_message(chat_id, "Szablon nie znaleziony.")
        return

    template = ChecklistTemplate.from_firestore_dict(template_doc.to_dict())

    # Load user for timezone/evening/morning settings
    from bot.models.user import User

    user = await User.get_or_create(db, telegram_user_id=user_id)

    # Create session
    from bot.services.checklist_session import create_session

    session = await create_session(
        db=db,
        user_id=user_id,
        template=template,
        event_time=event_time,
        user_timezone=user.timezone,
        evening_time_str=user.evening_time,
        morning_time_str=user.morning_time,
    )

    # Confirm the task as well
    from bot.models.task import TaskState
    from bot.services.scheduler import schedule_reminder

    if task.state == TaskState.PENDING_CONFIRMATION:
        task.transition(TaskState.SCHEDULED)
        task.scheduled_time = event_time
        ct_name = await schedule_reminder(task_id=task_id, fire_at=event_time)
        task.cloud_task_name = ct_name
        await task.save(db)

    items_text = "\n".join(f"[ ] {item.text}" for item in session.items)
    response_text = (
        f"Lista '<b>{template.name}</b>' dolaczona!\n\n"
        f"{items_text}\n\n"
        f"Przypomnę wieczorem i rano."
    )
    await _edit_message_text(chat_id, message_id, response_text)


async def handle_checklist_create_callback(callback_query: dict, db) -> None:
    """Handle callback for creating a new checklist for a task.

    Callback data format: checklist_create:{task_id}
    Prompts user to create a checklist via /new_checklist, then confirms the task.
    """
    callback_data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(callback_query_id)

    # Parse: checklist_create:{task_id}
    parts = callback_data.split(":")
    if len(parts) < 2:
        return

    task_id = parts[1]

    # Confirm the task
    from bot.models.task import Task, TaskState
    from bot.services.scheduler import schedule_reminder

    task_doc = await db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        await _send_message(chat_id, "Zadanie nie znalezione.")
        return

    task = Task.from_firestore_dict(task_doc.to_dict())
    event_time = task.proposed_time or (datetime.now(tz=timezone.utc) + timedelta(days=1))

    if task.state == TaskState.PENDING_CONFIRMATION:
        task.transition(TaskState.SCHEDULED)
        task.scheduled_time = event_time
        ct_name = await schedule_reminder(task_id=task_id, fire_at=event_time)
        task.cloud_task_name = ct_name
        await task.save(db)

    response_text = (
        f"Zadanie zapisane!\n\n"
        f"Uzyj /new_checklist <nazwa> aby stworzyc liste.\n"
        f"Np. /new_checklist {task.content}"
    )
    await _edit_message_text(chat_id, message_id, response_text)
