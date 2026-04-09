"""Singleton Firestore client."""

from __future__ import annotations

import os
from typing import Optional
from unittest.mock import MagicMock

_client: Optional[object] = None


def get_firestore_client():
    """Return singleton Firestore client. Uses mock in test environment."""
    global _client
    if _client is None:
        if os.environ.get("TESTING") == "1":
            _client = MagicMock()
        else:
            from google.cloud import firestore  # type: ignore
            project_id = os.environ.get("GCP_PROJECT_ID")
            _client = firestore.AsyncClient(project=project_id)
    return _client


def reset_firestore_client() -> None:
    """Reset singleton — used in tests."""
    global _client
    _client = None
