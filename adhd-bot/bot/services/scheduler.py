"""Cloud Tasks scheduler for reminders and nudges."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

REMINDER_QUEUE = "reminders"
NUDGE_QUEUE = "nudges"
CHECKLIST_QUEUE = "reminders"  # reuse reminders queue for checklist triggers
NUDGE_DELAY_SECONDS = 3600  # 1 hour


def _get_tasks_client():
    """Return Cloud Tasks client."""
    from google.cloud import tasks_v2  # type: ignore
    return tasks_v2.CloudTasksClient()


def _build_task_name(project: str, region: str, queue: str, task_id: str) -> str:
    return f"projects/{project}/locations/{region}/queues/{queue}/tasks/{task_id}"


def _build_queue_path(project: str, region: str, queue: str) -> str:
    return f"projects/{project}/locations/{region}/queues/{queue}"


def make_reminder_task_name(task_id: str, fire_at: datetime) -> str:
    """Generate deterministic Cloud Task name for a reminder."""
    return f"reminder-{task_id}-{int(fire_at.timestamp())}"


def make_nudge_task_name(task_id: str, fire_at: datetime) -> str:
    """Generate deterministic Cloud Task name for a nudge."""
    return f"nudge-{task_id}-{int(fire_at.timestamp())}"


async def schedule_reminder(
    task_id: str,
    fire_at: datetime,
    project: Optional[str] = None,
    region: Optional[str] = None,
    service_url: Optional[str] = None,
    queue: Optional[str] = None,
) -> str:
    """Schedule a Cloud Task to trigger the reminder endpoint at fire_at.

    Returns the Cloud Task name.
    """
    proj = project or os.environ.get("GCP_PROJECT_ID", "")
    reg = region or os.environ.get("GCP_REGION", "europe-central2")
    url = service_url or os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    q = queue or os.environ.get("CLOUD_TASKS_REMINDERS_QUEUE", REMINDER_QUEUE)

    ct_name = make_reminder_task_name(task_id, fire_at)
    full_task_name = _build_task_name(proj, reg, q, ct_name)
    queue_path = _build_queue_path(proj, reg, q)

    payload = json.dumps({"task_id": task_id}).encode()
    schedule_time = fire_at if fire_at.tzinfo else fire_at.replace(tzinfo=timezone.utc)

    from google.cloud import tasks_v2  # type: ignore
    from google.protobuf import timestamp_pb2  # type: ignore

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(schedule_time)

    task = {
        "name": full_task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{url}/internal/trigger-reminder",
            "headers": {"Content-Type": "application/json"},
            "body": payload,
            "oidc_token": {
                "service_account_email": f"cloud-tasks-sa@{proj}.iam.gserviceaccount.com",
            },
        },
        "schedule_time": ts,
    }

    client = _get_tasks_client()
    client.create_task(request={"parent": queue_path, "task": task})
    logger.info("Scheduled reminder Cloud Task: %s at %s", ct_name, fire_at.isoformat())
    return ct_name


async def cancel_reminder(task_name: Optional[str]) -> None:
    """Cancel a Cloud Task by name. Silently ignores None or NOT_FOUND."""
    if not task_name:
        return

    try:
        project = os.environ.get("GCP_PROJECT_ID", "")
        region = os.environ.get("GCP_REGION", "europe-central2")

        # Resolve full task name if only the short name was provided
        if not task_name.startswith("projects/"):
            queue = os.environ.get("CLOUD_TASKS_REMINDERS_QUEUE", REMINDER_QUEUE)
            if task_name.startswith("nudge-"):
                queue = os.environ.get("CLOUD_TASKS_NUDGES_QUEUE", NUDGE_QUEUE)
            task_name = _build_task_name(project, region, queue, task_name)

        client = _get_tasks_client()
        client.delete_task(request={"name": task_name})
        logger.info("Cancelled Cloud Task: %s", task_name)

    except Exception as exc:  # noqa: BLE001
        if "NOT_FOUND" in str(exc) or "404" in str(exc):
            logger.debug("Cloud Task not found (already executed or deleted): %s", task_name)
        else:
            logger.warning("Failed to cancel Cloud Task %s: %s", task_name, exc)


async def schedule_nudge(
    task_id: str,
    fire_at: Optional[datetime] = None,
    project: Optional[str] = None,
    region: Optional[str] = None,
    service_url: Optional[str] = None,
) -> str:
    """Schedule a nudge Cloud Task for 1h after fire_at (or now)."""
    proj = project or os.environ.get("GCP_PROJECT_ID", "")
    reg = region or os.environ.get("GCP_REGION", "europe-central2")
    url = service_url or os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    q = os.environ.get("CLOUD_TASKS_NUDGES_QUEUE", NUDGE_QUEUE)

    nudge_at = (fire_at or datetime.now(tz=timezone.utc)) + timedelta(
        seconds=NUDGE_DELAY_SECONDS
    )
    ct_name = make_nudge_task_name(task_id, nudge_at)
    full_task_name = _build_task_name(proj, reg, q, ct_name)
    queue_path = _build_queue_path(proj, reg, q)

    payload = json.dumps({"task_id": task_id}).encode()

    from google.cloud import tasks_v2  # type: ignore
    from google.protobuf import timestamp_pb2  # type: ignore

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(nudge_at)

    task = {
        "name": full_task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{url}/internal/trigger-nudge",
            "headers": {"Content-Type": "application/json"},
            "body": payload,
            "oidc_token": {
                "service_account_email": f"cloud-tasks-sa@{proj}.iam.gserviceaccount.com",
            },
        },
        "schedule_time": ts,
    }

    client = _get_tasks_client()
    client.create_task(request={"parent": queue_path, "task": task})
    logger.info("Scheduled nudge Cloud Task: %s at %s", ct_name, nudge_at.isoformat())
    return ct_name


async def snooze_reminder(
    task_id: str,
    old_task_name: Optional[str],
    new_fire_at: datetime,
    db,
) -> str:
    """Atomically cancel old reminder and schedule new one.

    Returns the new Cloud Task name.
    """
    await cancel_reminder(old_task_name)
    new_ct_name = await schedule_reminder(task_id=task_id, fire_at=new_fire_at)

    # Update Firestore with new task name
    doc_ref = db.collection("tasks").document(task_id)
    await doc_ref.update(
        {
            "cloud_task_name": new_ct_name,
            "scheduled_time": new_fire_at,
            "updated_at": datetime.now(tz=timezone.utc),
        }
    )
    return new_ct_name


def make_checklist_task_name(session_id: str, trigger_type: str, fire_at: datetime) -> str:
    """Generate deterministic Cloud Task name for a checklist trigger."""
    return f"checklist-{trigger_type}-{session_id}-{int(fire_at.timestamp())}"


async def schedule_checklist_trigger(
    session_id: str,
    trigger_type: str,
    fire_at: datetime,
    project: Optional[str] = None,
    region: Optional[str] = None,
    service_url: Optional[str] = None,
) -> str:
    """Schedule a Cloud Task for a checklist evening or morning trigger.

    trigger_type: 'evening' or 'morning'
    Returns the Cloud Task name.
    """
    proj = project or os.environ.get("GCP_PROJECT_ID", "")
    reg = region or os.environ.get("GCP_REGION", "europe-central2")
    url = service_url or os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    q = os.environ.get("CLOUD_TASKS_REMINDERS_QUEUE", CHECKLIST_QUEUE)

    ct_name = make_checklist_task_name(session_id, trigger_type, fire_at)
    full_task_name = _build_task_name(proj, reg, q, ct_name)
    queue_path = _build_queue_path(proj, reg, q)

    payload = json.dumps({"session_id": session_id}).encode()
    schedule_time = fire_at if fire_at.tzinfo else fire_at.replace(tzinfo=timezone.utc)

    from google.cloud import tasks_v2  # type: ignore
    from google.protobuf import timestamp_pb2  # type: ignore

    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(schedule_time)

    task = {
        "name": full_task_name,
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{url}/internal/trigger-checklist-{trigger_type}",
            "headers": {"Content-Type": "application/json"},
            "body": payload,
            "oidc_token": {
                "service_account_email": f"cloud-tasks-sa@{proj}.iam.gserviceaccount.com",
            },
        },
        "schedule_time": ts,
    }

    client = _get_tasks_client()
    client.create_task(request={"parent": queue_path, "task": task})
    logger.info("Scheduled checklist %s Cloud Task: %s at %s", trigger_type, ct_name, fire_at.isoformat())
    return ct_name
