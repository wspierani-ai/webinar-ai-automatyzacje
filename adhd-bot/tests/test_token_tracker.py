"""Tests for bot.services.token_tracker — Gemini token usage tracking."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_SECRET_TOKEN", "test-secret")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("CLOUD_RUN_SERVICE_URL", "https://test.run.app")

from bot.services.token_tracker import _calculate_cost_pln, record_usage


class TestCalculateCostPln:
    """Test cost calculation logic."""

    def test_known_token_counts_produce_correct_cost(self):
        """1000 input + 1000 output tokens produce expected PLN cost."""
        cost = _calculate_cost_pln(1000, 1000)
        # input: 1000 * 0.30/1_000_000 * 4.0 = 0.0012
        # output: 1000 * 2.50/1_000_000 * 4.0 = 0.01
        expected = 0.0012 + 0.01
        assert abs(cost - expected) < 1e-9

    def test_zero_tokens_produce_zero_cost(self):
        cost = _calculate_cost_pln(0, 0)
        assert cost == 0.0

    def test_large_token_count(self):
        """1M input + 1M output tokens."""
        cost = _calculate_cost_pln(1_000_000, 1_000_000)
        expected = 1.2 + 10.0
        assert abs(cost - expected) < 1e-6


class TestRecordUsage:
    """Test record_usage Firestore integration."""

    @pytest.fixture
    def mock_db(self):
        db = MagicMock()
        mock_doc_ref = AsyncMock()
        mock_doc_ref.set = AsyncMock()
        # Chain: db.collection("token_usage").document(date).collection("users").document(uid)
        mock_users_col = MagicMock()
        mock_users_col.document.return_value = mock_doc_ref
        mock_date_doc = MagicMock()
        mock_date_doc.collection.return_value = mock_users_col
        mock_token_col = MagicMock()
        mock_token_col.document.return_value = mock_date_doc
        db.collection.return_value = mock_token_col
        return db

    async def test_records_correct_values_in_firestore(self, mock_db):
        """record_usage writes correct values to Firestore with merge=True."""
        await record_usage(mock_db, user_id=12345, input_tokens=100, output_tokens=50)

        mock_db.collection.assert_called_once_with("token_usage")
        # Get the final doc_ref that set was called on
        mock_token_col = mock_db.collection.return_value
        mock_date_doc = mock_token_col.document.return_value
        mock_users_col = mock_date_doc.collection.return_value
        mock_doc_ref = mock_users_col.document.return_value

        mock_users_col.document.assert_called_once_with("12345")
        mock_doc_ref.set.assert_awaited_once()
        call_args = mock_doc_ref.set.call_args
        data = call_args[0][0]
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50
        assert data["call_count"] == 1
        assert call_args[1]["merge"] is True

    async def test_cost_pln_calculated_correctly(self, mock_db):
        """Cost PLN in recorded data matches calculation."""
        await record_usage(mock_db, user_id=12345, input_tokens=1000, output_tokens=500)

        mock_token_col = mock_db.collection.return_value
        mock_date_doc = mock_token_col.document.return_value
        mock_users_col = mock_date_doc.collection.return_value
        mock_doc_ref = mock_users_col.document.return_value

        call_args = mock_doc_ref.set.call_args
        data = call_args[0][0]
        expected_cost = _calculate_cost_pln(1000, 500)
        assert abs(data["cost_pln"] - expected_cost) < 1e-9

    async def test_does_not_raise_when_firestore_unavailable(self):
        """record_usage gracefully handles Firestore errors."""
        mock_db = MagicMock()
        mock_db.collection.side_effect = Exception("Firestore unavailable")

        # Should not raise
        await record_usage(mock_db, user_id=12345, input_tokens=100, output_tokens=50)

    async def test_does_not_block_caller(self, mock_db):
        """record_usage completes within reasonable time."""
        import time

        start = time.monotonic()
        await record_usage(mock_db, user_id=12345, input_tokens=100, output_tokens=50)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0


class TestFireAndForgetIntegration:
    """Test that ai_parser fires token tracking without blocking."""

    async def test_parse_message_does_not_block_on_tracking(self):
        """parse_message returns a result even when token tracking is scheduled."""
        mock_response = MagicMock()
        mock_response.text = '{"content": "test", "scheduled_time_iso": null, "confidence": 0.5, "is_morning_snooze": false}'
        mock_usage = MagicMock()
        mock_usage.prompt_token_count = 100
        mock_usage.candidates_token_count = 50
        mock_response.usage_metadata = mock_usage

        mock_model = MagicMock()
        mock_model.generate_content_async = AsyncMock(return_value=mock_response)

        with (
            patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model),
            patch("bot.services.ai_parser.token_tracker.record_usage", new_callable=AsyncMock) as mock_record,
            patch("bot.services.ai_parser._fire_and_forget_token_tracking") as mock_fire,
        ):
            from bot.services.ai_parser import parse_message

            result = await parse_message("test task", user_id=12345)

            assert result.content == "test"
            # Verify that fire-and-forget was called with the response
            mock_fire.assert_called_once_with(mock_response, 12345)
