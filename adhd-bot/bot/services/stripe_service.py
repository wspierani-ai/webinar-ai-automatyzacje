"""Stripe service: Customer creation, Checkout Session, event deduplication."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

STRIPE_CURRENCY = "pln"


def _get_stripe():
    """Return configured stripe module. Lazy-imported to allow mocking in tests."""
    import stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
    return _stripe


async def create_or_get_stripe_customer(
    db,
    user,
    *,
    stripe=None,
) -> str:
    """Return existing stripe_customer_id or create a new Stripe Customer.

    Persists stripe_customer_id to Firestore if newly created.
    """
    if user.stripe_customer_id:
        return user.stripe_customer_id

    if stripe is None:
        stripe = _get_stripe()

    customer = stripe.Customer.create(
        metadata={"telegram_user_id": str(user.telegram_user_id)},
        name=user.first_name or None,
    )
    customer_id: str = customer["id"]

    # Persist to Firestore
    doc_ref = db.collection("users").document(str(user.telegram_user_id))
    await doc_ref.update({
        "stripe_customer_id": customer_id,
        "updated_at": datetime.now(tz=timezone.utc),
    })
    user.stripe_customer_id = customer_id

    logger.info(
        "Created Stripe customer %s for user %s", customer_id, user.telegram_user_id
    )
    return customer_id


async def create_checkout_session(
    user,
    *,
    success_url: str,
    cancel_url: str,
    stripe=None,
) -> str:
    """Create a Stripe Checkout Session for subscription purchase.

    Returns the checkout session URL.
    """
    if stripe is None:
        stripe = _get_stripe()

    price_id = os.environ.get("STRIPE_PRICE_ID", "")

    params: dict[str, Any] = {
        "mode": "subscription",
        "currency": STRIPE_CURRENCY,
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": {"telegram_user_id": str(user.telegram_user_id)},
    }

    if user.stripe_customer_id:
        params["customer"] = user.stripe_customer_id

    session = stripe.checkout.Session.create(**params)
    url: str = session["url"]
    logger.info(
        "Created Checkout Session %s for user %s", session["id"], user.telegram_user_id
    )
    return url


async def is_event_duplicate(db, event_id: str) -> bool:
    """Return True if this Stripe event_id was already processed (deduplication).

    Uses Firestore collection stripe_events/{event_id}.
    """
    doc_ref = db.collection("stripe_events").document(event_id)
    doc = await doc_ref.get()
    return doc.exists


async def mark_event_processed(db, event_id: str) -> None:
    """Mark Stripe event_id as processed in Firestore."""
    doc_ref = db.collection("stripe_events").document(event_id)
    await doc_ref.set({
        "event_id": event_id,
        "processed_at": datetime.now(tz=timezone.utc),
    })


async def handle_checkout_session_completed(db, session_data: dict) -> None:
    """Process checkout.session.completed event.

    Sets subscription_status=active and stores stripe_subscription_id.
    """
    telegram_user_id = session_data.get("metadata", {}).get("telegram_user_id")
    subscription_id = session_data.get("subscription")

    if not telegram_user_id:
        logger.warning("checkout.session.completed: missing telegram_user_id in metadata")
        return

    doc_ref = db.collection("users").document(str(telegram_user_id))
    await doc_ref.update({
        "subscription_status": "active",
        "stripe_subscription_id": subscription_id,
        "grace_period_until": None,
        "updated_at": datetime.now(tz=timezone.utc),
    })
    logger.info(
        "User %s subscription activated (sub=%s)", telegram_user_id, subscription_id
    )


async def handle_invoice_payment_failed(db, invoice_data: dict) -> None:
    """Process invoice.payment_failed event.

    Sets subscription_status=grace_period with 3-day grace period.
    """
    customer_id: Optional[str] = invoice_data.get("customer")
    if not customer_id:
        logger.warning("invoice.payment_failed: missing customer")
        return

    user_doc = await _find_user_by_customer_id(db, customer_id)
    if user_doc is None:
        logger.warning("invoice.payment_failed: user not found for customer %s", customer_id)
        return

    grace_period_until = datetime.now(tz=timezone.utc) + timedelta(days=3)
    await user_doc.reference.update({
        "subscription_status": "grace_period",
        "grace_period_until": grace_period_until,
        "updated_at": datetime.now(tz=timezone.utc),
    })
    logger.info(
        "User set to grace_period until %s (customer=%s)", grace_period_until, customer_id
    )


async def handle_invoice_payment_succeeded(db, invoice_data: dict) -> None:
    """Process invoice.payment_succeeded event.

    Restores subscription_status=active and clears grace_period_until.
    """
    customer_id: Optional[str] = invoice_data.get("customer")
    if not customer_id:
        logger.warning("invoice.payment_succeeded: missing customer")
        return

    user_doc = await _find_user_by_customer_id(db, customer_id)
    if user_doc is None:
        logger.warning("invoice.payment_succeeded: user not found for customer %s", customer_id)
        return

    await user_doc.reference.update({
        "subscription_status": "active",
        "grace_period_until": None,
        "updated_at": datetime.now(tz=timezone.utc),
    })
    logger.info("User subscription renewed (customer=%s)", customer_id)


async def handle_subscription_deleted(db, subscription_data: dict) -> None:
    """Process customer.subscription.deleted event.

    Sets subscription_status=blocked.
    """
    customer_id: Optional[str] = subscription_data.get("customer")
    if not customer_id:
        logger.warning("customer.subscription.deleted: missing customer")
        return

    user_doc = await _find_user_by_customer_id(db, customer_id)
    if user_doc is None:
        logger.warning(
            "customer.subscription.deleted: user not found for customer %s", customer_id
        )
        return

    await user_doc.reference.update({
        "subscription_status": "blocked",
        "stripe_subscription_id": None,
        "updated_at": datetime.now(tz=timezone.utc),
    })
    logger.info("User subscription deleted (customer=%s)", customer_id)


async def _find_user_by_customer_id(db, customer_id: str):
    """Return user DocumentSnapshot by stripe_customer_id, or None."""
    query = db.collection("users").where("stripe_customer_id", "==", customer_id)
    docs = await query.get()
    for doc in docs:
        return doc
    return None
