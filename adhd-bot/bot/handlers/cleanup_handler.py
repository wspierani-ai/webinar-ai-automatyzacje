"""Cleanup handler for auto-archival and orphan Cloud Task cleanup.

Endpoint: /internal/cleanup
Schedule: 0 3 * * * (03:00 Europe/Warsaw via Cloud Scheduler)
Auth: OIDC token required (same pattern as internal_triggers.py)

Responsibilities:
- Expire trial users whose trial_ends_at has passed → status="blocked"
- Expire grace_period users whose grace_period_until has passed → status="blocked"
- Delete orphaned Cloud Tasks for archived tasks (COMPLETED/REJECTED with expired nudge names)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from bot.services.firestore_client import get_firestore_client
from bot.services.scheduler import cancel_reminder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")

_INTERNAL_AUDIENCE = os.environ.get("CLOUD_RUN_SERVICE_URL", "")


def _verify_oidc_token(authorization: str | None) -> None:
    """Verify that the request carries a valid Google OIDC token.

    Raises HTTP 401 on failure.
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


async def _block_expired_trial_users(db, now: datetime) -> int:
    """Set subscription_status=blocked for users whose trial has expired.

    Returns the count of updated users.
    """
    count = 0
    users_ref = db.collection("users")
    # Query for trial users
    query = users_ref.where("subscription_status", "==", "trial")
    docs = await query.get()

    for doc in docs:
        data = doc.to_dict()
        trial_ends_at = data.get("trial_ends_at")
        if trial_ends_at is None:
            continue

        # Normalize to UTC-aware datetime for comparison
        if hasattr(trial_ends_at, "tzinfo") and trial_ends_at.tzinfo is None:
            trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)

        if trial_ends_at < now:
            await doc.reference.update({
                "subscription_status": "blocked",
                "updated_at": now,
            })
            logger.info("Blocked expired trial user: %s", data.get("telegram_user_id"))
            count += 1

    return count


async def _block_expired_grace_period_users(db, now: datetime) -> int:
    """Set subscription_status=blocked for users whose grace period has expired.

    Returns the count of updated users.
    """
    count = 0
    users_ref = db.collection("users")
    query = users_ref.where("subscription_status", "==", "grace_period")
    docs = await query.get()

    for doc in docs:
        data = doc.to_dict()
        grace_period_until = data.get("grace_period_until")
        if grace_period_until is None:
            # No grace period end date — skip to avoid unintended blocking
            logger.warning(
                "Skipping grace_period user %s: grace_period_until is None",
                data.get("telegram_user_id"),
            )
            continue

        if hasattr(grace_period_until, "tzinfo") and grace_period_until.tzinfo is None:
            grace_period_until = grace_period_until.replace(tzinfo=timezone.utc)

        if grace_period_until < now:
            await doc.reference.update({
                "subscription_status": "blocked",
                "updated_at": now,
            })
            logger.info("Blocked expired grace_period user: %s", data.get("telegram_user_id"))
            count += 1

    return count


async def _cleanup_orphaned_cloud_tasks(db, now: datetime) -> int:
    """Delete Cloud Tasks for tasks in terminal states (COMPLETED/REJECTED).

    These tasks may still have cloud_task_name or nudge_task_name set even
    though they are no longer needed.

    Returns the count of cleaned tasks.
    """
    count = 0
    tasks_ref = db.collection("tasks")

    # Query completed tasks
    for state in ("COMPLETED", "REJECTED"):
        query = tasks_ref.where("state", "==", state)
        docs = await query.get()

        for doc in docs:
            data = doc.to_dict()
            cloud_task_name = data.get("cloud_task_name")
            nudge_task_name = data.get("nudge_task_name")

            update_data: dict = {}
            if cloud_task_name:
                await cancel_reminder(cloud_task_name)
                update_data["cloud_task_name"] = None

            if nudge_task_name:
                await cancel_reminder(nudge_task_name)
                update_data["nudge_task_name"] = None

            if update_data:
                update_data["updated_at"] = now
                await doc.reference.update(update_data)
                count += 1

    return count


@router.post("/cleanup")
async def cleanup(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Run cleanup job: expire subscriptions + clean orphaned Cloud Tasks.

    Protected by OIDC auth (same as other /internal/* endpoints).
    Idempotent: safe to run multiple times.
    """
    _verify_oidc_token(authorization)

    now = datetime.now(tz=timezone.utc)
    db = get_firestore_client()

    results: dict[str, int] = {}

    try:
        results["trial_blocked"] = await _block_expired_trial_users(db, now)
    except Exception as exc:
        logger.error("Failed to block expired trial users: %s", exc)
        results["trial_blocked"] = 0

    try:
        results["grace_period_blocked"] = await _block_expired_grace_period_users(db, now)
    except Exception as exc:
        logger.error("Failed to block expired grace_period users: %s", exc)
        results["grace_period_blocked"] = 0

    try:
        results["orphaned_tasks_cleaned"] = await _cleanup_orphaned_cloud_tasks(db, now)
    except Exception as exc:
        logger.error("Failed to cleanup orphaned Cloud Tasks: %s", exc)
        results["orphaned_tasks_cleaned"] = 0

    logger.info("Cleanup completed: %s", results)
    return JSONResponse(content={"ok": True, "results": results})
