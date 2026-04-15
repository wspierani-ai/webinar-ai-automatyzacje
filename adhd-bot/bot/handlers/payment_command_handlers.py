"""Payment command handlers: /subscribe, /billing."""

from __future__ import annotations

import logging
import os

from bot.models.user import User
from bot.services.stripe_service import (
    create_checkout_session,
    create_or_get_stripe_customer,
    _get_stripe,
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
    """Handle /billing command — open Stripe Billing Portal or show status without active sub."""
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    user = await User.get_or_create(db, telegram_user_id=user_id)

    if not user.stripe_customer_id:
        await _send_message(
            chat_id,
            "Nie masz jeszcze aktywnej subskrypcji.\n"
            "Użyj /subscribe, aby wykupić subskrypcję.",
        )
        return

    if stripe is None:
        stripe = _get_stripe()

    service_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "https://example.com")
    return_url = service_url.rstrip("/")

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        portal_url: str = portal_session["url"]
    except Exception as exc:
        logger.error("Failed to create billing portal session for user %s: %s", user_id, exc)
        await _send_message(
            chat_id,
            "❌ Wystąpił błąd podczas otwierania portalu płatności. Spróbuj ponownie później.",
        )
        return

    await _send_message(
        chat_id,
        f"🔧 <b>Zarządzaj subskrypcją</b>\n\n"
        f"Kliknij poniższy link, aby zaktualizować kartę, zmienić plan lub anulować subskrypcję:\n\n"
        f"<a href='{portal_url}'>Otwórz portal płatności</a>",
    )
