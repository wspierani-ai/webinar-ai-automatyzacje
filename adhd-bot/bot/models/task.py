"""Task model with explicit state machine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional


class TaskState(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    SCHEDULED = "SCHEDULED"
    REMINDED = "REMINDED"
    NUDGED = "NUDGED"
    SNOOZED = "SNOOZED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


# Allowed state transitions
ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING_CONFIRMATION: {TaskState.SCHEDULED},
    TaskState.SCHEDULED: {TaskState.REMINDED},
    TaskState.REMINDED: {
        TaskState.SNOOZED,
        TaskState.NUDGED,
        TaskState.COMPLETED,
        TaskState.REJECTED,
    },
    TaskState.NUDGED: {
        TaskState.SNOOZED,
        TaskState.COMPLETED,
        TaskState.REJECTED,
    },
    TaskState.SNOOZED: {TaskState.REMINDED},
    TaskState.COMPLETED: set(),
    TaskState.REJECTED: set(),
}

ARCHIVE_STATES = {TaskState.COMPLETED, TaskState.REJECTED}
ARCHIVE_TTL_DAYS = 30


class InvalidStateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, from_state: TaskState, to_state: TaskState) -> None:
        super().__init__(
            f"Invalid state transition: {from_state.value} → {to_state.value}"
        )
        self.from_state = from_state
        self.to_state = to_state


@dataclass
class Task:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    telegram_user_id: int = 0
    content: str = ""
    state: TaskState = TaskState.PENDING_CONFIRMATION
    proposed_time: Optional[datetime] = None
    scheduled_time: Optional[datetime] = None
    is_morning_snooze: bool = False
    cloud_task_name: Optional[str] = None
    nudge_task_name: Optional[str] = None
    google_calendar_event_id: Optional[str] = None
    google_task_id: Optional[str] = None
    reminder_message_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    reminded_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    snoozed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def transition(self, new_state: TaskState) -> None:
        """Transition to a new state. Raises InvalidStateTransitionError if not allowed."""
        allowed = ALLOWED_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransitionError(self.state, new_state)

        now = datetime.now(tz=timezone.utc)
        self.state = new_state
        self.updated_at = now

        if new_state == TaskState.COMPLETED:
            self.completed_at = now
            self.expires_at = now + timedelta(days=ARCHIVE_TTL_DAYS)
        elif new_state == TaskState.REJECTED:
            self.rejected_at = now
            self.expires_at = now + timedelta(days=ARCHIVE_TTL_DAYS)
        elif new_state == TaskState.SNOOZED:
            self.snoozed_at = now
        elif new_state == TaskState.REMINDED:
            self.reminded_at = now

    def to_firestore_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "telegram_user_id": self.telegram_user_id,
            "content": self.content,
            "state": self.state.value,
            "proposed_time": self.proposed_time,
            "scheduled_time": self.scheduled_time,
            "is_morning_snooze": self.is_morning_snooze,
            "cloud_task_name": self.cloud_task_name,
            "nudge_task_name": self.nudge_task_name,
            "google_calendar_event_id": self.google_calendar_event_id,
            "google_task_id": self.google_task_id,
            "reminder_message_id": self.reminder_message_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "reminded_at": self.reminded_at,
            "completed_at": self.completed_at,
            "rejected_at": self.rejected_at,
            "snoozed_at": self.snoozed_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, Any]) -> "Task":
        return cls(
            task_id=data["task_id"],
            telegram_user_id=data.get("telegram_user_id", 0),
            content=data.get("content", ""),
            state=TaskState(data.get("state", TaskState.PENDING_CONFIRMATION.value)),
            proposed_time=data.get("proposed_time"),
            scheduled_time=data.get("scheduled_time"),
            is_morning_snooze=data.get("is_morning_snooze", False),
            cloud_task_name=data.get("cloud_task_name"),
            nudge_task_name=data.get("nudge_task_name"),
            google_calendar_event_id=data.get("google_calendar_event_id"),
            google_task_id=data.get("google_task_id"),
            reminder_message_id=data.get("reminder_message_id"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            reminded_at=data.get("reminded_at"),
            completed_at=data.get("completed_at"),
            rejected_at=data.get("rejected_at"),
            snoozed_at=data.get("snoozed_at"),
            expires_at=data.get("expires_at"),
        )

    async def save(self, db) -> None:
        """Persist task changes to Firestore."""
        self.updated_at = datetime.now(tz=timezone.utc)
        doc_ref = db.collection("tasks").document(self.task_id)
        await doc_ref.set(self.to_firestore_dict())
