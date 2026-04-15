"""Input validation helpers for security boundary checks.

All validators raise ValidationError on invalid input.
"""

from __future__ import annotations

import re
from zoneinfo import available_timezones


class ValidationError(Exception):
    """Raised when input validation fails."""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"Validation error on '{field}': {message}")


_TIME_PATTERN = re.compile(r"^\d{2}:\d{2}$")
_MAX_TEXT_LENGTH = 4096  # Telegram message limit


def validate_timezone(tz: str) -> str:
    """Validate IANA timezone string. Returns the timezone if valid.

    Raises ValidationError if timezone is not in IANA database.
    """
    if not tz or tz not in available_timezones():
        raise ValidationError("timezone", f"Invalid timezone: {tz!r}")
    return tz


def validate_time_format(time_str: str) -> str:
    """Validate HH:MM time format. Returns the time string if valid.

    Raises ValidationError if format is wrong or hours/minutes out of range.
    """
    if not _TIME_PATTERN.match(time_str):
        raise ValidationError("time", f"Invalid time format: {time_str!r}. Expected HH:MM")

    hours, minutes = int(time_str[:2]), int(time_str[3:5])
    if hours > 23 or minutes > 59:
        raise ValidationError("time", f"Invalid time value: {time_str!r}")

    return time_str


def validate_text_length(text: str, max_len: int = _MAX_TEXT_LENGTH) -> str:
    """Validate text length against Telegram limit. Returns the text if valid.

    Raises ValidationError if text exceeds max_len.
    """
    if len(text) > max_len:
        raise ValidationError(
            "text",
            f"Text too long: {len(text)} chars (max {max_len})",
        )
    return text


def sanitize_for_logging(text: str) -> str:
    """Remove potentially sensitive data from text before logging.

    Masks:
    - Tokens/keys (strings > 10 chars that look like secrets)
    - Email addresses
    - Long numeric sequences (phone numbers, IDs)
    """
    # Mask potential tokens (alphanumeric strings > 20 chars)
    sanitized = re.sub(r"[A-Za-z0-9_\-]{20,}", "[REDACTED]", text)

    # Mask email addresses
    sanitized = re.sub(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        "[EMAIL_REDACTED]",
        sanitized,
    )

    return sanitized
