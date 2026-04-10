"""Gemini token usage tracking — fire-and-forget recording to Firestore.

Records per-user per-day token usage with atomic increments.
Used by ai_parser.py after each Gemini call.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Vertex AI pricing (USD) * approximate PLN/USD rate
_INPUT_COST_PER_TOKEN_PLN = 0.30 / 1_000_000 * 4.0
_OUTPUT_COST_PER_TOKEN_PLN = 2.50 / 1_000_000 * 4.0


def _calculate_cost_pln(input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in PLN for given token counts."""
    return (
        input_tokens * _INPUT_COST_PER_TOKEN_PLN
        + output_tokens * _OUTPUT_COST_PER_TOKEN_PLN
    )


def _make_increment(value):
    """Create a Firestore Increment transform, or return raw value in tests."""
    if os.environ.get("TESTING") == "1":
        return value
    from google.cloud.firestore_v1 import transforms  # type: ignore

    return transforms.Increment(value)


async def record_usage(
    db,
    user_id: int,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Record token usage to Firestore with atomic increment.

    Fire-and-forget: catches all exceptions to never block the caller.
    Path: token_usage/{YYYY-MM-DD}/users/{user_id}
    """
    try:
        now = datetime.now(tz=timezone.utc)
        date_key = now.strftime("%Y-%m-%d")
        cost_pln = _calculate_cost_pln(input_tokens, output_tokens)

        doc_ref = (
            db.collection("token_usage")
            .document(date_key)
            .collection("users")
            .document(str(user_id))
        )

        await doc_ref.set(
            {
                "input_tokens": _make_increment(input_tokens),
                "output_tokens": _make_increment(output_tokens),
                "call_count": _make_increment(1),
                "cost_pln": _make_increment(cost_pln),
                "updated_at": now,
            },
            merge=True,
        )
        logger.debug(
            "Recorded token usage for user %s: in=%d out=%d cost=%.6f PLN",
            user_id,
            input_tokens,
            output_tokens,
            cost_pln,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to record token usage for user %s: %s", user_id, exc)
