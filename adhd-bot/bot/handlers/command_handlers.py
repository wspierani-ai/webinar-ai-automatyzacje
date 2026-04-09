"""Command handlers: /start, /timezone, /morning."""

from __future__ import annotations

import logging
import os
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from bot.models.user import User

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"
TIME_REGEX = re.compile(r"^(\d{2}):(\d{2})$")


async def _send_message(chat_id: int, text: str) -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        resp.raise_for_status()


def _validate_timezone(tz_string: str) -> bool:
    """Return True if tz_string is a valid IANA timezone identifier."""
    return tz_string in available_timezones()


def _validate_morning_time(time_str: str) -> bool:
    """Validate HH:MM format with 00-23:00-59 range."""
    match = TIME_REGEX.match(time_str)
    if not match:
        return False
    hour, minute = int(match.group(1)), int(match.group(2))
    return 0 <= hour <= 23 and 0 <= minute <= 59


async def handle_start(message: dict, db) -> None:
    """Handle /start command — create or greet user."""
    user_id = message["from"]["id"]
    first_name = message["from"].get("first_name", "")
    username = message["from"].get("username", "")
    chat_id = message["chat"]["id"]

    user = await User.get_or_create(
        db,
        telegram_user_id=user_id,
        first_name=first_name,
        username=username,
    )

    if user.subscription_status == "trial":
        trial_days = 7
        welcome_text = (
            f"Cześć {first_name}! 👋\n\n"
            f"Jestem Twoim asystentem ADHD. Pomagam zapamiętać i przypomnieć o wszystkim, "
            f"co musisz zrobić.\n\n"
            f"<b>Jak używać:</b>\n"
            f"Wyślij mi dowolną wiadomość z zadaniem, np.:\n"
            f"• \"Kupić mleko jutro o 17\"\n"
            f"• \"Za 2 godziny zadzwonić do mamy\"\n\n"
            f"Masz <b>{trial_days} dni za darmo</b>. Miłego korzystania! 🚀\n\n"
            f"Ustaw strefę czasową: /timezone Europe/Warsaw"
        )
    else:
        welcome_text = (
            f"Cześć z powrotem, {first_name}! 👋\n\n"
            f"Status: <b>{user.subscription_status}</b>\n"
            f"Wyślij mi zadanie, a Ci przypomnę!"
        )

    await _send_message(chat_id, welcome_text)


async def handle_timezone(message: dict, db) -> None:
    """Handle /timezone command — set user timezone."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    # Extract timezone argument: "/timezone Europe/Warsaw"
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await _send_message(
            chat_id,
            "Użycie: /timezone Europe/Warsaw\n"
            "Przykłady: Europe/Warsaw, America/New_York, Asia/Tokyo",
        )
        return

    tz_string = parts[1].strip()
    if not _validate_timezone(tz_string):
        await _send_message(
            chat_id,
            f"❌ Nieprawidłowa strefa czasowa: <b>{tz_string}</b>\n\n"
            "Użyj nazwy IANA, np.:\n"
            "• Europe/Warsaw\n"
            "• America/New_York\n"
            "• Asia/Tokyo",
        )
        return

    user = await User.get_or_create(db, telegram_user_id=user_id)
    user.timezone = tz_string
    await user.save(db)

    await _send_message(
        chat_id,
        f"✅ Strefa czasowa ustawiona na: <b>{tz_string}</b>",
    )


async def handle_morning(message: dict, db) -> None:
    """Handle /morning command — set morning reminder time."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")

    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await _send_message(
            chat_id,
            "Użycie: /morning 08:00\n"
            "Podaj godzinę w formacie HH:MM (np. 07:30, 08:00)",
        )
        return

    time_str = parts[1].strip()
    if not _validate_morning_time(time_str):
        await _send_message(
            chat_id,
            f"❌ Nieprawidłowa godzina: <b>{time_str}</b>\n\n"
            "Użyj formatu HH:MM, np. 07:30, 08:00\n"
            "Godziny: 00-23, minuty: 00-59",
        )
        return

    user = await User.get_or_create(db, telegram_user_id=user_id)
    user.morning_time = time_str
    await user.save(db)

    await _send_message(
        chat_id,
        f"✅ Godzina poranniego przypomnienia ustawiona na: <b>{time_str}</b>",
    )


async def dispatch_command(message: dict, db) -> None:
    """Route command to appropriate handler."""
    from bot.handlers.payment_command_handlers import handle_billing, handle_subscribe

    text = message.get("text", "")
    command = text.split()[0].lower() if text.split() else ""

    if command == "/start":
        await handle_start(message, db)
    elif command == "/timezone":
        await handle_timezone(message, db)
    elif command == "/morning":
        await handle_morning(message, db)
    elif command == "/subscribe":
        await handle_subscribe(message, db)
    elif command == "/billing":
        await handle_billing(message, db)
    else:
        logger.debug("Unknown command: %s", command)
