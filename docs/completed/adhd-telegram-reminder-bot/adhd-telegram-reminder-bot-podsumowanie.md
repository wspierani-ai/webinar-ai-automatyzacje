---
title: "ADHD Reminder Bot — Podsumowanie ukonczonego zadania"
branch: feature/adhd-telegram-reminder-bot
status: completed
created: 2026-04-09
completed: 2026-04-09
---

# ADHD Reminder Bot — Podsumowanie

**Data ukoncczenia:** 2026-04-09
**Branch:** `feature/adhd-telegram-reminder-bot`
**Testy:** 285 (wszystkie PASS)
**Lint:** clean (ruff)
**Fazy:** 6/6 zaimplementowanych
**Units:** 21/21 zaimplementowanych

## Co zostalo dostarczone

### Faza 1 — Core Bot (Units 1-8)
- Scaffold projektu Python/FastAPI z Dockerfile i Cloud Run config
- Telegram webhook z security (secret token, timestamp check, deduplication)
- Firestore data layer z explicit state machine (7 stanow, typed errors)
- Gemini 2.5 Flash parser (tekst + glos, polskie wyrazenia czasowe, DST-aware)
- Cloud Tasks scheduler (schedule/cancel/snooze z deterministic naming)
- Onboarding flow (/start, /timezone, /morning)
- Task capture flow (wiadomosc -> parse -> potwierdzenie -> schedule)
- Reminder delivery z inline buttons (3x snooze, done, reject)

### Faza 2 — Polish (Units 9-10)
- Nudge system (1h brak reakcji -> gentle nudge, dokladnie 1 per task)
- Auto-archival (Firestore TTL 30 dni) + cleanup job (03:00 daily)

### Faza 3 — Monetyzacja (Unit 11)
- Stripe subscription (7-day trial -> 29.99 PLN/mies.)
- Webhook handling (checkout.completed, payment_failed, payment_succeeded, subscription.deleted)
- Grace period 3 dni + blokada
- Billing Portal + Telegram notyfikacje przy problemach z platnoscia

### Faza 4 — Google Integration (Units 12-14)
- Google OAuth 2.0 z CSRF protection (state token, TTL 10 min, single-use)
- AES-256-GCM szyfrowanie tokenow Google
- Google Calendar sync (bot -> Calendar, jednostronna)
- Google Tasks sync (dwustronna: bot -> Tasks + polling Tasks -> bot co 5 min)

### Faza 5 — Admin Dashboard + Security (Units 15-18)
- Gemini token usage tracking (fire-and-forget, atomic Firestore increment)
- Admin auth (Google SSO, JWT session, role-based: admin/read-only)
- Admin dashboard (Jinja2 + Tailwind + Alpine.js + Chart.js): overview, users, user detail
- Security hardening: Cloud KMS encryption, rate limiting (slowapi), security headers, Firestore rules, input validators

### Faza 6 — Checklista + RODO (Units 19-21)
- Checklist templates (max 12 items, AI sugestie przez Gemini)
- Checklist sessions (wieczorny + poranny reminder, item callbacks, auto-zamkniecie)
- Event detection (Gemini klasyfikuje wiadomosci -> matching templateow)
- RODO: /delete_my_data (kaskadowe usuwanie + cancel Stripe + revoke Google)
- Polityka prywatnosci (statyczna strona /privacy)

## Kluczowe decyzje architektoniczne

| Decyzja | Wybor | Uzasadnienie |
|---------|-------|--------------|
| Runtime | Python FastAPI | python-telegram-bot v21 (async), Vertex AI SDK |
| Deduplication | Firestore transaction (bez Redis) | Mniej infra, <100ms dla MVP |
| Cloud Tasks naming | `reminder-{task_id}-{fire_at_unix}` | Deterministyczny cancel bez handle |
| Grace period | Custom logika Firestore (nie Stripe built-in) | Pelna kontrola nad UX |
| Gemini confidence | Threshold 0.65 | Ponizej -> dopytaj usera o czas |
| Google OAuth storage | AES-256-GCM (Cloud KMS) | Plain text refresh_token = ryzyko |
| Admin UI | Jinja2 + Tailwind CDN + Alpine.js | Jeden service, brak osobnego buildu |
| Admin auth | Google SSO + JWT (HttpOnly/Secure/SameSite) | Bez hasel, TTL 8h |
| Stripe Customer | Lazy creation (przy /subscribe) | Mniej API calls dla trial userow |
| Mark-after-handle | Stripe webhook dedup po sukcesie handlera | Reliability: retry mozliwy |

## Wzorce warte zachowania

