"""Google Tasks integration — bidirectional sync via polling.

Outbound (bot → Google Tasks):
- create_google_task(db, user_id, task) → google_task_id | None
- complete_google_task(db, user_id, task) → None
- delete_google_task(db, user_id, task) → None

Polling (Google Tasks → bot):
- poll_user_tasks(db, telegram_user_id) → list[str]  (completed task IDs)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from bot.services.google_auth import get_valid_token

logger = logging.getLogger(__name__)


def _build_tasks_service(access_token: str):
    """Build Google API resource object for Tasks."""
    from googleapiclient.discovery import build  # type: ignore
    from google.oauth2.credentials import Credentials  # type: ignore

    creds = Credentials(token=access_token)
    service = build("tasks", "v1", credentials=creds, cache_discovery=False)
    return service


def _format_due_date(dt: datetime) -> str:
    """Format datetime as RFC 3339 string required by Google Tasks API."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def create_google_task(db, telegram_user_id: int, task) -> Optional[str]:
    """Create a Google Task for a scheduled bot task.

    Returns google_task_id on success, None if user has no Google or on error.
    Saves google_task_id to the task document in Firestore.
    """
    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return None

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return None

    user_data = user_doc.to_dict()
    tasks_list_id = user_data.get("google_tasks_list_id", "@default")

    task_body: dict = {
        "title": task.content,
        "notes": "Zadanie z ADHD Bot",
    }

    if task.scheduled_time:
        task_body["due"] = _format_due_date(task.scheduled_time)

    try:
        service = _build_tasks_service(access_token)
        created = (
            service.tasks()
            .insert(tasklist=tasks_list_id, body=task_body)
            .execute()
        )
        google_task_id: str = created.get("id", "")

        if google_task_id:
            task_doc_ref = db.collection("tasks").document(task.task_id)
            await task_doc_ref.update({"google_task_id": google_task_id})
            task.google_task_id = google_task_id
            logger.info(
                "Created Google Task %s for task %s", google_task_id, task.task_id
            )

        return google_task_id or None

    except Exception as exc:
        logger.error(
            "Failed to create Google Task for task %s: %s", task.task_id, exc
        )
        return None


async def complete_google_task(db, telegram_user_id: int, task) -> None:
    """Mark a Google Task as completed."""
    if not task.google_task_id:
        return

    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return

    user_data = user_doc.to_dict()
    tasks_list_id = user_data.get("google_tasks_list_id", "@default")

    try:
        service = _build_tasks_service(access_token)
        service.tasks().patch(
            tasklist=tasks_list_id,
            task=task.google_task_id,
            body={"status": "completed"},
        ).execute()
        logger.info("Marked Google Task %s as completed", task.google_task_id)
    except Exception as exc:
        logger.error("Failed to complete Google Task %s: %s", task.google_task_id, exc)


async def delete_google_task(db, telegram_user_id: int, task) -> None:
    """Delete a Google Task (used when task is rejected)."""
    if not task.google_task_id:
        return

    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return

    user_data = user_doc.to_dict()
    tasks_list_id = user_data.get("google_tasks_list_id", "@default")

    try:
        service = _build_tasks_service(access_token)
        service.tasks().delete(
            tasklist=tasks_list_id,
            task=task.google_task_id,
        ).execute()
        logger.info("Deleted Google Task %s", task.google_task_id)
    except Exception as exc:
        logger.error("Failed to delete Google Task %s: %s", task.google_task_id, exc)


async def poll_user_tasks(db, telegram_user_id: int) -> list[str]:
    """Poll Google Tasks for a single user and return completed google_task_ids.

    Also updates nextSyncToken in user document for delta queries.
    """
    access_token = await get_valid_token(db, telegram_user_id)
    if not access_token:
        return []

    user_doc = await db.collection("users").document(str(telegram_user_id)).get()
    if not user_doc.exists:
        return []

    user_data = user_doc.to_dict()
    tasks_list_id = user_data.get("google_tasks_list_id", "@default")
    sync_token = user_data.get("google_tasks_sync_token")

    try:
        service = _build_tasks_service(access_token)

        list_kwargs: dict = {
            "tasklist": tasks_list_id,
            "showCompleted": True,
            "showHidden": True,
            "maxResults": 100,
        }

        if sync_token:
            list_kwargs["syncToken"] = sync_token
        else:
            # Initial poll: limit to recently updated tasks
            list_kwargs["updatedMin"] = datetime.now(tz=timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            ).isoformat()

        result = service.tasks().list(**list_kwargs).execute()

        completed_ids: list[str] = []
        for item in result.get("items", []):
            if item.get("status") == "completed":
                completed_ids.append(item["id"])

        # Persist nextSyncToken for next poll
        new_sync_token = result.get("nextSyncToken")
        if new_sync_token:
            user_doc_ref = db.collection("users").document(str(telegram_user_id))
            await user_doc_ref.update({
                "google_tasks_sync_token": new_sync_token,
                "updated_at": datetime.now(tz=timezone.utc),
            })

        return completed_ids

    except Exception as exc:
        logger.error(
            "Failed to poll Google Tasks for user %s: %s", telegram_user_id, exc
        )
        return []
