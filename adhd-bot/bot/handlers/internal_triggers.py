"""Internal trigger endpoints for Cloud Tasks (reminder + nudge)."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.services.firestore_client import get_firestore_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

TELEGRAM_BASE_URL = "https://api.telegram.org"

_INTERNAL_AUDIENCE = os.environ.get("CLOUD_RUN_SERVICE_URL", "")


def _verify_oidc_token(authorization: str | None) -> None:
    """Verify that the request carries a valid Google OIDC token issued for
    this service.  Raises HTTP 401 on failure.

    In test environments (TESTING=1) verification is skipped.
    """
    if os.environ.get("TESTING") == "1":
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing OIDC token")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        from google.auth.exceptions import GoogleAuthError, TransportError  # type: ignore
        from google.auth.transport import requests as google_requests  # type: ignore
        from google.oauth2 import id_token  # type: ignore

        audience = _INTERNAL_AUDIENCE or None
        id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=audience,
        )
    except (GoogleAuthError, TransportError, ValueError) as exc:
        logger.warning("OIDC token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid OIDC token") from exc


def _build_reminder_keyboard(task_id: str) -> dict:
    """Build InlineKeyboardMarkup for reminder message."""
    return {
        "inline_keyboard": [
            [
                {"text": "+30 min", "callback_data": f"snooze:30m:{task_id}"},
                {"text": "+2h", "callback_data": f"snooze:2h:{task_id}"},
                {"text": "Jutro rano", "callback_data": f"snooze:morning:{task_id}"},
            ],
            [
                {"text": "✓ Zrobione", "callback_data": f"done:{task_id}"},
                {"text": "✗ Odrzuć", "callback_data": f"reject:{task_id}"},
            ],
        ]
    }


async def _send_telegram_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> dict:
    """Send a Telegram message via HTTP API."""
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


async def _get_task_and_user(db, task_id: str):
    """Fetch Task and User objects from Firestore."""
    from bot.models.task import Task
    from bot.models.user import User

    task_doc = await db.collection("tasks").document(task_id).get()
    if not task_doc.exists:
        return None, None
    task = Task.from_firestore_dict(task_doc.to_dict())

    user_doc = await db.collection("users").document(str(task.telegram_user_id)).get()
    if not user_doc.exists:
        return task, None
    user = User.from_firestore_dict(user_doc.to_dict())
    return task, user


@router.post("/trigger-reminder")
async def trigger_reminder(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Triggered by Cloud Tasks to send a reminder to the user.

    Requires a valid OIDC token in Authorization header (issued by Cloud Tasks).
    Idempotent: if task is already in REMINDED state, returns 200 without resending.
    """
    _verify_oidc_token(authorization)
    from bot.models.task import TaskState
    from bot.services.scheduler import schedule_nudge

    body: dict = await request.json()
    task_id: str = body.get("task_id", "")

    if not task_id:
        logger.error("trigger-reminder: missing task_id in body")
        return JSONResponse(content={"ok": False, "error": "missing task_id"}, status_code=400)

    db = get_firestore_client()
    task, user = await _get_task_and_user(db, task_id)

    if task is None:
        logger.warning("trigger-reminder: task %s not found", task_id)
        return JSONResponse(content={"ok": True, "skipped": "task not found"})

    # Idempotency guard: already reminded (or in terminal state)
    if task.state in (
        TaskState.REMINDED,
        TaskState.NUDGED,
        TaskState.COMPLETED,
        TaskState.REJECTED,
    ):
        logger.info(
            "trigger-reminder: task %s already in state %s, skipping", task_id, task.state
        )
        return JSONResponse(content={"ok": True, "skipped": "already reminded"})

    if task.state != TaskState.SCHEDULED:
        logger.warning(
            "trigger-reminder: task %s in unexpected state %s", task_id, task.state
        )
        return JSONResponse(content={"ok": True, "skipped": "unexpected state"})

    # Transition task to REMINDED
    task.transition(TaskState.REMINDED)

    # Send reminder message
    keyboard = _build_reminder_keyboard(task_id)
    message_text = f"⏰ Przypomnienie:\n\n<b>{task.content}</b>"

    try:
        result = await _send_telegram_message(
            chat_id=task.telegram_user_id,
            text=message_text,
            reply_markup=keyboard,
        )
        message_id = result.get("result", {}).get("message_id")
        task.reminder_message_id = message_id
    except Exception as exc:
        logger.error("Failed to send reminder for task %s: %s", task_id, exc)
        # Still save the state change even if message failed
        await task.save(db)
        return JSONResponse(
            content={"ok": False, "error": "telegram send failed"}, status_code=500
        )

    await task.save(db)

    # Schedule nudge for 1h later
    try:
        nudge_name = await schedule_nudge(task_id=task_id, fire_at=task.reminded_at)
        doc_ref = db.collection("tasks").document(task_id)
        await doc_ref.update({"nudge_task_name": nudge_name})
    except Exception as exc:
        logger.error("Failed to schedule nudge for task %s: %s", task_id, exc)

    return JSONResponse(content={"ok": True})


