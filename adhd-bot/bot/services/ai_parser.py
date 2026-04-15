"""Gemini AI parser: text + voice → structured task."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from bot.services import token_tracker

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash-001"
CONFIDENCE_THRESHOLD = 0.65

PARSE_PROMPT_TEMPLATE = """
Jesteś asystentem parsującym wiadomości po polsku do zadań/przypomnień.

Aktualna data i czas (strefa: {timezone}): {current_datetime}

Wiadomość do parsowania: "{message}"

Odpowiedz TYLKO JSON (bez markdown) według schematu:
{{
  "content": "treść zadania bez informacji o czasie",
  "scheduled_time_iso": "ISO 8601 datetime z timezone lub null jeśli brak pewności",
  "confidence": 0.0-1.0,
  "is_morning_snooze": true/false,
  "event_type": "task" | "event_with_preparation" | null
}}

Zasady:
- content: czysta treść zadania, bez dat/czasu
- scheduled_time_iso: null gdy confidence < {threshold}
- confidence: pewność co do czasu (0.0 = brak informacji, 1.0 = pełna pewność)
- is_morning_snooze: true gdy użytkownik mówi "jutro rano" lub "rano" bez konkretnej godziny
- Wyrażenia względne: "za 2 godziny", "jutro", "w piątek" → oblicz względem current_datetime
- Strefa czasowa: {timezone} (uwzględnij DST)
- event_type: "event_with_preparation" gdy wiadomość dotyczy treningu, wyjścia, podróży, spotkania poza domem, wydarzenia wymagającego zabrania rzeczy (np. siłownia, basen, wyjazd, lotnisko). "task" dla zwykłych zadań. null gdy nie można określić.
"""


@dataclass
class ParsedTask:
    content: Optional[str]
    scheduled_time: Optional[datetime]
    confidence: float
    is_morning_snooze: bool = False
    event_type: Optional[str] = None  # "task" | "event_with_preparation" | None

    @property
    def has_time(self) -> bool:
        return self.scheduled_time is not None and self.confidence >= CONFIDENCE_THRESHOLD


def _get_gemini_client():
    """Return Gemini GenerativeModel instance."""
    import vertexai  # type: ignore
    from vertexai.generative_models import GenerativeModel  # type: ignore

    project = os.environ.get("GCP_PROJECT_ID", "")
    region = os.environ.get("GCP_REGION", "europe-central2")
    vertexai.init(project=project, location=region)
    return GenerativeModel(GEMINI_MODEL)


def _parse_gemini_response(raw_text: str, user_timezone: str) -> ParsedTask:
    """Parse raw Gemini JSON response into ParsedTask."""
    data = json.loads(raw_text.strip())
    content = data.get("content") or None
    confidence = float(data.get("confidence", 0.0))
    is_morning_snooze = bool(data.get("is_morning_snooze", False))

    scheduled_time: Optional[datetime] = None
    raw_time = data.get("scheduled_time_iso")
    if raw_time and confidence >= CONFIDENCE_THRESHOLD:
        try:
            dt = datetime.fromisoformat(raw_time)
            if dt.tzinfo is None:
                tz = ZoneInfo(user_timezone)
                dt = dt.replace(tzinfo=tz)
            scheduled_time = dt.astimezone(timezone.utc)
        except (ValueError, KeyError) as exc:
            logger.warning("Failed to parse scheduled_time_iso '%s': %s", raw_time, exc)

    event_type = data.get("event_type") or None
    if event_type not in ("task", "event_with_preparation", None):
        event_type = None

    return ParsedTask(
        content=content,
        scheduled_time=scheduled_time,
        confidence=confidence,
        is_morning_snooze=is_morning_snooze,
        event_type=event_type,
    )


async def parse_message(
    text: str,
    user_timezone: str = "Europe/Warsaw",
    user_id: int = 0,
) -> ParsedTask:
    """Parse a text message via Gemini → ParsedTask.

    Returns ParsedTask(content=None, confidence=0.0) on any Gemini error.
    """
    try:
        tz = ZoneInfo(user_timezone)
        now = datetime.now(tz=tz)
        prompt = PARSE_PROMPT_TEMPLATE.format(
            timezone=user_timezone,
            current_datetime=now.isoformat(),
            message=text,
            threshold=CONFIDENCE_THRESHOLD,
        )

        model = _get_gemini_client()
        response = await model.generate_content_async(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        )

        _fire_and_forget_token_tracking(response, user_id)

        return _parse_gemini_response(response.text, user_timezone)

    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini parse_message failed: %s", exc)
        return ParsedTask(content=None, scheduled_time=None, confidence=0.0)


async def parse_voice_message(
    audio_bytes: bytes,
    user_timezone: str = "Europe/Warsaw",
    mime_type: str = "audio/ogg",
    user_id: int = 0,
) -> ParsedTask:
    """Parse a voice message via Gemini → ParsedTask.

    Sends raw audio bytes directly to Gemini (transcription + parsing in one request).
    Returns ParsedTask(content=None, confidence=0.0) on any error.
    """
    try:
        from vertexai.generative_models import Part  # type: ignore

        tz = ZoneInfo(user_timezone)
        now = datetime.now(tz=tz)
        prompt = PARSE_PROMPT_TEMPLATE.format(
            timezone=user_timezone,
            current_datetime=now.isoformat(),
            message="[wiadomość głosowa — treść w załączonym audio]",
            threshold=CONFIDENCE_THRESHOLD,
        )

        audio_part = Part.from_data(data=audio_bytes, mime_type=mime_type)

        model = _get_gemini_client()
        response = await model.generate_content_async(
            [audio_part, prompt],
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.0,
            },
        )

        _fire_and_forget_token_tracking(response, user_id)

        return _parse_gemini_response(response.text, user_timezone)

    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini parse_voice_message failed: %s", exc)
        return ParsedTask(content=None, scheduled_time=None, confidence=0.0)


def _fire_and_forget_token_tracking(response, user_id: int) -> None:
    """Extract usage metadata from Gemini response and track asynchronously."""
    if user_id == 0:
        return

    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return

        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0

        if input_tokens == 0 and output_tokens == 0:
            return

        from bot.services.firestore_client import get_firestore_client

        db = get_firestore_client()
        asyncio.create_task(
            token_tracker.record_usage(db, user_id, input_tokens, output_tokens)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule token tracking: %s", exc)
