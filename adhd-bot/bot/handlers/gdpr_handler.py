"""GDPR handler — cascade delete all user data on /delete_my_data confirmation."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"

# All Firestore collections that store per-user data
USER_COLLECTIONS = [
    "tasks",
    "token_usage",
    "checklist_templates",
    "checklist_sessions",
    "processed_updates",
]


async def _answer_callback_query(callback_query_id: str, text: str = "") -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{TELEGRAM_BASE_URL}/bot{token}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id, "text": text},
        )


async def _send_message(chat_id: int, text: str) -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
        resp.raise_for_status()


async def _delete_collection_docs(db, collection_name: str, user_id: int) -> int:
    """Delete all documents in a collection matching the user_id. Returns count deleted."""
    count = 0

    # Different collections use different field names for user identification
    field_name = "telegram_user_id" if collection_name in ("tasks",) else "user_id"

    try:
        query = db.collection(collection_name).where(field_name, "==", user_id)
        docs = await query.get()
        for doc in docs:
            await doc.reference.delete()
            count += 1
    except Exception as exc:
        logger.error(
            "Failed to delete docs from %s for user %s: %s",
            collection_name, user_id, exc,
        )

    return count


async def _cancel_user_stripe_subscription(user_data: dict) -> bool:
    """Cancel Stripe subscription if exists. Returns True if cancelled."""
    subscription_id = user_data.get("stripe_subscription_id")
    if not subscription_id:
        return False

    try:
        import stripe

        stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        stripe.Subscription.cancel(subscription_id)
        logger.info("Cancelled Stripe subscription %s", subscription_id)
        return True
    except Exception as exc:
        logger.error("Failed to cancel Stripe subscription %s: %s", subscription_id, exc)
        return False


async def _revoke_google_token(db, user_id: int, user_data: dict) -> bool:
    """Revoke Google refresh token if connected. Returns True if revoked."""
    if not user_data.get("google_connected", False):
        return False

    try:
        from bot.services.google_auth import disconnect_google

        await disconnect_google(db, user_id)
        logger.info("Revoked Google token for user %s", user_id)
        return True
    except Exception as exc:
        logger.error("Failed to revoke Google token for user %s: %s", user_id, exc)
        return False


async def cascade_delete_user_data(db, user_id: int) -> dict[str, Any]:
    """Delete ALL user data from Firestore and external services.

    Returns a summary dict of what was deleted.
    """
    summary: dict[str, Any] = {"collections_deleted": {}, "stripe_cancelled": False, "google_revoked": False}

    # Load user data before deletion
    user_doc = await db.collection("users").document(str(user_id)).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}

    # Delete from all per-user collections
    for collection_name in USER_COLLECTIONS:
        count = await _delete_collection_docs(db, collection_name, user_id)
        summary["collections_deleted"][collection_name] = count

    # Cancel Stripe subscription
    summary["stripe_cancelled"] = await _cancel_user_stripe_subscription(user_data)

    # Revoke Google token
    summary["google_revoked"] = await _revoke_google_token(db, user_id, user_data)

    # Delete user document last
    try:
        await db.collection("users").document(str(user_id)).delete()
        summary["user_deleted"] = True
    except Exception as exc:
        logger.error("Failed to delete user document for %s: %s", user_id, exc)
        summary["user_deleted"] = False

    return summary


async def handle_gdpr_confirm_callback(callback_query: dict, db) -> None:
    """Handle GDPR deletion confirmation callback."""
    callback_query_id = callback_query["id"]
    user_id = callback_query["from"]["id"]
    chat_id = callback_query["message"]["chat"]["id"]

    await _answer_callback_query(callback_query_id)

    # Perform cascade deletion
    summary = await cascade_delete_user_data(db, user_id)

    logger.info("GDPR delete completed for user %s: %s", user_id, summary)

    await _send_message(
        chat_id,
        "Wszystkie Twoje dane zostaly usuniete. Do zobaczenia!",
    )


async def handle_gdpr_cancel_callback(callback_query: dict, db) -> None:
    """Handle GDPR deletion cancellation callback."""
    callback_query_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]

    await _answer_callback_query(callback_query_id)

    await _send_message(chat_id, "Anulowano. Twoje dane sa bezpieczne.")
