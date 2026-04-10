"""Google Tasks polling handler.

Endpoint: POST /internal/poll-google-tasks
Schedule: */5 * * * * (every 5 min via Cloud Scheduler)
Auth: OIDC token required

Polls Google Tasks for all users with an active Google connection.
For each completed Google Task found, transitions the corresponding bot task
to COMPLETED state and sends a Telegram confirmation.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from bot.services.firestore_client import get_firestore_client
from bot.services.google_tasks import poll_user_tasks
from bot.services.scheduler import cancel_reminder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

_TELEGRAM_BASE_URL = "https://api.telegram.org"
_INTERNAL_AUDIENCE = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
_MAX_USERS_PER_INVOCATION = 100


def _verify_oidc_token(authorization: str | None) -> None:
    """Verify Google OIDC token. Skipped in test environments (TESTING=1)."""
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


async def _send_telegram_message(telegram_user_id: int, text: str) -> None:
    """Send Telegram message. No-op in test environments."""
    if os.environ.get("TESTING") == "1":
        return

    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{_TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"chat_id": telegram_user_id, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.error(
            "Failed to send Telegram message to %s: %s", telegram_user_id, exc
        )


@router.post("/poll-google-tasks")
async def poll_google_tasks(
    request: Request,
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Poll Google Tasks for all connected users and sync completions to bot."""
    _verify_oidc_token(authorization)

    db = get_firestore_client()

    # Fetch users with active Google connection
    users_ref = db.collection("users")
    # Query users where google_connected == True
    try:
        query = users_ref.where("google_connected", "==", True).limit(_MAX_USERS_PER_INVOCATION)
        user_docs = await query.get()
    except Exception as exc:
        logger.error("Failed to fetch Google-connected users: %s", exc)
        return JSONResponse(content={"status": "error", "detail": str(exc)}, status_code=500)

    if not user_docs:
        return JSONResponse(content={"status": "ok", "processed_users": 0, "completed_tasks": 0})

    total_completed = 0
    processed_users = 0

    for user_doc in user_docs:
        try:
            user_data = user_doc.to_dict()
            telegram_user_id = user_data.get("telegram_user_id")

            if not telegram_user_id:
                continue

            completed_count = await _process_user_polling(db, telegram_user_id)
            total_completed += completed_count
            processed_users += 1

        except Exception as exc:
            logger.error(
                "Error processing Google Tasks poll for user %s: %s",
                user_doc.id,
                exc,
            )
            # Continue with next user

    logger.info(
        "Google Tasks poll complete: %d users, %d tasks completed",
        processed_users,
        total_completed,
    )
    return JSONResponse(
        content={
            "status": "ok",
            "processed_users": processed_users,
            "completed_tasks": total_completed,
        }
    )


async def _process_user_polling(db, telegram_user_id: int) -> int:
    """Poll Google Tasks for one user. Returns number of tasks completed."""
    from bot.models.task import TaskState

    completed_google_task_ids = await poll_user_tasks(db, telegram_user_id)

    if not completed_google_task_ids:
        return 0

    completed_count = 0
    for google_task_id in completed_google_task_ids:
        try:
            count = await _sync_completed_task(db, telegram_user_id, google_task_id)
            completed_count += count
        except Exception as exc:
            logger.error(
                "Error syncing completed Google Task %s for user %s: %s",
                google_task_id,
                telegram_user_id,
                exc,
            )

    return completed_count


async def _sync_completed_task(
    db, telegram_user_id: int, google_task_id: str
) -> int:
    """Find bot task matching google_task_id and complete it if not already done.

    Returns 1 if task was completed, 0 otherwise.
    """
    from bot.models.task import Task, TaskState

    # Find bot task with matching google_task_id
    tasks_query = (
        db.collection("tasks")
        .where("telegram_user_id", "==", telegram_user_id)
        .where("google_task_id", "==", google_task_id)
        .limit(1)
    )
    task_docs = await tasks_query.get()

    if not task_docs:
        return 0

    task_doc = task_docs[0]
    task_data = task_doc.to_dict()
    task = Task.from_firestore_dict(task_data)

    # Only complete tasks in active states
    completable_states = {TaskState.REMINDED, TaskState.NUDGED, TaskState.SNOOZED}
    if task.state not in completable_states:
        return 0

    from bot.models.task import ARCHIVE_STATES
    from datetime import datetime, timedelta, timezone

    # Transition to COMPLETED
    task.transition(TaskState.COMPLETED)

    # Cancel pending Cloud Tasks
    if task.cloud_task_name:
        await cancel_reminder(task.cloud_task_name)
    if task.nudge_task_name:
        await cancel_reminder(task.nudge_task_name)

    # Persist state change
    task_doc_ref = db.collection("tasks").document(task.task_id)
    await task_doc_ref.update({
        "state": task.state.value,
        "completed_at": task.completed_at,
        "expires_at": task.expires_at,
        "cloud_task_name": None,
        "nudge_task_name": None,
    })

    # Notify user via Telegram
    await _send_telegram_message(
        telegram_user_id,
        f"✅ Zadanie ukończone w Google Tasks: <b>{task.content}</b>",
    )

    logger.info(
        "Task %s completed via Google Tasks polling for user %s",
        task.task_id,
        telegram_user_id,
    )
    return 1
