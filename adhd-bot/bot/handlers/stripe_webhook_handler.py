"""Stripe webhook handler: /stripe/webhook endpoint.

Verifies Stripe signature, deduplicates events, routes to appropriate handlers.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.services.firestore_client import get_firestore_client
from bot.services.stripe_service import (
    handle_checkout_session_completed,
    handle_invoice_payment_failed,
    handle_invoice_payment_succeeded,
    handle_subscription_deleted,
    is_event_duplicate,
    mark_event_processed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stripe")

_SUPPORTED_EVENTS = {
    "checkout.session.completed",
    "invoice.payment_failed",
    "invoice.payment_succeeded",
    "customer.subscription.deleted",
}


def _verify_stripe_signature(payload: bytes, sig_header: str | None) -> dict:
    """Verify Stripe webhook signature and return the parsed event.

    Raises HTTP 400 if signature is missing or invalid.
    In test environments (TESTING=1) signature verification is skipped and
    payload is parsed as JSON directly.
    """
    if os.environ.get("TESTING") == "1":
        import json
        return json.loads(payload)

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        raise HTTPException(status_code=400, detail="STRIPE_WEBHOOK_SECRET not configured")

    try:
        import stripe as _stripe  # type: ignore

        _stripe.api_key = os.environ.get("STRIPE_API_KEY", "")
        event = _stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        return event  # type: ignore[return-value]
    except Exception as exc:
        logger.warning("Stripe signature verification failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid Stripe signature") from exc


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> JSONResponse:
    """Process incoming Stripe webhook events.

    Verifies signature, deduplicates events, and dispatches to handlers.
    """
    payload = await request.body()
    event = _verify_stripe_signature(payload, stripe_signature)

    event_id: str = event.get("id", "")
    event_type: str = event.get("type", "")

    db = get_firestore_client()

    # Deduplication: skip already-processed events
    if event_id and await is_event_duplicate(db, event_id):
        logger.info("Stripe event %s already processed, skipping", event_id)
        return JSONResponse(content={"ok": True, "skipped": "duplicate"})

    # Mark event as processed before handling (idempotency)
    if event_id:
        await mark_event_processed(db, event_id)

    event_data = event.get("data", {}).get("object", {})

    try:
        if event_type == "checkout.session.completed":
            await handle_checkout_session_completed(db, event_data)
        elif event_type == "invoice.payment_failed":
            await handle_invoice_payment_failed(db, event_data)
        elif event_type == "invoice.payment_succeeded":
            await handle_invoice_payment_succeeded(db, event_data)
        elif event_type == "customer.subscription.deleted":
            await handle_subscription_deleted(db, event_data)
        else:
            logger.debug("Unhandled Stripe event type: %s", event_type)

    except Exception as exc:
        logger.error("Error processing Stripe event %s (%s): %s", event_id, event_type, exc)
        return JSONResponse(
            content={"ok": False, "error": "processing failed"}, status_code=500
        )

    return JSONResponse(content={"ok": True})
