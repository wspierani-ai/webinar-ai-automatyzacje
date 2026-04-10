"""Checklist models: ChecklistTemplate and ChecklistSession dataclasses."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

MAX_CHECKLIST_ITEMS = 12


class ChecklistValidationError(Exception):
    """Raised when checklist validation fails."""


@dataclass
class ChecklistItem:
    text: str
    checked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "checked": self.checked}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChecklistItem":
        return cls(text=data["text"], checked=data.get("checked", False))


@dataclass
class ChecklistTemplate:
    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: int = 0
    name: str = ""
    items: list[str] = field(default_factory=list)
    evening_enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def validate(self) -> None:
        """Validate template constraints. Raises ChecklistValidationError."""
        if len(self.items) > MAX_CHECKLIST_ITEMS:
            raise ChecklistValidationError(
                f"Szablon nie moze miec wiecej niz {MAX_CHECKLIST_ITEMS} elementow "
                f"(podano {len(self.items)})"
            )
        if not self.name.strip():
            raise ChecklistValidationError("Nazwa szablonu nie moze byc pusta")

    def to_firestore_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "user_id": self.user_id,
            "name": self.name,
            "items": self.items,
            "evening_enabled": self.evening_enabled,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, Any]) -> "ChecklistTemplate":
        return cls(
            template_id=data["template_id"],
            user_id=data.get("user_id", 0),
            name=data.get("name", ""),
            items=data.get("items", []),
            evening_enabled=data.get("evening_enabled", True),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    async def save(self, db) -> None:
        """Persist template to Firestore."""
        now = datetime.now(tz=timezone.utc)
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now
        self.validate()
        doc_ref = db.collection("checklist_templates").document(self.template_id)
        await doc_ref.set(self.to_firestore_dict())

    async def delete(self, db) -> None:
        """Delete template from Firestore."""
        doc_ref = db.collection("checklist_templates").document(self.template_id)
        await doc_ref.delete()


@dataclass
class ChecklistSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: int = 0
    template_id: str = ""
    template_name: str = ""
    items: list[ChecklistItem] = field(default_factory=list)
    event_time: Optional[datetime] = None
    evening_reminder_time: Optional[datetime] = None
    morning_reminder_time: Optional[datetime] = None
    evening_message_id: Optional[int] = None
    morning_message_id: Optional[int] = None
    cloud_task_name_evening: Optional[str] = None
    cloud_task_name_morning: Optional[str] = None
    state: str = "pending_evening"  # pending_evening | evening_sent | morning_sent | completed
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @property
    def unchecked_items(self) -> list[tuple[int, ChecklistItem]]:
        """Return list of (index, item) for unchecked items."""
        return [(i, item) for i, item in enumerate(self.items) if not item.checked]

    @property
    def all_checked(self) -> bool:
        return all(item.checked for item in self.items) if self.items else False

    def to_firestore_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "template_id": self.template_id,
            "template_name": self.template_name,
            "items": [item.to_dict() for item in self.items],
            "event_time": self.event_time,
            "evening_reminder_time": self.evening_reminder_time,
            "morning_reminder_time": self.morning_reminder_time,
            "evening_message_id": self.evening_message_id,
            "morning_message_id": self.morning_message_id,
            "cloud_task_name_evening": self.cloud_task_name_evening,
            "cloud_task_name_morning": self.cloud_task_name_morning,
            "state": self.state,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, Any]) -> "ChecklistSession":
        items_raw = data.get("items", [])
        items = [ChecklistItem.from_dict(i) for i in items_raw]
        return cls(
            session_id=data["session_id"],
            user_id=data.get("user_id", 0),
            template_id=data.get("template_id", ""),
            template_name=data.get("template_name", ""),
            items=items,
            event_time=data.get("event_time"),
            evening_reminder_time=data.get("evening_reminder_time"),
            morning_reminder_time=data.get("morning_reminder_time"),
            evening_message_id=data.get("evening_message_id"),
            morning_message_id=data.get("morning_message_id"),
            cloud_task_name_evening=data.get("cloud_task_name_evening"),
            cloud_task_name_morning=data.get("cloud_task_name_morning"),
            state=data.get("state", "pending_evening"),
            created_at=data.get("created_at"),
            expires_at=data.get("expires_at"),
        )

    async def save(self, db) -> None:
        """Persist session to Firestore."""
        if self.created_at is None:
            self.created_at = datetime.now(tz=timezone.utc)
        doc_ref = db.collection("checklist_sessions").document(self.session_id)
        await doc_ref.set(self.to_firestore_dict())
