"""Tests for Cloud Tasks Scheduler — Unit 5."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from bot.services.scheduler import (
    cancel_reminder,
    make_reminder_task_name,
    make_nudge_task_name,
    schedule_reminder,
    snooze_reminder,
)


class TestTaskNameFormat:
    """Verify deterministic task name format."""

    def test_reminder_task_name_format(self):
        fire_at = datetime(2026, 4, 10, 17, 0, 0, tzinfo=timezone.utc)
        name = make_reminder_task_name("abc123", fire_at)
        assert name == f"reminder-abc123-{int(fire_at.timestamp())}"

    def test_nudge_task_name_format(self):
        fire_at = datetime(2026, 4, 10, 18, 0, 0, tzinfo=timezone.utc)
        name = make_nudge_task_name("abc123", fire_at)
        assert name == f"nudge-abc123-{int(fire_at.timestamp())}"

    def test_different_tasks_have_different_names(self):
        fire_at = datetime(2026, 4, 10, 17, 0, 0, tzinfo=timezone.utc)
        name1 = make_reminder_task_name("task-1", fire_at)
        name2 = make_reminder_task_name("task-2", fire_at)
        assert name1 != name2


class TestScheduleReminder:
    """Tests for schedule_reminder function."""

    @pytest.mark.asyncio
    async def test_creates_cloud_task_with_correct_schedule_time(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("GCP_REGION", "europe-central2")
        monkeypatch.setenv("CLOUD_RUN_SERVICE_URL", "https://test.run.app")
        monkeypatch.setenv("CLOUD_TASKS_REMINDERS_QUEUE", "reminders")

        mock_client = MagicMock()
        mock_client.create_task = MagicMock()

        mock_ts = MagicMock()
        mock_ts_class = MagicMock(return_value=mock_ts)
        mock_protobuf = MagicMock()
        mock_protobuf.Timestamp = mock_ts_class

        mock_tasks_v2 = MagicMock()
        mock_tasks_v2.HttpMethod.POST = "POST"

        with patch("bot.services.scheduler._get_tasks_client", return_value=mock_client), \
             patch.dict("sys.modules", {
                 "google": MagicMock(),
                 "google.cloud": MagicMock(),
                 "google.cloud.tasks_v2": mock_tasks_v2,
                 "google.protobuf": MagicMock(),
                 "google.protobuf.timestamp_pb2": mock_protobuf,
             }):
            fire_at = datetime(2026, 4, 10, 17, 0, 0, tzinfo=timezone.utc)
            result = await schedule_reminder("task-123", fire_at)

        assert "reminder-task-123" in result
        mock_client.create_task.assert_called_once()


class TestCancelReminder:
    """Tests for cancel_reminder function."""

    @pytest.mark.asyncio
    async def test_cancel_with_none_returns_without_error(self):
        # No exception should be raised
        await cancel_reminder(None)

    @pytest.mark.asyncio
    async def test_cancel_with_not_found_ignores_error(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("GCP_REGION", "europe-central2")
        monkeypatch.setenv("CLOUD_TASKS_REMINDERS_QUEUE", "reminders")

        mock_client = MagicMock()
        mock_client.delete_task = MagicMock(
            side_effect=Exception("NOT_FOUND: task does not exist")
        )

        with patch("bot.services.scheduler._get_tasks_client", return_value=mock_client):
            # Should NOT raise
            await cancel_reminder("reminder-abc123-1234567890")

    @pytest.mark.asyncio
    async def test_cancel_with_404_ignores_error(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("GCP_REGION", "europe-central2")
        monkeypatch.setenv("CLOUD_TASKS_REMINDERS_QUEUE", "reminders")

        mock_client = MagicMock()
        mock_client.delete_task = MagicMock(
            side_effect=Exception("404: resource not found")
        )

        with patch("bot.services.scheduler._get_tasks_client", return_value=mock_client):
            # Should NOT raise
            await cancel_reminder("reminder-abc123-1234567890")


class TestSnoozeReminder:
    """Tests for snooze_reminder — atomically cancel old + create new."""

    @pytest.mark.asyncio
    async def test_snooze_cancels_old_and_creates_new(self, monkeypatch):
        monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
        monkeypatch.setenv("GCP_REGION", "europe-central2")
        monkeypatch.setenv("CLOUD_RUN_SERVICE_URL", "https://test.run.app")
        monkeypatch.setenv("CLOUD_TASKS_REMINDERS_QUEUE", "reminders")

        new_fire_at = datetime.now(tz=timezone.utc) + timedelta(minutes=30)
        old_task_name = "reminder-task-123-1234567890"

        mock_client = MagicMock()
        mock_client.create_task = MagicMock()
        mock_client.delete_task = MagicMock()

        # Mock Firestore update
        doc_ref = AsyncMock()
        doc_ref.update = AsyncMock()
        collection_mock = MagicMock()
        collection_mock.document.return_value = doc_ref
        db = MagicMock()
        db.collection.return_value = collection_mock

        mock_ts = MagicMock()
        mock_protobuf = MagicMock()
        mock_protobuf.Timestamp = MagicMock(return_value=mock_ts)
        mock_tasks_v2 = MagicMock()
        mock_tasks_v2.HttpMethod.POST = "POST"

        with patch("bot.services.scheduler._get_tasks_client", return_value=mock_client), \
             patch.dict("sys.modules", {
                 "google": MagicMock(),
                 "google.cloud": MagicMock(),
                 "google.cloud.tasks_v2": mock_tasks_v2,
                 "google.protobuf": MagicMock(),
                 "google.protobuf.timestamp_pb2": mock_protobuf,
             }):
            new_name = await snooze_reminder("task-123", old_task_name, new_fire_at, db)

        assert "reminder-task-123" in new_name
        mock_client.delete_task.assert_called_once()
        mock_client.create_task.assert_called_once()
        doc_ref.update.assert_called_once()
