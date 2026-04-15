"""Inline button callback handlers — snooze, done, reject, confirm, change_time."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from bot.models.task import Task, TaskState
from bot.models.user import User
from bot.services.scheduler import cancel_reminder, schedule_reminder, snooze_reminder

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"


async def _answer_callback_query(callback_query_id: str, text: str = "") -> None:
    """Always answer the callback query to remove the loading spinner."""
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_BASE_URL}/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def _edit_message_reply_markup(
    chat_id: int,
    message_id: int,
    reply_markup: Optional[dict] = None,
) -> bool:
    """Try to edit message reply markup. Returns False if edit fails."""
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    else:
        payload["reply_markup"] = {"inline_keyboard": []}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{TELEGRAM_BASE_URL}/bot{token}/editMessageReplyMarkup",
                json=payload,
            )
            return resp.status_code == 200
    except Exception as exc:
        logger.warning("Failed to edit message reply markup: %s", exc)
        return False


async def _send_message(chat_id: int, text: str, reply_markup: Optional[dict] = None) -> dict:
    """Send a new Telegram message (fallback when edit fails)."""
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{TELEGRAM_BASE_URL}/bot{token}/sendMessage", json=payload)
        resp.raise_for_status()
        return resp.json()


async def _get_task(db, task_id: str) -> Optional[Task]:
    task_doc = await db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        return None
    return Task.from_firestore_dict(task_doc.to_dict())


async def _get_user(db, user_id: int) -> Optional[User]:
    user_doc = await db.collection("users").document(str(user_id)).get()
    if not user_doc.exists:
        return None
    return User.from_firestore_dict(user_doc.to_dict())


async def handle_confirm_callback(
    callback_query: dict,
    task_id: str,
    db,
) -> None:
    """Handle [✓ OK] — schedule the task."""
    cq_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(cq_id)

    task = await _get_task(db, task_id)
    if task is None:
        await _send_message(chat_id, "Zadanie nie znalezione.")
        return

    if task.state != TaskState.PENDING_CONFIRMATION:
        # Already processed — idempotent
        logger.info("confirm: task %s not in PENDING_CONFIRMATION, skipping", task_id)
        return

    # Determine fire_at
    fire_at = task.proposed_time or datetime.now(tz=timezone.utc) + timedelta(hours=1)

    # Transition to SCHEDULED
    task.transition(TaskState.SCHEDULED)
    task.scheduled_time = fire_at

    # Schedule Cloud Task
    ct_name = await schedule_reminder(task_id=task_id, fire_at=fire_at)
    task.cloud_task_name = ct_name
    await task.save(db)

    # Remove buttons from message
    edit_ok = await _edit_message_reply_markup(chat_id, message_id)
    if not edit_ok:
        user = await _get_user(db, user_id)
        tz_name = user.timezone if user else "Europe/Warsaw"
        tz = ZoneInfo(tz_name)
        time_str = fire_at.astimezone(tz).strftime("%d.%m.%Y %H:%M")
        await _send_message(
            chat_id,
            f"✅ Zapisano! Przypomnę Ci o <b>{task.content}</b> o <b>{time_str}</b>.",
        )


async def handle_change_time_callback(
    callback_query: dict,
    task_id: str,
    db,
) -> None:
    """Handle [Zmień czas] — enter awaiting_time_input conversation state."""
    cq_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]

    await _answer_callback_query(cq_id)

    user = await _get_user(db, user_id)
    if user is None:
        user = await User.get_or_create(db, telegram_user_id=user_id)

    # Set conversation state
    user.conversation_state = "awaiting_time_input"
    user.conversation_state_expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
    await user.save(db)

    await _send_message(
        chat_id,
        "⏰ Podaj nowy czas, np.:\n"
        "• jutro o 17\n"
        "• za 2 godziny\n"
        "• w piątek o 10:30",
    )


async def handle_snooze_callback(
    callback_query: dict,
    snooze_type: str,
    task_id: str,
    db,
) -> None:
    """Handle snooze callbacks: 30m, 2h, morning."""
    cq_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(cq_id)

    task = await _get_task(db, task_id)
    if task is None:
        return

    # Idempotency: only snooze if in snoozeable state
    if task.state not in (TaskState.REMINDED, TaskState.NUDGED):
        logger.info("snooze: task %s in state %s, skipping", task_id, task.state)
        return

    user = await _get_user(db, user_id)
    tz_name = user.timezone if user else "Europe/Warsaw"

    now = datetime.now(tz=timezone.utc)

    if snooze_type == "30m":
        new_fire_at = now + timedelta(minutes=30)
    elif snooze_type == "2h":
        new_fire_at = now + timedelta(hours=2)
    elif snooze_type == "morning":
        if user and user.morning_time:
            # Schedule for tomorrow at morning_time
            tz = ZoneInfo(tz_name)
            local_now = now.astimezone(tz)
            tomorrow = local_now.date() + timedelta(days=1)
            h, m = map(int, user.morning_time.split(":"))
            morning_local = datetime(
                tomorrow.year, tomorrow.month, tomorrow.day, h, m, tzinfo=tz
            )
            new_fire_at = morning_local.astimezone(timezone.utc)
        else:
            # R9 flow: ask for morning time
            if user:
                user.conversation_state = "awaiting_morning_time"
                user.conversation_state_expires_at = now + timedelta(minutes=10)
                await user.save(db)
            await _send_message(
                chat_id,
                "🌅 O której godzinie masz zazwyczaj poranek?\n"
                "Np. 07:30 lub 08:00\n\n"
                "Zapamiętam to dla następnych \"jutro rano\" przypomnień.",
            )
            return
    else:
        logger.warning("Unknown snooze type: %s", snooze_type)
        return

    # Transition task
    task.transition(TaskState.SNOOZED)

    # Cancel nudge if any
    await cancel_reminder(task.nudge_task_name)
    task.nudge_task_name = None

    # Snooze: cancel old + create new reminder
    new_ct_name = await snooze_reminder(task_id, task.cloud_task_name, new_fire_at, db)
    task.cloud_task_name = new_ct_name
    await task.save(db)

    # Edit message to remove buttons
    edit_ok = await _edit_message_reply_markup(chat_id, message_id)

    tz = ZoneInfo(tz_name)
    time_str = new_fire_at.astimezone(tz).strftime("%d.%m %H:%M")
    confirm_text = f"⏰ Przekładam na: <b>{time_str}</b>"

    if not edit_ok:
        await _send_message(chat_id, confirm_text)


async def handle_done_callback(
    callback_query: dict,
    task_id: str,
    db,
) -> None:
    """Handle [✓ Zrobione] — mark task as COMPLETED."""
    cq_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(cq_id, "✓ Świetnie!")

    task = await _get_task(db, task_id)
    if task is None:
        return

    # Idempotency: if already completed, just answer callback (no error)
    if task.state == TaskState.COMPLETED:
        logger.info("done: task %s already COMPLETED (idempotent)", task_id)
        return

    if task.state not in (TaskState.REMINDED, TaskState.NUDGED):
        logger.info("done: task %s in state %s, cannot complete", task_id, task.state)
        return

    # Cancel nudge
    await cancel_reminder(task.nudge_task_name)
    task.nudge_task_name = None

    # Transition
    task.transition(TaskState.COMPLETED)
    await task.save(db)

    # Edit message to remove buttons
    edit_ok = await _edit_message_reply_markup(chat_id, message_id)
    if not edit_ok:
        await _send_message(chat_id, f"✅ Zadanie \"<b>{task.content}</b>\" ukończone! Świetna robota! 🎉")


async def handle_reject_callback(
    callback_query: dict,
    task_id: str,
    db,
) -> None:
    """Handle [✗ Odrzuć] — mark task as REJECTED."""
    cq_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    message_id = callback_query["message"]["message_id"]

    await _answer_callback_query(cq_id)

    task = await _get_task(db, task_id)
    if task is None:
        return

    if task.state == TaskState.REJECTED:
        logger.info("reject: task %s already REJECTED (idempotent)", task_id)
        return

    if task.state not in (TaskState.REMINDED, TaskState.NUDGED):
        return

    # Cancel nudge
    await cancel_reminder(task.nudge_task_name)
    task.nudge_task_name = None

    task.transition(TaskState.REJECTED)
    await task.save(db)

    edit_ok = await _edit_message_reply_markup(chat_id, message_id)
    if not edit_ok:
        await _send_message(chat_id, f"✗ Zadanie \"<b>{task.content}</b>\" odrzucone.")


async def dispatch_callback(callback_query: dict, db) -> None:
    """Route callback_query to appropriate handler based on callback_data."""
    from bot.handlers.checklist_callbacks import (
        handle_checklist_attach_callback,
        handle_checklist_create_callback,
        handle_checklist_item_callback,
        handle_checklist_snooze_callback,
    )
    from bot.handlers.checklist_command_handlers import handle_checklist_delete_callback
    from bot.handlers.gdpr_handler import (
        handle_gdpr_cancel_callback,
        handle_gdpr_confirm_callback,
    )

    data = callback_query.get("data", "")
    parts = data.split(":", maxsplit=2)
    action = parts[0]

    if action == "confirm" and len(parts) == 2:
        await handle_confirm_callback(callback_query, parts[1], db)
    elif action == "change_time" and len(parts) == 2:
        await handle_change_time_callback(callback_query, parts[1], db)
    elif action == "snooze" and len(parts) == 3:
        await handle_snooze_callback(callback_query, parts[1], parts[2], db)
    elif action == "done" and len(parts) == 2:
        await handle_done_callback(callback_query, parts[1], db)
    elif action == "reject" and len(parts) == 2:
        await handle_reject_callback(callback_query, parts[1], db)
    elif action == "checklist_item":
        await handle_checklist_item_callback(callback_query, db)
    elif action == "checklist_snooze":
        await handle_checklist_snooze_callback(callback_query, db)
    elif action == "checklist_delete":
        await handle_checklist_delete_callback(callback_query, db)
    elif action == "checklist_attach":
        await handle_checklist_attach_callback(callback_query, db)
    elif action == "checklist_create":
        await handle_checklist_create_callback(callback_query, db)
    elif action == "gdpr_confirm_delete":
        await handle_gdpr_confirm_callback(callback_query, db)
    elif action == "gdpr_cancel_delete":
        await handle_gdpr_cancel_callback(callback_query, db)
    else:
        logger.warning("Unknown callback action: %s", data)
