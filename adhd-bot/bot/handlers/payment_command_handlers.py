"""Payment command handlers: /subscribe, /billing."""

from __future__ import annotations

import logging
import os

from bot.models.user import User
from bot.services.stripe_service import (
    create_checkout_session,
    create_or_get_stripe_customer,
)

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"

_SUBSCRIBE_SUCCESS_PATH = "/subscribe/success"
_SUBSCRIBE_CANCEL_PATH = "/subscribe/cancel"


async def _send_message(chat_id: int, text: str, parse_mode: str = "HTML") -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            url, json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )
        resp.raise_for_status()


def _build_success_url(service_url: str) -> str:
    base = service_url.rstrip("/")
    return f"{base}{_SUBSCRIBE_SUCCESS_PATH}"


def _build_cancel_url(service_url: str) -> str:
    base = service_url.rstrip("/")
    return f"{base}{_SUBSCRIBE_CANCEL_PATH}"


async def handle_subscribe(message: dict, db, *, stripe=None) -> None:
    """Handle /subscribe command — create Stripe Checkout Session and send link."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    user = await User.get_or_create(db, telegram_user_id=user_id)

    if user.subscription_status == "active":
        await _send_message(
            chat_id,
            "✅ Twoja subskrypcja jest już <b>aktywna</b>.\n"
            "Użyj /billing, aby zarządzać subskrypcją.",
        )
        return

    service_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "https://example.com")
    success_url = _build_success_url(service_url)
    cancel_url = _build_cancel_url(service_url)

    try:
        await create_or_get_stripe_customer(db, user, stripe=stripe)
        checkout_url = await create_checkout_session(
            user,
            success_url=success_url,
            cancel_url=cancel_url,
            stripe=stripe,
        )
    except Exception as exc:
        logger.error("Failed to create checkout session for user %s: %s", user_id, exc)
        await _send_message(
            chat_id,
            "❌ Wystąpił błąd podczas tworzenia sesji płatności. Spróbuj ponownie później.",
        )
        return

    if user.subscription_status == "blocked":
        intro = (
            "🔒 Twój dostęp do bota jest zablokowany.\n\n"
            "Wykup subskrypcję, aby odblokować dostęp:\n\n"
        )
    elif user.subscription_status == "grace_period":
        intro = (
            "⚠️ Twoja płatność nie powiodła się. Masz 3 dni, aby odnowić subskrypcję.\n\n"
            "Odnów subskrypcję tutaj:\n\n"
        )
    else:
        intro = (
            "🚀 Subskrypcja ADHD Bota — <b>29.99 PLN/miesiąc</b>\n\n"
            "Kliknij poniższy link, aby przejść do płatności:\n\n"
        )

    await _send_message(chat_id, f"{intro}<a href='{checkout_url}'>Przejdź do płatności</a>")


async def handle_billing(message: dict, db, *, stripe=None) -> None:
    """Handle /billing command — show subscription status."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    user = await User.get_or_create(db, telegram_user_id=user_id)

    status = user.subscription_status

    if status == "active":
        text = (
            "✅ <b>Status subskrypcji: Aktywna</b>\n\n"
            "Twoja subskrypcja jest aktywna. Dziękujemy!\n"
            "Aby anulować, skontaktuj się z pomocą techniczną."
        )
    elif status == "trial":
        from datetime import datetime, timezone
        if user.trial_ends_at:
            now = datetime.now(tz=timezone.utc)
            days_left = max(0, (user.trial_ends_at - now).days)
            text = (
                f"⏳ <b>Status subskrypcji: Trial</b>\n\n"
                f"Pozostało dni próbnych: <b>{days_left}</b>\n\n"
                f"Aby kontynuować po zakończeniu trialu, użyj /subscribe"
            )
        else:
            text = (
                "⏳ <b>Status subskrypcji: Trial</b>\n\n"
                "Korzystasz z darmowego okresu próbnego.\n"
                "Użyj /subscribe, aby kupić subskrypcję."
            )
    elif status == "grace_period":
        from datetime import datetime, timezone
        if user.grace_period_until:
            now = datetime.now(tz=timezone.utc)
            days_left = max(0, (user.grace_period_until - now).days)
            text = (
                f"⚠️ <b>Status subskrypcji: Grace Period</b>\n\n"
                f"Twoja płatność nie powiodła się. Masz <b>{days_left} dni</b> na odnowienie.\n\n"
                f"Użyj /subscribe, aby odnowić subskrypcję."
            )
        else:
            text = (
                "⚠️ <b>Status subskrypcji: Grace Period</b>\n\n"
                "Twoja płatność nie powiodła się.\n"
                "Użyj /subscribe, aby odnowić subskrypcję."
            )
    else:
        # blocked or unknown
        text = (
            "🔒 <b>Status subskrypcji: Zablokowana</b>\n\n"
            "Twój dostęp do bota jest zablokowany.\n\n"
            "Użyj /subscribe, aby wykupić subskrypcję."
        )

    await _send_message(chat_id, text)
