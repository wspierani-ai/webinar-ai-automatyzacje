# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projekt

ADHD Telegram Reminder Bot — asystent przypomnień dla osób z ADHD, zbudowany na GCP.

**Stack:**
- Backend: Python + FastAPI
- AI: Gemini 2.5 Flash (Vertex AI, region: `europe-central2`)
- Baza: Firestore (`users`, `tasks`, `processed_updates`, `stripe_events`, `oauth_states`, `admin_users`)
- Infra: GCP Cloud Run (`min-instances=1`), Cloud Tasks, Cloud Scheduler, Secret Manager, Cloud KMS
- Płatności: Stripe (29.99 PLN/mies.)
- Zewnętrzne API: Telegram Bot API, Google Calendar API, Google Tasks API, Google OAuth 2.0

Struktura docelowa: `adhd-bot/` — szczegoly w `docs/completed/adhd-telegram-reminder-bot/adhd-telegram-reminder-bot-kontekst.md`
Status: implementacja ukonczona (21 Units, 6 Faz, 285 testow). Wymaga setup GCP infra + deploy.

## Dev workflow

Pełny pipeline skills:
```
/dev-ideate → /dev-brainstorm → /dev-plan → /dev-docs → /dev-docs-execute ↔ /dev-docs-review → /dev-docs-complete → /dev-compound
```
Skrót: `/dev-autopilot` (orkiestruje cały pipeline).

## Komendy

```bash
# Testy
pytest adhd-bot/tests/ -v
pytest adhd-bot/tests/test_config.py -v      # pojedynczy plik

# Linting i formatowanie
ruff check adhd-bot/
ruff format adhd-bot/
ruff check --fix adhd-bot/

# Deploy
gcloud run deploy adhd-bot --region=europe-central2 --min-instances=1
```

## Sekrety (GCP Secret Manager)

Wszystkie sekrety w Secret Manager — **nigdy nie hardcoduj w kodzie**:
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SECRET_TOKEN`
- `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`
- `ADMIN_JWT_SECRET`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Cloud KMS: `projects/{proj}/locations/europe-central2/keyRings/adhd-bot/cryptoKeys/oauth-tokens`

Lokalnie: skopiuj `adhd-bot/.env.example` → `adhd-bot/.env` (gitignored).

## Konwencje

- **Język:** dokumentacja i komentarze w polskim; identyfikatory kodu w angielskim
- **Commity:** imperative mood, opcjonalnie prefix `docs:` / `feat:` / `fix:`
- **Branche:** `feature/*`, `fix/*` → `main`
- **Timezone:** `zoneinfo` (Python stdlib), **nie** `pytz`

## Gotchas

- `min-instances=1` — Cloud Run nie schodzi do 0, cold start niedopuszczalny dla Telegram webhook
- Deduplication Telegram updates: Firestore transaction (`processed_updates/{update_id}`, TTL 24h)
- Google OAuth tokeny szyfrowane przez Cloud KMS — raw token nigdy w Firestore
- Gemini confidence threshold `0.65` — poniżej brak `scheduled_time`, flow R3 (dopytaj usera)
- Grace period 3 dni po `payment_failed` — logika własna w Firestore, nie Stripe built-in
- Cloud Tasks naming: `reminder-{task_id}-{fire_at_unix}` — deterministyczny cancel bez przechowywania handle
