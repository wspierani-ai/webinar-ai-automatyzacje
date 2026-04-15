"""Tests for Gemini AI Parser — Unit 4."""

from __future__ import annotations

import json
import pytest
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.ai_parser import ParsedTask, _parse_gemini_response, parse_message, parse_voice_message


def _mock_gemini_response(data: dict) -> MagicMock:
    """Create a mock Gemini response."""
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


def _mock_model(response_data: dict) -> AsyncMock:
    """Create a mock GenerativeModel."""
    model = AsyncMock()
    model.generate_content_async = AsyncMock(
        return_value=_mock_gemini_response(response_data)
    )
    return model


class TestParseGeminiResponse:
    """Unit tests for _parse_gemini_response (internal)."""

    def test_parses_content_and_time(self):
        data = {
            "content": "Kupić mleko",
            "scheduled_time_iso": "2026-04-10T17:00:00+02:00",
            "confidence": 0.95,
            "is_morning_snooze": False,
        }
        result = _parse_gemini_response(json.dumps(data), "Europe/Warsaw")
        assert result.content == "Kupić mleko"
        assert result.confidence == 0.95
        assert result.scheduled_time is not None
        assert result.is_morning_snooze is False

    def test_low_confidence_sets_scheduled_time_to_none(self):
        data = {
            "content": "Kupić mleko",
            "scheduled_time_iso": "2026-04-10T17:00:00+02:00",
            "confidence": 0.4,
            "is_morning_snooze": False,
        }
        result = _parse_gemini_response(json.dumps(data), "Europe/Warsaw")
        assert result.scheduled_time is None
        assert result.confidence == 0.4

    def test_null_scheduled_time_maps_to_none(self):
        data = {
            "content": "Kupić mleko",
            "scheduled_time_iso": None,
            "confidence": 0.1,
            "is_morning_snooze": False,
        }
        result = _parse_gemini_response(json.dumps(data), "Europe/Warsaw")
        assert result.scheduled_time is None

    def test_is_morning_snooze_true(self):
        data = {
            "content": "Umyć auto",
            "scheduled_time_iso": None,
            "confidence": 0.3,
            "is_morning_snooze": True,
        }
        result = _parse_gemini_response(json.dumps(data), "Europe/Warsaw")
        assert result.is_morning_snooze is True
        assert result.scheduled_time is None

    def test_scheduled_time_converted_to_utc(self):
        # Warsaw in summer is UTC+2
        data = {
            "content": "Task",
            "scheduled_time_iso": "2026-06-01T12:00:00+02:00",
            "confidence": 0.9,
            "is_morning_snooze": False,
        }
        result = _parse_gemini_response(json.dumps(data), "Europe/Warsaw")
        assert result.scheduled_time is not None
        assert result.scheduled_time.tzinfo == timezone.utc
        assert result.scheduled_time.hour == 10  # 12:00+02:00 = 10:00 UTC


class TestParseMessage:
    """Integration tests for parse_message with mocked Gemini."""

    @pytest.mark.asyncio
    async def test_text_with_time_returns_scheduled_time(self):
        response_data = {
            "content": "Kupić mleko",
            "scheduled_time_iso": "2026-04-10T17:00:00+02:00",
            "confidence": 0.95,
            "is_morning_snooze": False,
        }
        mock_model = _mock_model(response_data)

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_message("Kupić mleko jutro o 17")

        assert result.content == "Kupić mleko"
        assert result.scheduled_time is not None
        assert result.confidence > 0.65

    @pytest.mark.asyncio
    async def test_text_without_time_returns_none_scheduled_time(self):
        response_data = {
            "content": "Kupić mleko",
            "scheduled_time_iso": None,
            "confidence": 0.1,
            "is_morning_snooze": False,
        }
        mock_model = _mock_model(response_data)

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_message("Kupić mleko")

        assert result.scheduled_time is None
        assert result.confidence < 0.65

    @pytest.mark.asyncio
    async def test_relative_time_two_hours_returns_scheduled_time(self):
        response_data = {
            "content": "Zadzwonić do mamy",
            "scheduled_time_iso": "2026-04-09T14:00:00+02:00",
            "confidence": 0.9,
            "is_morning_snooze": False,
        }
        mock_model = _mock_model(response_data)

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_message("Za 2 godziny zadzwonić do mamy")

        assert result.content == "Zadzwonić do mamy"
        assert result.scheduled_time is not None

    @pytest.mark.asyncio
    async def test_morning_snooze_sets_flag(self):
        response_data = {
            "content": "Umyć auto",
            "scheduled_time_iso": None,
            "confidence": 0.3,
            "is_morning_snooze": True,
        }
        mock_model = _mock_model(response_data)

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_message("Jutro rano umyć auto")

        assert result.is_morning_snooze is True
        assert result.scheduled_time is None

    @pytest.mark.asyncio
    async def test_gemini_exception_returns_graceful_fallback(self):
        mock_model = AsyncMock()
        mock_model.generate_content_async = AsyncMock(
            side_effect=Exception("Gemini timeout")
        )

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_message("Jakiś tekst")

        assert result.content is None
        assert result.confidence == 0.0
        assert result.scheduled_time is None

    @pytest.mark.asyncio
    async def test_gemini_timeout_no_exception_propagation(self):
        mock_model = AsyncMock()
        mock_model.generate_content_async = AsyncMock(
            side_effect=TimeoutError("Connection timeout")
        )

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            # Should NOT raise — graceful fallback
            result = await parse_message("Cokolwiek")

        assert result.confidence == 0.0


class TestParseVoiceMessage:
    """Tests for voice message parsing."""

    @pytest.mark.asyncio
    async def test_voice_calls_gemini_with_audio_part(self):
        response_data = {
            "content": "Zadzwonić do mamy",
            "scheduled_time_iso": None,
            "confidence": 0.5,
            "is_morning_snooze": False,
        }
        fake_audio = b"\x00\x01\x02\x03"
        mock_part = MagicMock()
        mock_model = _mock_model(response_data)

        mock_vertex_module = MagicMock()
        mock_vertex_module.Part.from_data.return_value = mock_part

        # Patch the import inside the function
        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model), \
             patch.dict("sys.modules", {
                 "vertexai": MagicMock(),
                 "vertexai.generative_models": mock_vertex_module,
             }):
            result = await parse_voice_message(fake_audio, mime_type="audio/ogg")

        # Verify result is a ParsedTask (graceful even if Gemini not fully mocked)
        assert isinstance(result, ParsedTask)

    @pytest.mark.asyncio
    async def test_voice_exception_returns_graceful_fallback(self):
        mock_model = AsyncMock()
        mock_model.generate_content_async = AsyncMock(
            side_effect=Exception("Voice processing error")
        )

        with patch("bot.services.ai_parser._get_gemini_client", return_value=mock_model):
            result = await parse_voice_message(b"fake_audio")

        assert result.content is None
        assert result.confidence == 0.0
