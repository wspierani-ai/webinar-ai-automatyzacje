"""Google OAuth 2.0 handler.

Endpoints:
- GET  /connect-google     (called from Telegram via /connect-google command)
- GET  /auth/google/callback
- GET  /disconnect-google  (called from Telegram via /disconnect-google command)

The /connect-google and /disconnect-google are also accessible as Telegram
bot commands through the webhook → command_handlers routing. These HTTP
endpoints are used when accessed directly (e.g. via browser redirect or
direct API call).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from bot.security.rate_limiter import limiter
from bot.services.firestore_client import get_firestore_client
from bot.services.google_auth import (
    build_oauth_url,
    disconnect_google,
    exchange_code_for_tokens,
    generate_oauth_state,
    save_tokens,
    verify_oauth_state,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_TELEGRAM_BASE_URL = "https://api.telegram.org"


def _get_redirect_uri(request: Request) -> str:
    """Build the OAuth callback redirect URI from the request base URL."""
    base_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "")
    if base_url:
        return f"{base_url}/auth/google/callback"
    # Fallback: derive from request
    return str(request.base_url).rstrip("/") + "/auth/google/callback"


async def _send_telegram_message(telegram_user_id: int, text: str) -> None:
    """Send a Telegram message. No-op in test environments."""
    if os.environ.get("TESTING") == "1":
        return

    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    url = f"{_TELEGRAM_BASE_URL}/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={"chat_id": telegram_user_id, "text": text, "parse_mode": "HTML"},
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.error("Failed to send Telegram message to %s: %s", telegram_user_id, exc)


async def handle_connect_google(message: dict, db) -> None:
    """Telegram command handler for /connect-google."""
    telegram_user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    state = await generate_oauth_state(db, telegram_user_id)

    # Build redirect URI from env
    base_url = os.environ.get("CLOUD_RUN_SERVICE_URL", "https://example.com")
    redirect_uri = f"{base_url}/auth/google/callback"
    oauth_url = build_oauth_url(state, redirect_uri)

    text = (
        "🔗 <b>Połącz konto Google</b>\n\n"
        "Kliknij link poniżej, aby autoryzować dostęp do Google Calendar i Google Tasks:\n\n"
        f'<a href="{oauth_url}">Połącz z Google</a>\n\n'
        "Link wygaśnie za 10 minut."
    )
    await _send_telegram_message(chat_id, text)


async def handle_disconnect_google(message: dict, db) -> None:
    """Telegram command handler for /disconnect-google."""
    telegram_user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]

    await disconnect_google(db, telegram_user_id)

    text = (
        "✅ Konto Google zostało odłączone.\n\n"
        "Twoje zadania nie będą już synchronizowane z Google Calendar i Google Tasks.\n"
        "Aby ponownie połączyć, użyj /connect-google."
    )
    await _send_telegram_message(chat_id, text)


@router.get("/auth/google/callback")
@limiter.limit("10/minute")
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> HTMLResponse:
    """Handle Google OAuth 2.0 callback."""
    db = get_firestore_client()

    if error:
        logger.warning("OAuth callback received error: %s", error)
        return HTMLResponse(
            content=_html_response("Błąd autoryzacji", "Autoryzacja odrzucona przez Google."),
            status_code=400,
        )

    if not state or not code:
        return HTMLResponse(
            content=_html_response("Błąd", "Brakujące parametry autoryzacji."),
            status_code=400,
        )

    telegram_user_id = await verify_oauth_state(db, state)
    if telegram_user_id is None:
        return HTMLResponse(
            content=_html_response(
                "Błąd autoryzacji",
                "Link autoryzacji jest nieprawidłowy lub wygasł. Użyj /connect-google ponownie.",
            ),
            status_code=400,
        )

    redirect_uri = _get_redirect_uri(request)

    try:
        token_data = await exchange_code_for_tokens(code, redirect_uri)
    except ValueError as exc:
        logger.error("Token exchange failed for user %s: %s", telegram_user_id, exc)
        return HTMLResponse(
            content=_html_response("Błąd", "Nie udało się wymienić kodu autoryzacji."),
            status_code=400,
        )

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token or not refresh_token:
        logger.error(
            "Token exchange returned incomplete data for user %s", telegram_user_id
        )
        return HTMLResponse(
            content=_html_response(
                "Błąd",
                "Nie otrzymano wymaganych tokenów. Spróbuj ponownie z /connect-google.",
            ),
            status_code=400,
        )

    # Fetch calendar and tasks list IDs
    calendar_id, tasks_list_id = await _fetch_google_resource_ids(access_token)

    await save_tokens(
        db,
        telegram_user_id,
        access_token,
        refresh_token,
        expires_in,
        google_calendar_id=calendar_id,
        google_tasks_list_id=tasks_list_id,
    )

    await _send_telegram_message(
        telegram_user_id,
        "✅ Konto Google połączone! Od teraz twoje zadania będą synchronizowane z "
        "Google Calendar i Google Tasks.",
    )

    return HTMLResponse(
        content=_html_response(
            "Połączono!",
            "Połączono z Google! Możesz zamknąć tę kartę i wrócić do Telegram.",
        )
    )


async def _fetch_google_resource_ids(access_token: str) -> tuple[str, str]:
    """Fetch primary calendar ID and default tasks list ID.

    Returns ("primary", "@default") as fallback on any error.
    """
    import httpx

    headers = {"Authorization": f"Bearer {access_token}"}
    calendar_id = "primary"
    tasks_list_id = "@default"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Get primary calendar
            cal_resp = await client.get(
                "https://www.googleapis.com/calendar/v3/users/me/calendarList/primary",
                headers=headers,
            )
            if cal_resp.status_code == 200:
                calendar_id = cal_resp.json().get("id", "primary")

            # Get first tasks list
            tasks_resp = await client.get(
                "https://www.googleapis.com/tasks/v1/users/@me/lists",
                headers=headers,
            )
            if tasks_resp.status_code == 200:
                items = tasks_resp.json().get("items", [])
                if items:
                    tasks_list_id = items[0].get("id", "@default")
    except Exception as exc:
        logger.warning("Failed to fetch Google resource IDs: %s", exc)

    return calendar_id, tasks_list_id


def _html_response(title: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <title>{title}</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 60px 20px; color: #333; }}
    h1 {{ font-size: 2rem; margin-bottom: 1rem; }}
    p {{ font-size: 1.1rem; color: #555; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>{message}</p>
</body>
</html>"""
