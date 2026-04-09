"""Tests for Telegram update deduplication — Unit 2."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.deduplication import is_duplicate, mark_processed


def _make_db(doc_exists: bool) -> MagicMock:
    """Create a mock Firestore db."""
    db = MagicMock()
    doc_mock = AsyncMock()
    doc_mock.exists = doc_exists

    doc_ref = AsyncMock()
    doc_ref.get = AsyncMock(return_value=doc_mock)
    doc_ref.set = AsyncMock()

    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_ref

    db.collection.return_value = collection_mock
    return db, doc_ref


class TestIsDuplicate:
    """Test deduplication check."""

    @pytest.mark.asyncio
    async def test_returns_true_when_update_already_processed(self):
        db, _ = _make_db(doc_exists=True)
        result = await is_duplicate(db, 12345)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_update_not_yet_processed(self):
        db, _ = _make_db(doc_exists=False)
        result = await is_duplicate(db, 12345)
        assert result is False


class TestMarkProcessed:
    """Test marking update as processed."""

    @pytest.mark.asyncio
    async def test_creates_document_with_update_id(self):
        db, doc_ref = _make_db(doc_exists=False)
        await mark_processed(db, 99999)

        doc_ref.set.assert_called_once()
        call_args = doc_ref.set.call_args[0][0]
        assert call_args["update_id"] == 99999

    @pytest.mark.asyncio
    async def test_document_has_expires_at_field(self):
        db, doc_ref = _make_db(doc_exists=False)
        await mark_processed(db, 99999)

        call_args = doc_ref.set.call_args[0][0]
        assert "expires_at" in call_args
        assert call_args["expires_at"] > datetime.now(tz=timezone.utc)

    @pytest.mark.asyncio
    async def test_document_has_processed_at_field(self):
        db, doc_ref = _make_db(doc_exists=False)
        await mark_processed(db, 99999)

        call_args = doc_ref.set.call_args[0][0]
        assert "processed_at" in call_args
