"""Tests for Telegram webhook security — Unit 2."""

from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from fastapi import FastAPI


def make_app() -> FastAPI:
    from bot.webhook import router
    app = FastAPI()
    app.include_router(router)
    return app


VALID_TOKEN = "test-secret-token"
VALID_UPDATE_ID = 12345


def _fresh_update(offset: int = 0) -> dict:
    """Build a fresh (non-stale) Telegram update."""
    return {
        "update_id": VALID_UPDATE_ID + offset,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "text": "hello",
            "chat": {"id": 111},
            "from": {"id": 111, "first_name": "Test"},
        },
    }


def _stale_update() -> dict:
    return {
        "update_id": VALID_UPDATE_ID + 999,
        "message": {
            "message_id": 2,
            "date": int(time.time()) - 200,
            "text": "old",
            "chat": {"id": 111},
            "from": {"id": 111, "first_name": "Test"},
        },
    }


@pytest.fixture
def env_with_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_SECRET_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("TESTING", "1")


@pytest.fixture
def mock_dedup_fresh():
    """Mock deduplication — update is NOT a duplicate."""
    with patch("bot.webhook.is_duplicate", new_callable=AsyncMock, return_value=False) as mock_is_dup, \
         patch("bot.webhook.mark_processed", new_callable=AsyncMock) as mock_mark, \
         patch("bot.webhook.get_firestore_client", return_value=MagicMock()):
        yield mock_is_dup, mock_mark


@pytest.fixture
def mock_dedup_duplicate():
    """Mock deduplication — update IS a duplicate."""
    with patch("bot.webhook.is_duplicate", new_callable=AsyncMock, return_value=True) as mock_is_dup, \
         patch("bot.webhook.mark_processed", new_callable=AsyncMock) as mock_mark, \
         patch("bot.webhook.get_firestore_client", return_value=MagicMock()):
        yield mock_is_dup, mock_mark


class TestWebhookSecurityToken:
    """Verify secret token validation."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self, env_with_token, mock_dedup_fresh):
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_fresh_update(),
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_wrong_token_returns_401(self, env_with_token, mock_dedup_fresh):
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_fresh_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token"},
            )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_correct_token_returns_200(self, env_with_token, mock_dedup_fresh):
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_fresh_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_TOKEN},
            )
        assert response.status_code == 200


class TestWebhookTimestamp:
    """Verify stale update handling."""

    @pytest.mark.asyncio
    async def test_stale_update_returns_200_silently(self, env_with_token, mock_dedup_fresh):
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_stale_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_TOKEN},
            )
        assert response.status_code == 200


class TestWebhookDeduplication:
    """Verify deduplication logic."""

    @pytest.mark.asyncio
    async def test_duplicate_update_id_returns_200_without_reprocessing(
        self, env_with_token, mock_dedup_duplicate
    ):
        mock_is_dup, mock_mark = mock_dedup_duplicate
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_fresh_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_TOKEN},
            )
        assert response.status_code == 200
        mock_mark.assert_not_called()

    @pytest.mark.asyncio
    async def test_new_update_id_creates_processed_document(
        self, env_with_token, mock_dedup_fresh
    ):
        mock_is_dup, mock_mark = mock_dedup_fresh
        app = make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/telegram/webhook",
                json=_fresh_update(),
                headers={"X-Telegram-Bot-Api-Secret-Token": VALID_TOKEN},
            )
        assert response.status_code == 200
        mock_mark.assert_called_once()
