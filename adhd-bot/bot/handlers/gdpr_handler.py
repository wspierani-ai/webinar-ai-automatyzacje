"""GDPR handler — cascade delete all user data on /delete_my_data confirmation."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx
from google.cloud.exceptions import GoogleCloudError

from bot.services.scheduler import cancel_reminder

logger = logging.getLogger(__name__)

TELEGRAM_BASE_URL = "https://api.telegram.org"

# All Firestore collections that store per-user data (flat, with user_id field).
# NOTE: processed_updates is intentionally excluded — documents are keyed by
# Telegram update_id, have no user_id field, and auto-expire via 24h TTL.
# NOTE: token_usage uses subcollection structure (token_usage/{date}/users/{uid})
# and is handled separately in _delete_token_usage_docs.
USER_COLLECTIONS = [
    "tasks",
    "checklist_templates",
    "checklist_sessions",
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
    except GoogleCloudError as exc:
        logger.error(
            "Failed to delete docs from %s for user %s: %s",
            collection_name, user_id, exc,
        )

    return count


async def _delete_token_usage_docs(db, user_id: int) -> int:
    """Delete token_usage subcollection docs for user.

    Structure: token_usage/{YYYY-MM-DD}/users/{user_id}
    Enumerate all date documents, then delete the user's doc under each.
    """
    count = 0
    try:
        date_docs = await db.collection("token_usage").get()
        for date_doc in date_docs:
            user_doc_ref = (
                db.collection("token_usage")
                .document(date_doc.id)
                .collection("users")
                .document(str(user_id))
            )
            user_doc = await user_doc_ref.get()
            if user_doc.exists:
                await user_doc_ref.delete()
                count += 1
    except GoogleCloudError as exc:
        logger.error(
            "Failed to delete token_usage docs for user %s: %s",
            user_id, exc,
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
    except stripe.error.StripeError as exc:
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
    except (httpx.HTTPError, ValueError, GoogleCloudError) as exc:
        logger.error("Failed to revoke Google token for user %s: %s", user_id, exc)
        return False


async def _cancel_active_cloud_tasks(db, user_id: int) -> int:
    """Cancel Cloud Tasks for user's active tasks and checklist sessions.

    Looks for tasks in SCHEDULED/REMINDED/SNOOZED/NUDGED states and
    checklist sessions with pending cloud tasks. Returns count cancelled.
    """
    cancelled = 0

    # Cancel Cloud Tasks for active task reminders/nudges
    active_states = ["SCHEDULED", "REMINDED", "SNOOZED", "NUDGED"]
    try:
        for state_val in active_states:
            query = (
                db.collection("tasks")
                .where("telegram_user_id", "==", user_id)
                .where("state", "==", state_val)
            )
            docs = await query.get()
            for doc in docs:
                data = doc.to_dict()
                for ct_field in ("cloud_task_name", "nudge_task_name"):
                    ct_name = data.get(ct_field)
                    if ct_name:
                        await cancel_reminder(ct_name)
                        cancelled += 1
    except GoogleCloudError as exc:
        logger.error("Failed to cancel task Cloud Tasks for user %s: %s", user_id, exc)

    # Cancel Cloud Tasks for checklist sessions
    try:
        query = db.collection("checklist_sessions").where("user_id", "==", user_id)
        docs = await query.get()
        for doc in docs:
            data = doc.to_dict()
            for ct_field in ("cloud_task_name_evening", "cloud_task_name_morning"):
                ct_name = data.get(ct_field)
                if ct_name:
                    await cancel_reminder(ct_name)
                    cancelled += 1
    except GoogleCloudError as exc:
        logger.error("Failed to cancel checklist Cloud Tasks for user %s: %s", user_id, exc)

    return cancelled


async def cascade_delete_user_data(db, user_id: int) -> dict[str, Any]:
    """Delete ALL user data from Firestore and external services.

    Returns a summary dict of what was deleted.
    """
    summary: dict[str, Any] = {
        "collections_deleted": {},
        "stripe_cancelled": False,
        "google_revoked": False,
        "cloud_tasks_cancelled": 0,
    }

    # Load user data before deletion
    user_doc = await db.collection("users").document(str(user_id)).get()
    user_data = user_doc.to_dict() if user_doc.exists else {}

    # Cancel active Cloud Tasks before deleting documents (P2-2)
    summary["cloud_tasks_cancelled"] = await _cancel_active_cloud_tasks(db, user_id)

    # Delete from all per-user collections (flat structure)
    for collection_name in USER_COLLECTIONS:
        count = await _delete_collection_docs(db, collection_name, user_id)
        summary["collections_deleted"][collection_name] = count

    # Delete token_usage subcollection docs (P1-1)
    token_count = await _delete_token_usage_docs(db, user_id)
    summary["collections_deleted"]["token_usage"] = token_count

    # Cancel Stripe subscription
    summary["stripe_cancelled"] = await _cancel_user_stripe_subscription(user_data)

    # Revoke Google token
    summary["google_revoked"] = await _revoke_google_token(db, user_id, user_data)

    # Delete user document last
    try:
        await db.collection("users").document(str(user_id)).delete()
        summary["user_deleted"] = True
    except GoogleCloudError as exc:
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
