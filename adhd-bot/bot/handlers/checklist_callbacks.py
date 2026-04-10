"""Checklist item callback handlers — check items, snooze list."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bot.models.checklist import ChecklistSession

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
    except Exception as exc:
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
    """Build checklist message text and keyboard from session state."""
    lines = [f"<b>{session.template_name}</b>\n"]

    for i, item in enumerate(session.items):
        if item.checked:
            lines.append(f"  {item.text}")
        else:
            lines.append(f"[ ] {item.text}")

    text = "\n".join(lines)

    # Build keyboard with unchecked items as buttons
    item_buttons = []
    for i, item in enumerate(session.items):
        if not item.checked:
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
    """Handle callback for checking/unchecking a checklist item."""
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

    # Load session
    doc_ref = db.collection("checklist_sessions").document(session_id)
    doc = await doc_ref.get()
    if not doc.exists:
        return

    session = ChecklistSession.from_firestore_dict(doc.to_dict())

    # Check bounds
    if item_index < 0 or item_index >= len(session.items):
        return

    # Mark item as checked
    session.items[item_index].checked = True
    await session.save(db)

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
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to snooze checklist %s: %s", session_id, exc)

    snooze_text = "Przypomne za 30 min"
    await _edit_message_text(chat_id, message_id, snooze_text)