@router.post("/trigger-nudge")
async def trigger_nudge(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Triggered by Cloud Tasks to send a gentle nudge for tasks with no response.

    Requires a valid OIDC token in Authorization header (issued by Cloud Tasks).
    Only sends if task is still in REMINDED state (idempotent guard).
    """
    _verify_oidc_token(authorization)
    from bot.models.task import TaskState

    body: dict = await request.json()
    task_id: str = body.get("task_id", "")

    if not task_id:
        return JSONResponse(content={"ok": False, "error": "missing task_id"}, status_code=400)

    db = get_firestore_client()
    task, user = await _get_task_and_user(db, task_id)

    if task is None:
        return JSONResponse(content={"ok": True, "skipped": "task not found"})

    # State guard: only nudge if still REMINDED
    if task.state != TaskState.REMINDED:
        logger.info(
            "trigger-nudge: task %s in state %s, skipping nudge", task_id, task.state
        )
        return JSONResponse(content={"ok": True, "skipped": "not in REMINDED state"})

    # Transition to NUDGED
    task.transition(TaskState.NUDGED)

    nudge_text = f"👋 Hej, pamiętasz jeszcze o:\n\n<b>{task.content}</b>\n\nCzy udało się to zrobić?"
    try:
        await _send_telegram_message(
            chat_id=task.telegram_user_id,
            text=nudge_text,
            reply_markup=_build_reminder_keyboard(task_id),
        )
    except Exception as exc:
        logger.error("Failed to send nudge for task %s: %s", task_id, exc)
        await task.save(db)
        return JSONResponse(
            content={"ok": False, "error": "telegram send failed"}, status_code=500
        )

    await task.save(db)
    return JSONResponse(content={"ok": True})


@router.post("/trigger-checklist-evening")
async def trigger_checklist_evening(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Triggered by Cloud Tasks to send evening checklist reminder."""
    _verify_oidc_token(authorization)
    from bot.models.checklist import ChecklistSession
    from bot.handlers.checklist_callbacks import _build_checklist_message

    body: dict = await request.json()
    session_id: str = body.get("session_id", "")

    if not session_id:
        return JSONResponse(content={"ok": False, "error": "missing session_id"}, status_code=400)

    db = get_firestore_client()
    doc = await db.collection("checklist_sessions").document(session_id).get()
    if not doc.exists:
        return JSONResponse(content={"ok": True, "skipped": "session not found"})

    session = ChecklistSession.from_firestore_dict(doc.to_dict())

    # Idempotency guard
    if session.state != "pending_evening":
        return JSONResponse(content={"ok": True, "skipped": f"state is {session.state}"})

    text, keyboard = _build_checklist_message(session)
    evening_text = f"Jutro {session.template_name}! Oto Twoja lista:\n\n{text}"

    try:
        result = await _send_telegram_message(
            chat_id=session.user_id,
            text=evening_text,
            reply_markup=keyboard,
        )
        message_id = result.get("result", {}).get("message_id")
        session.evening_message_id = message_id
    except Exception as exc:
        logger.error("Failed to send evening checklist for session %s: %s", session_id, exc)
        return JSONResponse(content={"ok": False, "error": "telegram send failed"}, status_code=500)

    session.state = "evening_sent"
    await session.save(db)
    return JSONResponse(content={"ok": True})


@router.post("/trigger-checklist-morning")
async def trigger_checklist_morning(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Triggered by Cloud Tasks to send morning checklist reminder with only unchecked items."""
    _verify_oidc_token(authorization)
    from bot.models.checklist import ChecklistSession
    from bot.handlers.checklist_callbacks import _build_checklist_message

    body: dict = await request.json()
    session_id: str = body.get("session_id", "")

    if not session_id:
        return JSONResponse(content={"ok": False, "error": "missing session_id"}, status_code=400)

    db = get_firestore_client()
    doc = await db.collection("checklist_sessions").document(session_id).get()
    if not doc.exists:
        return JSONResponse(content={"ok": True, "skipped": "session not found"})

    session = ChecklistSession.from_firestore_dict(doc.to_dict())

    # Allow morning trigger from evening_sent or morning_sent (for snooze re-trigger)
    if session.state not in ("evening_sent", "morning_sent", "pending_evening"):
        return JSONResponse(content={"ok": True, "skipped": f"state is {session.state}"})

    # All checked already — send congratulations
    if session.all_checked:
        congrats_text = f"Juz wszystko spakowane! Milego {session.template_name}"
        try:
            await _send_telegram_message(chat_id=session.user_id, text=congrats_text)
        except Exception as exc:
            logger.error("Failed to send morning congrats for session %s: %s", session_id, exc)

        session.state = "completed"
        await session.save(db)
        return JSONResponse(content={"ok": True, "all_checked": True})

    # Send only unchecked items
    text, keyboard = _build_checklist_message(session)
    morning_text = f"Dzis {session.template_name}! Zostalo:\n\n{text}"

    try:
        result = await _send_telegram_message(
            chat_id=session.user_id,
            text=morning_text,
            reply_markup=keyboard,
        )
        message_id = result.get("result", {}).get("message_id")
        session.morning_message_id = message_id
    except Exception as exc:
        logger.error("Failed to send morning checklist for session %s: %s", session_id, exc)
        return JSONResponse(content={"ok": False, "error": "telegram send failed"}, status_code=500)

    session.state = "morning_sent"
    await session.save(db)
    return JSONResponse(content={"ok": True})
