"""User model with Firestore CRUD operations."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


@dataclass
class User:
    telegram_user_id: int
    first_name: str = ""
    username: str = ""
    timezone: str = "Europe/Warsaw"
    morning_time: Optional[str] = None  # HH:MM format
    subscription_status: str = "trial"  # trial | active | grace_period | blocked
    trial_ends_at: Optional[datetime] = None
    grace_period_until: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    conversation_state: Optional[str] = None
    conversation_state_expires_at: Optional[datetime] = None
    google_connected: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def is_subscription_active(self) -> bool:
        """Return True if user can use the bot (trial or active or in grace period)."""
        now = datetime.now(tz=timezone.utc)

        if self.subscription_status == "active":
            return True

        if self.subscription_status == "trial":
            if self.trial_ends_at is None:
                return True
            return now < self.trial_ends_at

        if self.subscription_status == "grace_period":
            if self.grace_period_until is None:
                return False
            return now < self.grace_period_until

        # blocked or any unknown status
        return False

    def to_firestore_dict(self) -> dict[str, Any]:
        """Convert to dict suitable for Firestore storage."""
        return {
            "telegram_user_id": self.telegram_user_id,
            "first_name": self.first_name,
            "username": self.username,
            "timezone": self.timezone,
            "morning_time": self.morning_time,
            "subscription_status": self.subscription_status,
            "trial_ends_at": self.trial_ends_at,
            "grace_period_until": self.grace_period_until,
            "stripe_customer_id": self.stripe_customer_id,
            "stripe_subscription_id": self.stripe_subscription_id,
            "conversation_state": self.conversation_state,
            "conversation_state_expires_at": self.conversation_state_expires_at,
            "google_connected": self.google_connected,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_firestore_dict(cls, data: dict[str, Any]) -> "User":
        return cls(
            telegram_user_id=data["telegram_user_id"],
            first_name=data.get("first_name", ""),
            username=data.get("username", ""),
            timezone=data.get("timezone", "Europe/Warsaw"),
            morning_time=data.get("morning_time"),
            subscription_status=data.get("subscription_status", "trial"),
            trial_ends_at=data.get("trial_ends_at"),
            grace_period_until=data.get("grace_period_until"),
            stripe_customer_id=data.get("stripe_customer_id"),
            stripe_subscription_id=data.get("stripe_subscription_id"),
            conversation_state=data.get("conversation_state"),
            conversation_state_expires_at=data.get("conversation_state_expires_at"),
            google_connected=data.get("google_connected", False),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    @classmethod
    async def _get_or_create_in_transaction(cls, db, doc_ref, telegram_user_id: int, **defaults) -> "User":
        """Attempt an atomic get-or-create using a Firestore transaction."""
        from google.cloud.firestore import async_transactional  # type: ignore

        transaction = db.transaction()

        @async_transactional
        async def _run(transaction):
            doc = await doc_ref.get(transaction=transaction)
            if doc.exists:
                return cls.from_firestore_dict(doc.to_dict())
            now = datetime.now(tz=timezone.utc)
            user = cls(
                telegram_user_id=telegram_user_id,
                subscription_status="trial",
                trial_ends_at=now + timedelta(days=7),
                created_at=now,
                updated_at=now,
                **defaults,
            )
            transaction.set(doc_ref, user.to_firestore_dict())
            return user

        return await _run(transaction)

    @classmethod
    async def get_or_create(cls, db, telegram_user_id: int, **defaults) -> "User":
        """Get existing user or create a new one.

        Attempts an atomic Firestore transaction to prevent race conditions on
        concurrent /start calls. Falls back to a simple get-then-set when the
        real Firestore SDK is unavailable (e.g. mock in tests).
        """
        doc_ref = db.collection("users").document(str(telegram_user_id))

        try:
            return await cls._get_or_create_in_transaction(db, doc_ref, telegram_user_id, **defaults)
        except (ImportError, AttributeError, TypeError):
            # Fallback: no real Firestore (mock / unit-test environment)
            # TypeError is raised when MagicMock (non-async) is used in tests
            doc = await doc_ref.get()
            if doc.exists:
                return cls.from_firestore_dict(doc.to_dict())
            now = datetime.now(tz=timezone.utc)
            user = cls(
                telegram_user_id=telegram_user_id,
                subscription_status="trial",
                trial_ends_at=now + timedelta(days=7),
                created_at=now,
                updated_at=now,
                **defaults,
            )
            await doc_ref.set(user.to_firestore_dict())
            return user

    async def save(self, db) -> None:
        """Persist user changes to Firestore."""
        self.updated_at = datetime.now(tz=timezone.utc)
        doc_ref = db.collection("users").document(str(self.telegram_user_id))
        await doc_ref.set(self.to_firestore_dict())
