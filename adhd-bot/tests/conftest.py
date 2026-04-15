"""Global pytest configuration and fixtures."""

from __future__ import annotations


import pytest


@pytest.fixture(autouse=True)
def set_testing_env(monkeypatch):
    """Set TESTING=1 for all tests to prevent real network calls."""
    monkeypatch.setenv("TESTING", "1")