1. **State machine z explicit ALLOWED_TRANSITIONS + typed errors** — `InvalidStateTransitionError` zamiast cichego bledu
2. **Idempotency guards w triggerach** — state check przed akcja, 200 bez efektu przy duplikacie
3. **Fire-and-forget pattern** — `asyncio.create_task()` dla non-critical tracking (token usage)
4. **Graceful no-op dla opcjonalnych integracji** — Google Calendar/Tasks skip gdy brak tokenu
5. **OIDC auth na /internal/* endpointach** — Cloud Tasks/Scheduler SA verification
6. **Snapshot isolation checklist** — items kopiowane przy tworzeniu sesji
7. **Cursor-based pagination** — admin queries z server-side .where() + .limit()
8. **CSRF protection** — X-Requested-With header check na admin write endpoints

## Napotkane pulapki i rozwiazania

1. **Mark-before-handle w webhook dedup** — Stripe event markowany przed handlerem, przy 500 trwale pomijany. Rozwiazanie: mark PO sukcesie.
2. **`except Exception` maskujacy bledy konfiguracji** — OIDC verify catch-all uniemozliwial diagnoze. Rozwiazanie: zawezenie do konkretnych typow.
3. **Synchroniczne Google API blokujace async loop** — `.execute()` w sync mode. Rozwiazanie: `asyncio.to_thread()`.
4. **N+1 Firestore writes w cleanup** — oddzielne update per pole. Rozwiazanie: scalony dict builder.
5. **Firestore transaction bez @async_transactional** — transakcja nie commitowana. Rozwiazanie: dekorator na wewnetrznej funkcji.
6. **`cryptography` brak w requirements.txt** — fallback do plain base64. Rozwiazanie: pin `cryptography==44.0.0`.
7. **SCHEDULED w completable_states** — state machine zabrania SCHEDULED -> COMPLETED. Rozwiazanie: usuniecie ze zbioru.
8. **Grace period blocking bez logu** — user blokowany cicho. Rozwiazanie: logger.warning + skip.

## Nieukonczone elementy (infrastruktura/weryfikacja)

Ponizsze wymagaja dostepu do GCP i nie sa czescia kodu:
- Secret Manager setup (5 sekretow)
- Cloud Tasks kolejki (reminders, nudges)
- Docker build + Cloud Run deploy
- Firestore TTL konfiguracja
- Google OAuth Client setup
- Google Calendar/Tasks API enable
- Stripe Price ID w Dashboard
- Cloud KMS key ring
- E2E weryfikacja na staging

## Znane P3 (nit) do rozwiazania w przyszlosci

- `TELEGRAM_BASE_URL` zduplikowany w 11 plikach — wyciagnac do `bot/config.py`
- `_verify_oidc_token` zduplikowana w 3 plikach — wyciagnac do `bot/security/oidc.py`
- `_send_message` zduplikowana w 5 handlerach — wyciagnac do `bot/services/telegram.py`
- `vertexai.init()` przy kazdym parsowaniu — singleton z guard
- `CloudTasksClient` bez singleton — wzorzec jak firestore_client.py
- Kilka `except Exception` zbyt szerokich w admin queries/auth
- Brak adresu kontaktowego w privacy_policy.html (Art. 13 RODO)

## Utworzone/zmodyfikowane pliki (glowne)

### Kod zrodlowy (adhd-bot/)
- `main.py`, `Dockerfile`, `requirements.txt`, `.env.example`, `cloud-run.yaml`
- `bot/config.py`, `bot/webhook.py`, `firestore.rules`
- `bot/models/` — user.py, task.py, checklist.py
- `bot/services/` — firestore_client.py, deduplication.py, ai_parser.py, scheduler.py, stripe_service.py, google_auth.py, google_calendar.py, google_tasks.py, token_tracker.py, checklist_ai.py, checklist_session.py
- `bot/handlers/` — command_handlers.py, message_handlers.py, callback_handlers.py, internal_triggers.py, cleanup_handler.py, stripe_webhook_handler.py, payment_command_handlers.py, google_oauth_handler.py, gtasks_polling_handler.py, checklist_command_handlers.py, checklist_callbacks.py, gdpr_handler.py
- `bot/security/` — encryption.py, rate_limiter.py, headers.py, validators.py
- `bot/admin/` — auth.py, middleware.py, router.py, queries.py
- `templates/` — privacy_policy.html, admin/base.html, admin/dashboard.html, admin/users.html, admin/user_detail.html
- `infra/` — firestore-indexes.json, cloud-scheduler-cleanup.yaml

### Testy (285 testow)
- test_config.py, test_health.py, test_webhook_security.py, test_deduplication.py
- test_user_model.py, test_task_state_machine.py, test_ai_parser.py
- test_scheduler.py, test_internal_triggers.py, test_onboarding.py
- test_task_capture.py, test_reminder_callbacks.py, test_nudge.py
- test_cleanup.py, test_stripe_service.py, test_stripe_webhooks.py
- test_google_auth.py, test_google_calendar.py, test_google_tasks.py
- test_token_tracker.py, test_admin_auth.py, test_admin_queries.py
- test_security.py, test_checklist_templates.py, test_checklist_session.py, test_gdpr.py

## Zrodla

- Requirements doc: `docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md`
- Plan techniczny: `docs/plans/2026-04-09-001-feat-adhd-telegram-reminder-bot-plan.md`
- Review raporty: `docs/completed/adhd-telegram-reminder-bot/review-faza-{1..6}.md`
