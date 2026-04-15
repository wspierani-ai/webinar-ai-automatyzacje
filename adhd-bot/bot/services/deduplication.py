"""Telegram update deduplication via Firestore."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


async def is_duplicate(db, update_id: int) -> bool:
    """Return True if update_id was already processed."""
    doc_ref = db.collection("processed_updates").document(str(update_id))
    doc = await doc_ref.get()
    return doc.exists


async def mark_processed(db, update_id: int) -> None:
    """Mark update_id as processed with 24h TTL."""
    doc_ref = db.collection("processed_updates").document(str(update_id))
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=24)
    await doc_ref.set(
        {
            "update_id": update_id,
            "processed_at": datetime.now(tz=timezone.utc),
            "expires_at": expires_at,
        }
    )
