"""Command handlers for checklist management: /new_checklist, /checklists, /evening."""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Optional

from bot.models.checklist import (
    ChecklistTemplate,
    ChecklistValidationError,
    MAX_CHECKLIST_ITEMS,
)
from bot.models.user import User

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"
TIME_REGEX = re.compile(r"^(\d{2}):(\d{2})$")


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


def _validate_evening_time(time_str: str) -> bool:
    """Validate HH:MM format with 00-23:00-59 range."""
    match = TIME_REGEX.match(time_str)
    if not match:
        return False
    hour, minute = int(match.group(1)), int(match.group(2))
    return 0 <= hour <= 23 and 0 <= minute <= 59


async def handle_new_checklist(message: dict, db) -> None:
    """Handle /new_checklist command -- create a new checklist template with AI suggestions."""
    from bot.services.checklist_ai import suggest_items

    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await _send_message(
            chat_id,
            "Uzycie: /new_checklist Nazwa\n"
            "Przyklad: /new_checklist Silownia",
        )
        return

    template_name = parts[1].strip()

    # Get AI suggestions
    suggested_items = await suggest_items(template_name)

    if not suggested_items:
        suggested_items = []

    # Create template
    template = ChecklistTemplate(
        user_id=user_id,
        name=template_name,
        items=suggested_items,
    )

    try:
        await template.save(db)
    except ChecklistValidationError as exc:
        await _send_message(chat_id, f"Blad: {exc}")
        return

    # Build response
    if suggested_items:
        items_text = "\n".join(f"{i+1}. {item}" for i, item in enumerate(suggested_items))
        response_text = (
            f"Proponuje taka liste dla '<b>{template_name}</b>':\n\n"
            f"{items_text}\n\n"
            f"Szablon zapisany! Mozesz go zobaczyc przez /checklists"
        )
    else:
        response_text = (
            f"Szablon '<b>{template_name}</b>' zostal utworzony (pusty).\n\n"
            f"Dodaj elementy przez /checklists"
        )

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Usun", "callback_data": f"checklist_delete:{template.template_id}"},
            ]
        ]
    }

    await _send_message(chat_id, response_text, reply_markup=keyboard)


async def handle_checklists(message: dict, db) -> None:
    """Handle /checklists command -- list user's checklist templates."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    # Query templates for this user
    query = db.collection("checklist_templates").where("user_id", "==", user_id)
    docs = await query.get()

    if not docs:
        await _send_message(chat_id, "Nie masz jeszcze zadnych list.\n\nUzyj /new_checklist Nazwa aby stworzyc pierwsza.")
        return

    templates = [ChecklistTemplate.from_firestore_dict(doc.to_dict()) for doc in docs]

    lines = ["<b>Twoje listy:</b>\n"]
    buttons = []
    for tmpl in templates:
        item_count = len(tmpl.items)
        lines.append(f"- {tmpl.name} ({item_count} elementow)")
        buttons.append([
            {"text": f"Usun {tmpl.name}", "callback_data": f"checklist_delete:{tmpl.template_id}"},
        ])

    keyboard = {"inline_keyboard": buttons} if buttons else None
    await _send_message(chat_id, "\n".join(lines), reply_markup=keyboard)


async def handle_evening(message: dict, db) -> None:
    """Handle /evening command -- set evening reminder time."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await _send_message(
            chat_id,
            "Uzycie: /evening 21:00\n"
            "Podaj godzine w formacie HH:MM (np. 20:30, 21:00)",
        )
        return

    time_str = parts[1].strip()
    if not _validate_evening_time(time_str):
        await _send_message(
            chat_id,
            f"Nieprawidlowa godzina: <b>{time_str}</b>\n\n"
            "Uzyj formatu HH:MM, np. 20:30, 21:00\n"
            "Godziny: 00-23, minuty: 00-59",
        )
        return

    user = await User.get_or_create(db, telegram_user_id=user_id)
    user.evening_time = time_str
    await user.save(db)

    await _send_message(
        chat_id,
        f"Godzina wieczornego przypomnienia ustawiona na: <b>{time_str}</b>",
    )


async def handle_checklist_delete_callback(callback_query: dict, db) -> None:
    """Handle callback for deleting a checklist template."""
    callback_data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]

    # Answer callback immediately
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_BASE_URL}/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )

    # Extract template_id
    parts = callback_data.split(":")
    if len(parts) < 2:
        return

    template_id = parts[1]

    # Load template
    doc_ref = db.collection("checklist_templates").document(template_id)
    doc = await doc_ref.get()
    if not doc.exists:
        await _send_message(chat_id, "Szablon nie istnieje lub zostal juz usuniety.")
        return

    template_data = doc.to_dict()

    # Verify ownership (P2-1): only the template owner can delete it
    if template_data.get("user_id") != user_id:
        await _send_message(chat_id, "Brak uprawnien do usuniecia tego szablonu.")
        return

    await doc_ref.delete()
    template_name = template_data.get("name", "szablon")

    await _send_message(chat_id, f"Szablon '<b>{template_name}</b>' zostal usuniety.")
