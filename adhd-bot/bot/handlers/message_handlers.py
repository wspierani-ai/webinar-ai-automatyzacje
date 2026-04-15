"""Message handlers for text and voice messages — task capture flow."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bot.models.task import Task, TaskState
from bot.models.user import User
from bot.services.ai_parser import parse_message, parse_voice_message

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"

BLOCKED_USER_TEXT = (
    "🔒 Twój dostęp do bota wygasł.\n\n"
    "Aby kontynuować korzystanie, odblokuj subskrypcję:\n"
    "/subscribe"
)

PARSE_FAILED_TEXT = (
    "😔 Nie udało mi się przetworzyć Twojej wiadomości głosowej.\n\n"
    "Spróbuj wysłać to samo jako tekst."
)


def _build_confirmation_keyboard(task_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✓ OK", "callback_data": f"confirm:{task_id}"},
                {"text": "Zmień czas", "callback_data": f"change_time:{task_id}"},
            ]
        ]
    }


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


async def _download_voice(file_id: str) -> bytes:
    """Download a voice file from Telegram and return its bytes."""
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    # Step 1: get file path
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{TELEGRAM_BASE_URL}/bot{token}/getFile",
            params={"file_id": file_id},
        )
        resp.raise_for_status()
        file_path = resp.json()["result"]["file_path"]

        # Step 2: download file
        file_resp = await client.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}"
        )
        file_resp.raise_for_status()
        return file_resp.content


def _compute_heuristic_time(user_timezone: str = "Europe/Warsaw") -> datetime:
    """Return a heuristic 'next occurrence' time: next same-day if before 17:00, else tomorrow."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(user_timezone)
    now = datetime.now(tz=tz)
    candidate = now.replace(hour=17, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


async def _find_matching_template(db, user_id: int, content: str) -> Optional[dict]:
    """Search user's checklist templates for a case-insensitive match against content keywords."""
    try:
        query = db.collection("checklist_templates").where("user_id", "==", user_id)
        docs = await query.get()
        if not docs:
            return None

        content_lower = content.lower()
        for doc in docs:
            data = doc.to_dict()
            template_name = data.get("name", "").lower()
            if template_name and template_name in content_lower:
                return data
        return None
    except Exception as exc:
        logger.warning("Failed to search checklist templates: %s", exc)
        return None


async def handle_text_message(message: dict, db) -> None:
    """Process a text message: parse → create pending task → confirm."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    # Load user and check subscription
    user = await User.get_or_create(db, telegram_user_id=user_id)
    if not user.is_subscription_active():
        await _send_message(chat_id, BLOCKED_USER_TEXT)
        return

    # Check conversation state (awaiting_time_input)
    if user.conversation_state == "awaiting_time_input":
        await _handle_time_input(message, user, db)
        return

    # Parse message with Gemini
    parsed = await parse_message(text, user_timezone=user.timezone, user_id=user_id)

    # Determine scheduled time
    if parsed.has_time:
        proposed_time = parsed.scheduled_time
    elif parsed.is_morning_snooze:
        proposed_time = None  # will use morning_time
    else:
        proposed_time = _compute_heuristic_time(user.timezone)

    content = parsed.content or text

    # Create task in PENDING_CONFIRMATION
    task = Task(
        task_id=str(uuid.uuid4()),
        telegram_user_id=user_id,
        content=content,
        state=TaskState.PENDING_CONFIRMATION,
        proposed_time=proposed_time,
        is_morning_snooze=parsed.is_morning_snooze,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    await task.save(db)

    # Check for event_with_preparation — offer checklist
    extra_keyboard_rows: list[list[dict]] = []
    if parsed.event_type == "event_with_preparation" and proposed_time:
        matching_template = await _find_matching_template(db, user_id, content)
        if matching_template:
            extra_keyboard_rows.append([
                {
                    "text": f"Dodaj liste {matching_template['name']}",
                    "callback_data": f"checklist_attach:{task.task_id}:{matching_template['template_id']}",
                },
                {"text": "Nie, tylko reminder", "callback_data": f"confirm:{task.task_id}"},
            ])
        else:
            extra_keyboard_rows.append([
                {"text": "Stworz liste", "callback_data": f"checklist_create:{task.task_id}"},
                {"text": "Nie", "callback_data": f"confirm:{task.task_id}"},
            ])

    # Send confirmation message
    if proposed_time:
        tz_name = user.timezone
        from zoneinfo import ZoneInfo
        local_time = proposed_time.astimezone(ZoneInfo(tz_name))
        time_str = local_time.strftime("%d.%m.%Y %H:%M")
        confirm_text = (
            f"<b>{content}</b>\n\n"
            f"Przypomne Ci: <b>{time_str}</b>\n\n"
            f"Czy to jest dobry czas?"
        )
    else:
        confirm_text = (
            f"<b>{content}</b>\n\n"
            f"Kiedy mam Ci o tym przypomniez?\n"
            f"Wcisnij OK aby wybrac domyslny czas lub Zmien czas."
        )

    keyboard = _build_confirmation_keyboard(task.task_id)
    if extra_keyboard_rows:
        keyboard["inline_keyboard"] = extra_keyboard_rows + keyboard["inline_keyboard"]

    await _send_message(
        chat_id,
        confirm_text,
        reply_markup=keyboard,
    )


async def handle_voice_message(message: dict, db) -> None:
    """Process a voice message: download → parse → identical flow as text."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    voice = message.get("voice", {})
    file_id = voice.get("file_id", "")

    # Load user and check subscription
    user = await User.get_or_create(db, telegram_user_id=user_id)
    if not user.is_subscription_active():
        await _send_message(chat_id, BLOCKED_USER_TEXT)
        return

    # Download and parse voice
    try:
        audio_bytes = await _download_voice(file_id)
        parsed = await parse_voice_message(audio_bytes, user_timezone=user.timezone)
    except Exception as exc:
        logger.error("Voice message processing failed: %s", exc)
        await _send_message(chat_id, PARSE_FAILED_TEXT)
        return

    if not parsed.content:
        await _send_message(chat_id, PARSE_FAILED_TEXT)
        return

    # Same flow as text from here
    if parsed.has_time:
        proposed_time = parsed.scheduled_time
    elif parsed.is_morning_snooze:
        proposed_time = None
    else:
        proposed_time = _compute_heuristic_time(user.timezone)

    task = Task(
        task_id=str(uuid.uuid4()),
        telegram_user_id=user_id,
        content=parsed.content,
        state=TaskState.PENDING_CONFIRMATION,
        proposed_time=proposed_time,
        is_morning_snooze=parsed.is_morning_snooze,
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    await task.save(db)

    if proposed_time:
        from zoneinfo import ZoneInfo
        local_time = proposed_time.astimezone(ZoneInfo(user.timezone))
        time_str = local_time.strftime("%d.%m.%Y %H:%M")
        confirm_text = (
            f"📝 <b>{parsed.content}</b>\n\n"
            f"⏰ Przypomnę Ci: <b>{time_str}</b>\n\n"
            f"Czy to jest dobry czas?"
        )
    else:
        confirm_text = (
            f"📝 <b>{parsed.content}</b>\n\n"
            f"⏰ Kiedy mam Ci o tym przypomnieć?"
        )

    await _send_message(
        chat_id,
        confirm_text,
        reply_markup=_build_confirmation_keyboard(task.task_id),
    )


async def _handle_time_input(message: dict, user: User, db) -> None:
    """Handle user providing a new time when in awaiting_time_input conversation state."""
    from zoneinfo import ZoneInfo

    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    # Find the pending task that triggered the time change
    # (stored in conversation_state_context or as latest PENDING_CONFIRMATION task)
    # For simplicity: query the latest PENDING_CONFIRMATION task for this user
    tasks_query = (
        db.collection("tasks")
        .where("telegram_user_id", "==", user_id)
        .where("state", "==", TaskState.PENDING_CONFIRMATION.value)
        .order_by("created_at", direction="DESCENDING")
        .limit(1)
    )
    docs = await tasks_query.get()
    if not docs:
        await _send_message(chat_id, "Nie znalazłem zadania do aktualizacji. Spróbuj wysłać nową wiadomość.")
        return

    task_doc = docs[0]
    task = Task.from_firestore_dict(task_doc.to_dict())

    # Parse the new time input
    parsed = await parse_message(text, user_timezone=user.timezone)

    if parsed.has_time:
        task.proposed_time = parsed.scheduled_time
        await task.save(db)

        tz = ZoneInfo(user.timezone)
        local_time = parsed.scheduled_time.astimezone(tz)
        time_str = local_time.strftime("%d.%m.%Y %H:%M")
        await _send_message(
            chat_id,
            f"✅ Zaktualizowano czas na: <b>{time_str}</b>",
            reply_markup=_build_confirmation_keyboard(task.task_id),
        )
    else:
        await _send_message(
            chat_id,
            "⚠️ Nie rozumiem podanego czasu. Spróbuj ponownie, np.:\n"
            "• jutro o 17\n"
            "• za 2 godziny\n"
            "• w piątek o 10",
        )
        return

    # Clear conversation state
    user.conversation_state = None
    user.conversation_state_expires_at = None
    await user.save(db)
