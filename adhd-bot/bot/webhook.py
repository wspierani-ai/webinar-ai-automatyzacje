"""Telegram webhook receiver with security and deduplication."""

from __future__ import annotations

import hmac
import os
import time
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.services.deduplication import is_duplicate, mark_processed
from bot.services.firestore_client import get_firestore_client
from bot.security.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_UPDATE_AGE_SECONDS = 120


def _verify_secret_token(x_telegram_bot_api_secret_token: str | None) -> None:
    """Raise 401 if the secret token header is missing or wrong."""
    expected = os.environ.get("TELEGRAM_SECRET_TOKEN", "")
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, expected
    ):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _extract_update_info(body: dict[str, Any]) -> tuple[int, int | None]:
    """Return (update_id, message_date) from a Telegram update body."""
    update_id: int = body.get("update_id", 0)
    message = body.get("message") or body.get("edited_message") or {}
    message_date: int | None = message.get("date")
    return update_id, message_date


def _is_stale(message_date: int | None) -> bool:
    """Return True if the message is older than MAX_UPDATE_AGE_SECONDS."""
    if message_date is None:
        return False
    age = int(time.time()) - message_date
    return age > MAX_UPDATE_AGE_SECONDS


@router.post("/telegram/webhook")
@limiter.limit("30/minute")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> JSONResponse:
    """Main Telegram webhook endpoint.

    Processing order:
    1. Token check → 401 on failure
    2. Timestamp check → silent 200 if stale
    3. Dedup check → silent 200 if duplicate
    4. Route to handler
    """
    # 1. Security: verify secret token
    _verify_secret_token(x_telegram_bot_api_secret_token)

    body: dict[str, Any] = await request.json()
    update_id, message_date = _extract_update_info(body)

    # 2. Timestamp check: reject stale updates silently
    if _is_stale(message_date):
        logger.info("Stale update %s ignored (age > %ss)", update_id, MAX_UPDATE_AGE_SECONDS)
        return JSONResponse(content={"ok": True})

    # 3. Deduplication
    db = get_firestore_client()
    if await is_duplicate(db, update_id):
        logger.info("Duplicate update_id %s ignored", update_id)
        return JSONResponse(content={"ok": True})

    await mark_processed(db, update_id)

    # 4. Route to appropriate handler
    # Always return 200 to Telegram — processing errors must not cause retries
    try:
        await _route_update(body, db)
    except Exception:
        logger.exception("Unhandled error in _route_update for update_id %s", update_id)

    return JSONResponse(content={"ok": True})


async def _route_update(body: dict[str, Any], db) -> None:
    """Route update to the correct handler."""
    from bot.handlers.callback_handlers import dispatch_callback
    from bot.handlers.command_handlers import dispatch_command
    from bot.handlers.message_handlers import handle_text_message, handle_voice_message

    message = body.get("message")
    callback_query = body.get("callback_query")

    if callback_query:
        logger.debug("Received callback_query, routing to callback handler")
        await dispatch_callback(callback_query, db)
        return

    if message:
        text = message.get("text", "")
        voice = message.get("voice")
        if text.startswith("/"):
            logger.debug("Received command: %s", text)
            await dispatch_command(message, db)
            return
        if voice:
            logger.debug("Received voice message, routing to voice handler")
            await handle_voice_message(message, db)
            return
        logger.debug("Received text message, routing to message handler")
        await handle_text_message(message, db)
        return

    logger.debug("Unknown update type, ignoring")
