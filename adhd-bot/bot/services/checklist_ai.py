"""Checklist AI service — Gemini suggestions for checklist items."""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash-001"
MAX_SUGGESTIONS = 8

SUGGEST_PROMPT_TEMPLATE = """
Zaproponuj do {max_items} rzeczy do zabrania/przygotowania przed: {template_name}.
Odpowiedz TYLKO jako JSON array stringow, po polsku.
Kazdy element to krotki opis (max 5 slow).
Przykład: ["Buty sportowe", "Recznik", "Bidon"]
"""


def _get_gemini_client():
    """Return Gemini GenerativeModel instance."""
    import vertexai  # type: ignore
    from vertexai.generative_models import GenerativeModel  # type: ignore

    project = os.environ.get("GCP_PROJECT_ID", "")
    region = os.environ.get("GCP_REGION", "europe-central2")
    vertexai.init(project=project, location=region)
    return GenerativeModel(GEMINI_MODEL)


async def suggest_items(
    template_name: str,
    max_items: int = MAX_SUGGESTIONS,
) -> list[str]:
    """Call Gemini to suggest checklist items for a given template name.

    Returns a list of strings (max max_items). Returns empty list on error.
    """
    try:
        prompt = SUGGEST_PROMPT_TEMPLATE.format(
            template_name=template_name,
            max_items=max_items,
        )

        model = _get_gemini_client()
        response = await model.generate_content_async(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.3,
            },
        )

        raw_text = response.text.strip()
        items = json.loads(raw_text)

        if not isinstance(items, list):
            logger.warning("Gemini returned non-list for suggest_items: %s", type(items))
            return []

        # Filter to strings and limit
        result = [str(item).strip() for item in items if isinstance(item, str) and item.strip()]
        return result[:max_items]

    except Exception as exc:  # noqa: BLE001
        logger.error("Gemini suggest_items failed: %s", exc)
        return []
