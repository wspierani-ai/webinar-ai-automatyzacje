"""Tests for Task State Machine — Unit 3."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from bot.models.task import Task, TaskState, InvalidStateTransitionError


class TestAllowedTransitions:
    """Verify all valid state transitions succeed."""

    def test_pending_confirmation_to_scheduled(self):
        task = Task(state=TaskState.PENDING_CONFIRMATION)
        task.transition(TaskState.SCHEDULED)
        assert task.state == TaskState.SCHEDULED

    def test_scheduled_to_reminded(self):
        task = Task(state=TaskState.SCHEDULED)
        task.transition(TaskState.REMINDED)
        assert task.state == TaskState.REMINDED

    def test_reminded_to_snoozed(self):
        task = Task(state=TaskState.REMINDED)
        task.transition(TaskState.SNOOZED)
        assert task.state == TaskState.SNOOZED

    def test_reminded_to_nudged(self):
        task = Task(state=TaskState.REMINDED)
        task.transition(TaskState.NUDGED)
        assert task.state == TaskState.NUDGED

    def test_reminded_to_completed(self):
        task = Task(state=TaskState.REMINDED)
        task.transition(TaskState.COMPLETED)
        assert task.state == TaskState.COMPLETED

    def test_reminded_to_rejected(self):
        task = Task(state=TaskState.REMINDED)
        task.transition(TaskState.REJECTED)
        assert task.state == TaskState.REJECTED

    def test_nudged_to_snoozed(self):
        task = Task(state=TaskState.NUDGED)
        task.transition(TaskState.SNOOZED)
        assert task.state == TaskState.SNOOZED

    def test_nudged_to_completed(self):
        task = Task(state=TaskState.NUDGED)
        task.transition(TaskState.COMPLETED)
        assert task.state == TaskState.COMPLETED

    def test_nudged_to_rejected(self):
        task = Task(state=TaskState.NUDGED)
        task.transition(TaskState.REJECTED)
        assert task.state == TaskState.REJECTED

    def test_snoozed_to_reminded(self):
        task = Task(state=TaskState.SNOOZED)
        task.transition(TaskState.REMINDED)
        assert task.state == TaskState.REMINDED


class TestInvalidTransitions:
    """Verify invalid transitions raise InvalidStateTransitionError."""

    def test_scheduled_to_completed_raises(self):
        task = Task(state=TaskState.SCHEDULED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.COMPLETED)

    def test_pending_to_reminded_raises(self):
        task = Task(state=TaskState.PENDING_CONFIRMATION)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.REMINDED)

    def test_completed_to_anything_raises(self):
        task = Task(state=TaskState.COMPLETED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.REMINDED)

    def test_rejected_to_anything_raises(self):
        task = Task(state=TaskState.REJECTED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.COMPLETED)

    def test_reminded_to_scheduled_raises(self):
        task = Task(state=TaskState.REMINDED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.SCHEDULED)

    def test_snoozed_to_completed_raises(self):
        task = Task(state=TaskState.SNOOZED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.COMPLETED)

    def test_nudged_to_pending_raises(self):
        task = Task(state=TaskState.NUDGED)
        with pytest.raises(InvalidStateTransitionError):
            task.transition(TaskState.PENDING_CONFIRMATION)


class TestArchivalMetadata:
    """Verify COMPLETED/REJECTED set expires_at and timestamps."""

    def test_completed_sets_expires_at_to_30_days(self):
        task = Task(state=TaskState.REMINDED)
        before = datetime.now(tz=timezone.utc)
        task.transition(TaskState.COMPLETED)
        after = datetime.now(tz=timezone.utc)

        assert task.expires_at is not None
        expected_min = before + timedelta(days=30)
        expected_max = after + timedelta(days=30)
        assert expected_min <= task.expires_at <= expected_max

    def test_completed_sets_completed_at(self):
        task = Task(state=TaskState.REMINDED)
        before = datetime.now(tz=timezone.utc)
        task.transition(TaskState.COMPLETED)
        after = datetime.now(tz=timezone.utc)

        assert task.completed_at is not None
        assert before <= task.completed_at <= after

    def test_rejected_sets_expires_at_to_30_days(self):
        task = Task(state=TaskState.REMINDED)
        before = datetime.now(tz=timezone.utc)
        task.transition(TaskState.REJECTED)
        after = datetime.now(tz=timezone.utc)

        assert task.expires_at is not None
        expected_min = before + timedelta(days=30)
        expected_max = after + timedelta(days=30)
        assert expected_min <= task.expires_at <= expected_max

    def test_rejected_sets_rejected_at(self):
        task = Task(state=TaskState.REMINDED)
        before = datetime.now(tz=timezone.utc)
        task.transition(TaskState.REJECTED)
        after = datetime.now(tz=timezone.utc)

        assert task.rejected_at is not None
        assert before <= task.rejected_at <= after

    def test_transition_does_not_set_expires_at_for_non_archive_state(self):
        task = Task(state=TaskState.PENDING_CONFIRMATION)
        task.transition(TaskState.SCHEDULED)
        assert task.expires_at is None
