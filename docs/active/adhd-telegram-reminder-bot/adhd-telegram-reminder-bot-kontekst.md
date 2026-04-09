---
title: "ADHD Reminder Bot — Kontekst techniczny"
branch: feature/adhd-telegram-reminder-bot
status: active
created: 2026-04-09
last_updated: 2026-04-09
---

# ADHD Reminder Bot — Kontekst techniczny

**Branch:** `feature/adhd-telegram-reminder-bot`
**Ostatnia aktualizacja:** 2026-04-09 (Faza 3 zaimplementowana)

## Powiązane pliki źródłowe

| Plik | Rola |
|------|------|
| `docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md` | Requirements doc z `/dev-brainstorm` — wszystkie R1-R19 |
| `docs/plans/2026-04-09-001-feat-adhd-telegram-reminder-bot-plan.md` | Plan techniczny z `/dev-plan` — 21 Implementation Units |

## Struktura docelowa projektu

```
adhd-bot/
├── main.py                        # FastAPI app entry point
├── Dockerfile
├── requirements.txt
├── .env.example
├── cloud-run.yaml
├── firestore.rules
├── bot/
│   ├── config.py                  # env vars, fail-fast validation
│   ├── webhook.py                 # /telegram/webhook router
│   ├── handlers/
│   │   ├── command_handlers.py    # /start, /timezone, /morning, /delete_my_data
│   │   ├── message_handlers.py    # text + voice message flow
│   │   ├── callback_handlers.py   # inline button callbacks
│   │   ├── internal_triggers.py   # /internal/trigger-reminder, /internal/trigger-nudge
│   │   ├── cleanup_handler.py     # /internal/cleanup
│   │   ├── stripe_webhook_handler.py
│   │   ├── payment_command_handlers.py
│   │   ├── google_oauth_handler.py
│   │   ├── gtasks_polling_handler.py
│   │   └── checklist_command_handlers.py
│   ├── models/
│   │   ├── user.py
│   │   ├── task.py
│   │   └── checklist.py
│   ├── services/
│   │   ├── deduplication.py
│   │   ├── firestore_client.py    # singleton Firestore client
│   │   ├── ai_parser.py           # Gemini 2.5 Flash parser
│   │   ├── scheduler.py           # Cloud Tasks wrapper
│   │   ├── stripe_service.py
│   │   ├── google_auth.py         # OAuth + token refresh
│   │   ├── google_calendar.py
│   │   ├── google_tasks.py
│   │   ├── token_tracker.py
│   │   └── checklist_ai.py
│   ├── security/
│   │   ├── encryption.py          # Cloud KMS wrapper
│   │   ├── rate_limiter.py        # slowapi config
│   │   ├── headers.py             # security headers middleware
│   │   └── validators.py
│   └── admin/
│       ├── auth.py                # Google SSO + JWT session
│       ├── middleware.py          # require_admin dependency
│       ├── router.py              # /admin/* endpoints
│       └── queries.py             # Firestore queries dla metryk
├── templates/
│   ├── privacy_policy.html
│   └── admin/
│       ├── base.html
│       ├── dashboard.html
│       ├── users.html
│       └── user_detail.html
├── infra/
│   ├── firestore-indexes.json     # TTL policy
│   └── cloud-scheduler-cleanup.yaml
└── tests/
    ├── test_config.py
    ├── test_webhook_security.py
    ├── test_deduplication.py
    ├── test_user_model.py
    ├── test_task_state_machine.py
    ├── test_ai_parser.py
    ├── test_scheduler.py
    ├── test_internal_triggers.py
    ├── test_onboarding.py
    ├── test_task_capture.py
    ├── test_reminder_callbacks.py
    ├── test_nudge.py
    ├── test_cleanup.py
    ├── test_stripe_service.py
    ├── test_stripe_webhooks.py
    ├── test_google_auth.py
    ├── test_google_calendar.py
    ├── test_google_tasks.py
    ├── test_token_tracker.py
    ├── test_admin_auth.py
    ├── test_admin_queries.py
    ├── test_security.py
    ├── test_checklist_templates.py
    ├── test_checklist_session.py
    └── test_gdpr.py
```

## Architektura systemu

```
Telegram User
    ↓ (webhook + secret_token)
Cloud Run / FastAPI (europe-central2, min-instances=1)
    ├── Gemini 2.5 Flash (Vertex AI)  — parsowanie tekstu i głosu
    ├── Firestore                      — dane users/tasks, dedup, conversation state
    ├── Cloud Tasks                    — scheduled reminders i nudges
    ├── Stripe                         — subskrypcje i webhooks
    ├── Google Calendar API            — events CRUD (jednostronna sync)
    └── Google Tasks API               — tasks CRUD

Cloud Tasks       → Cloud Run /internal/trigger-reminder  → Telegram + GCal/GTasks
Cloud Tasks       → Cloud Run /internal/trigger-nudge     → Telegram
Stripe            → Cloud Run /stripe/webhook             → Firestore + Telegram
Cloud Scheduler   → Cloud Run /internal/cleanup           → Firestore + Cloud Tasks
Cloud Scheduler   → Cloud Run /internal/poll-google-tasks → Google Tasks API + Telegram
```

## Firestore — kolekcje

| Kolekcja | Opis | TTL |
|----------|------|-----|
| `users/{telegram_user_id}` | Dane usera, tokeny Google (zaszyfrowane), subscription status | Brak |
| `tasks/{task_id}` | Zadania z state machine, Cloud Task names, Google IDs | `expires_at` (TTL) — po COMPLETED/REJECTED +30 dni |
| `processed_updates/{update_id}` | Deduplication Telegram updates | `expires_at` 24h |
| `stripe_events/{event_id}` | Deduplication Stripe webhook events | Brak (koszty pomijalne) |
| `oauth_states/{state}` | Tymczasowe OAuth state tokens | TTL 10 min |
| `admin_users/{email}` | Whitelist adminów z rolami | Brak |
| `admin_audit_log/{id}` | Log akcji adminów | Brak (compliance) |
| `token_usage/{YYYY-MM-DD}/{user_id}` | Dzienne agregaty tokenów Gemini | Brak (analytics) |
| `checklist_templates/{template_id}` | Szablony checklist usera | Brak |
| `checklist_sessions/{session_id}` | Aktywne sesje checklist | `expires_at` po completed |

## Task State Machine

```
PENDING_CONFIRMATION
        ↓
    SCHEDULED
        ↓
    REMINDED ─────────→ COMPLETED
        ├──────────────→ REJECTED
        ↓               
     NUDGED ──────────→ COMPLETED
        ├──────────────→ REJECTED
        ↓
     SNOOZED
        ↓
    REMINDED (powrót)
```

Archiwizacja: przy COMPLETED/REJECTED ustawiany `expires_at = now() + 30 dni`. Firestore TTL auto-kasuje po tym czasie (z opóźnieniem do 24h).

## Kluczowe decyzje techniczne

| Decyzja | Wybór | Uzasadnienie |
|---------|-------|--------------|
| Runtime | Python FastAPI | python-telegram-bot v21 (async, najdojrzalszy), Vertex AI SDK dla Python |
| Deduplication | Firestore transaction (bez Redis) | Redis dodaje zależność infrastrukturalną — dla MVP Firestore wystarczy (<100ms) |
| Cloud Tasks naming | `reminder-{task_id}-{fire_at_unix}` | Deterministyczny format — cancel bez przechowywania handle |
| Grace period | Custom logika Firestore (nie Stripe built-in) | Stripe `payment_failed` → `grace_period_until = now() + 3d` w Firestore |
| Gemini confidence | Threshold 0.65 | `confidence < 0.65` → brak `scheduled_time` → R3 flow |
| "Jutro" definicja | Następny dzień od momentu wysłania | DST-aware przez `zoneinfo` (Python stdlib) |
| Google OAuth storage | Tokeny szyfrowane przez Cloud KMS | Plain text refresh_token w DB = krytyczne ryzyko bezpieczeństwa |
| Admin UI | Jinja2 + Tailwind CDN + Alpine.js | Jeden Cloud Run service, brak osobnego buildu frontendu |
| Admin auth | Google SSO (nie hasła) | JWT session cookie HttpOnly/Secure/SameSite=Strict, TTL 8h |
| Voice messages | Gemini obsługuje bez limitowania | Limit Telegrama = 60s. Jeden request: transkrypcja + parsowanie |

## Endpointy API

| Endpoint | Auth | Opis |
|----------|------|------|
| `POST /telegram/webhook` | `X-Telegram-Bot-Api-Secret-Token` | Odbiór Telegram updates |
| `POST /stripe/webhook` | Stripe signature | Eventy płatności |
| `GET /auth/google/callback` | OAuth state param | Callback OAuth Google |
| `POST /internal/trigger-reminder` | OIDC (Cloud Tasks SA) | Wysłanie remindera |
| `POST /internal/trigger-nudge` | OIDC | Wysłanie gentle nudge |
| `POST /internal/cleanup` | OIDC (Cloud Scheduler) | Czyszczenie expired data |
| `POST /internal/poll-google-tasks` | OIDC | Polling Google Tasks |
| `GET /admin/*` | JWT session cookie | Dashboard admin |
| `GET /health` | Brak | Health check |
| `GET /privacy` | Brak | Polityka prywatności (RODO) |

## Zależności między unitami

```
Unit 1 ─→ Unit 2 ─→ Unit 7
       └─→ Unit 3 ─→ Unit 4 ─→ Unit 15
                 └─→ Unit 5 ─→ Unit 8 ─→ Unit 9
                           └─→ Unit 10 ─→ Unit 11
       └─→ Unit 6 ─→ Unit 8

Unit 12 ─→ Unit 13
        └─→ Unit 14

Unit 16 ─→ Unit 17 ←─ Unit 15
                   ←─ Unit 11

Unit 19 ─→ Unit 20
Unit 3  ─→ Unit 21
```

## Zewnętrzne serwisy i konfiguracja

| Serwis | Co wymaga setup | Kiedy |
|--------|-----------------|-------|
| Telegram Bot API | BotFather: token, webhook URL, secret_token | Przed Unit 2 |
| GCP Project | Cloud Run, Cloud Tasks, Firestore, Vertex AI, Secret Manager, Cloud KMS | Przed Unit 1 |
| Vertex AI | Enable API, region europe-central2 | Przed Unit 4 |
| Stripe | Test mode: Price ID 29.99 PLN/mies., webhook endpoint | Przed Unit 11 |
| Google OAuth Client | OAuth 2.0 client dla Cloud Run redirect | Przed Unit 12 |
| Google APIs | Enable Calendar API + Tasks API | Przed Unit 13/14 |

## Rate limiting (Unit 18)

| Endpoint | Limit |
|----------|-------|
| `/telegram/webhook` | 30 req/min per IP |
| `/auth/google/callback` | 10 req/min per IP |
| `/admin/*` | 100 req/min per IP |
| `/stripe/webhook` | Unlimited (Stripe IPs whitelisted) |
| `/internal/*` | Unlimited (OIDC protected) |

## Secret Manager — lista sekretów

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_SECRET_TOKEN`
- `STRIPE_API_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `ADMIN_JWT_SECRET`
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
- Cloud KMS key: `projects/{proj}/locations/europe-central2/keyRings/adhd-bot/cryptoKeys/oauth-tokens`

## Status Faz

| Faza | Status | Data |
|------|--------|------|
| Faza 1 — Core Bot (Units 1-8) | ✅ Zaimplementowana | 2026-04-09 |
| Faza 2 — Polish (Units 9-10) | ✅ Zaimplementowana | 2026-04-09 |
| Faza 3 — Monetyzacja (Unit 11) | ✅ Zaimplementowana | 2026-04-09 |
| Faza 4 — Google Integration (Units 12-14) | ⬜ Do zrobienia | — |
| Faza 5 — Admin Dashboard + Security (Units 15-18) | ⬜ Do zrobienia | — |
| Faza 6 — Checklista + RODO (Units 19-21) | ⬜ Do zrobienia | — |

## Zmiany w Fazie 1 (2026-04-09)

### Stworzone pliki
- `adhd-bot/main.py` — FastAPI app, endpoint `/health`
- `adhd-bot/Dockerfile` — python:3.12-slim + gunicorn + uvicorn
- `adhd-bot/requirements.txt` — pinowane wersje
- `adhd-bot/.env.example` — szablon zmiennych środowiskowych
- `adhd-bot/cloud-run.yaml` — konfiguracja Cloud Run (min-instances=1, 512Mi, europe-central2)
- `adhd-bot/bot/config.py` — dataclass z fail-fast validation (`__post_init__`)
- `adhd-bot/bot/webhook.py` — webhook z security (token check → timestamp → dedup → routing)
- `adhd-bot/bot/services/firestore_client.py` — singleton Firestore client z TESTING mock
- `adhd-bot/bot/services/deduplication.py` — deduplication przez Firestore TTL
- `adhd-bot/bot/services/ai_parser.py` — Gemini 2.5 Flash parser (tekst + głos), JSON output
- `adhd-bot/bot/services/scheduler.py` — Cloud Tasks scheduler (schedule/cancel/snooze/nudge)
- `adhd-bot/bot/models/user.py` — User dataclass + get_or_create + is_subscription_active
- `adhd-bot/bot/models/task.py` — Task dataclass + TaskState enum + state machine + InvalidStateTransitionError
- `adhd-bot/bot/handlers/command_handlers.py` — /start, /timezone, /morning
- `adhd-bot/bot/handlers/message_handlers.py` — text + voice message handlers
- `adhd-bot/bot/handlers/callback_handlers.py` — snooze/done/reject/confirm callbacks
- `adhd-bot/bot/handlers/internal_triggers.py` — /internal/trigger-reminder + /internal/trigger-nudge

### Testy (106 testów, wszystkie przechodzą)
- `tests/test_config.py` — 8 testów
- `tests/test_health.py` — 2 testy
- `tests/test_webhook_security.py` — 6 testów
- `tests/test_deduplication.py` — 5 testów
- `tests/test_user_model.py` — 9 testów
- `tests/test_task_state_machine.py` — 22 testy
- `tests/test_ai_parser.py` — 13 testów
- `tests/test_scheduler.py` — 8 testów
- `tests/test_internal_triggers.py` — 5 testów
- `tests/test_onboarding.py` — 14 testów
- `tests/test_task_capture.py` — 5 testów
- `tests/test_reminder_callbacks.py` — 9 testów

### Kluczowe decyzje implementacyjne
- Firestore client używa `TESTING=1` env var do mockowania w testach (bez google-cloud-firestore jako dev dep)
- Cloud Tasks i google.cloud.tasks_v2 mockowane przez `sys.modules` patch w testach
- `get_firestore_client` importowany na poziomie modułu w `internal_triggers.py` (nie wewnątrz funkcji)
- Testy callback_handlers używają `db._task_doc_ref` i `db._user_doc_ref` do dokładniejszych asercji

## Review Fazy 1 — re-run cykl 2 (weryfikacja naprawy P2) (2026-04-09)

**Wynik:** ✅ GOTOWE DO KONTYNUACJI — P1=0, P2=0, P3=3  
**Raport:** `docs/active/adhd-telegram-reminder-bot/review-faza-1.md`

### P2 z cyklu 1 re-run — naprawione ✅
- `user.py:126` — zmienione z `except Exception:` na `except (ImportError, AttributeError, TypeError):` — ✅ ZWERYFIKOWANE
  - Naprawa skuteczna: nie łapie już `Aborted`, `DeadlineExceeded`, `PermissionDenied` z Firestore SDK
  - 106 testów przechodzi po zmianie
  - Race condition w produkcji zabezpieczone

### Łącznie naprawione P2 (8/8)
- hmac.compare_digest() w webhook.py — ✅
- OIDC auth na /internal/* — ✅
- MagicMock poza kodem produkcyjnym w firestore_client.py — ✅
- Atomiczna transakcja get_or_create w user.py — ✅
- Routery podpięte w main.py, routing w _route_update — ✅
- infra/firestore-indexes.json stworzony — ✅
- TestSnooze30Min + TestSnooze2h mają asercje — ✅
- `except Exception:` zbyt szeroki w user.py:126 — ✅

### Pozostałe P3 (nieblokujące — do rozważenia w Fazie 2)
- `TELEGRAM_BASE_URL` zduplikowany w 3 plikach — wyciągnij do config.py
- `CloudTasksClient` bez singleton w scheduler.py
- `vertexai.init()` przy każdym parsowaniu w ai_parser.py

### Kluczowe wnioski

Faza 1 jest gotowa do kontynuacji. Wszystkie P2 naprawione. Implementacja jest funkcjonalna end-to-end z prawidłową security (hmac, OIDC), transakcjami atomicznymi, idempotency guards i pokryciem testów.

**Dobre wzorce do kontynuacji:**
- State machine z explicit `ALLOWED_TRANSITIONS` + typed errors — dobry wzorzec
- Graceful fallback w `ai_parser.py` — poprawny
- Idempotency guards w trigger-reminder/nudge — poprawne
- Deduplication przez Firestore TTL bez Redis — właściwa decyzja dla MVP

## Zmiany w Fazie 2 (2026-04-09)

### Stworzone pliki
- `adhd-bot/bot/handlers/cleanup_handler.py` — /internal/cleanup endpoint (OIDC auth, expired subscriptions, orphaned Cloud Tasks)
- `adhd-bot/infra/cloud-scheduler-cleanup.yaml` — Cloud Scheduler cron 0 3 * * * Europe/Warsaw
- `adhd-bot/tests/test_nudge.py` — 9 testów Nudge System (Unit 9)
- `adhd-bot/tests/test_cleanup.py` — 9 testów Auto-Archival + Cleanup (Unit 10)

### Zmodyfikowane pliki
- `adhd-bot/main.py` — podpięty cleanup_router
- `adhd-bot/infra/firestore-indexes.json` — dodany TTL fieldOverride dla `tasks.expires_at`

### Testy (124 testy łącznie, wszystkie przechodzą)
- `tests/test_nudge.py` — 9 testów (happy path + idempotency guards dla wszystkich stanów)
- `tests/test_cleanup.py` — 9 testów (trial expiry, grace_period expiry, orphaned tasks, empty data, 401 auth)

### Kluczowe decyzje implementacyjne
- `cancel_reminder` importowany na poziomie modułu w `cleanup_handler.py` (umożliwia mockowanie w testach)
- Cleanup jest idempotentny — bezpieczne do wielokrotnego wywołania
- Każda z 3 faz cleanup (trial, grace_period, orphaned tasks) jest niezależnie obsługiwana z osobnym try/except

## Review Fazy 2 (2026-04-09)

**Wynik:** ⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI — P1=0, P2=3, P3=4  
**Raport:** `docs/active/adhd-telegram-reminder-bot/review-faza-2.md`

### P2 — wymagają naprawy

- `cleanup_handler.py:55` + `internal_triggers.py:46` — `except Exception` zbyt szeroki w `_verify_oidc_token` — maskuje błędy konfiguracji jako 401; należy zawęzić do `GoogleAuthError`, `TransportError`, `ValueError`
- `cleanup_handler.py:106-111` — natychmiastowe blokowanie `grace_period` usera gdy `grace_period_until is None` bez logu warning; ryzyko silent blocking po Unit 11 Stripe integration
- `cleanup_handler.py:148-167` — N+1 Firestore writes: 2 oddzielne `.update()` dla cloud_task_name i nudge_task_name zamiast jednego wywołania; przy skali → timeout cleanup jobu

## Review Fazy 2 — re-run cykl 1 (weryfikacja naprawy P2) (2026-04-10)

**Wynik:** ✅ GOTOWE DO KONTYNUACJI — P1=0, P2=0, P3=4  
**Raport:** `docs/active/adhd-telegram-reminder-bot/review-faza-2.md`

### P2 z cyklu 0 re-run — naprawione ✅

- `cleanup_handler.py:56` + `internal_triggers.py:47` — zmienione z `except Exception:` na `except (GoogleAuthError, TransportError, ValueError):` — ✅ ZWERYFIKOWANE
  - Import przeniesiony wewnątrz bloku try (lazy import) — wzorzec spójny z Fazą 1
- `cleanup_handler.py:106-112` — dodano `logger.warning(...)` + zmieniono natychmiastowy block na `continue` (skip) — ✅ ZWERYFIKOWANE
  - Użytkownik z `grace_period_until is None` nie jest już blokowany, lecz logowany jako warning
- `cleanup_handler.py:149-160` — scalone dwa oddzielne `.update()` w jeden `update_data: dict` builder z jednym `doc.reference.update(update_data)` — ✅ ZWERYFIKOWANE
  - N+1 writes → 1 write per task; count prawidłowo inkrementowany jeden raz per task

### Łącznie naprawione P2 (3/3)
- `except Exception` w OIDC verify (cleanup_handler + internal_triggers) — ✅
- `grace_period_until is None` → log warning + skip zamiast immediate block — ✅
- N+1 Firestore writes → scalony do 1 update per task — ✅

### Pozostałe P3 (nieblokujące — do rozważenia w Unit 18)
- Duplikacja `_verify_oidc_token` w 2 plikach — odłożone do Unit 18 Security Hardening
- `TELEGRAM_BASE_URL` carry-over z Fazy 1 — nadal nienaprawione (P3)
- Brak testów dla PENDING_CONFIRMATION i SCHEDULED w test_nudge.py
- Brak testu dla task z oboma cloud_task_name + nudge_task_name w test_cleanup.py

### P3 — odłożone do Unit 18 lub kolejnej fazy

- Duplikacja `_verify_oidc_token` w 2 plikach (cleanup_handler + internal_triggers) — wyciągnąć w Unit 18
- `TELEGRAM_BASE_URL` carry-over z Fazy 1 (P3 nadal otwarty)
- Brak testów dla stanów PENDING_CONFIRMATION i SCHEDULED w test_nudge.py
- Brak testu dla task z oboma cloud_task_name + nudge_task_name w test_cleanup.py

### Kluczowe wnioski

Faza 2 jest gotowa do kontynuacji z zastrzeżeniami. Implementacja idempotentna i poprawna funkcjonalnie. Główne P2 są w obszarze error handling (zbyt szeroki except) i performance (N+1 writes). Nie ma regresji w stosunku do Fazy 1.

**Dobre wzorce potwierdzone:**
- State-based idempotency guards w trigger-nudge — spójne z Fazą 1
- Niezależne try/except dla każdej fazy cleanup — poprawna izolacja błędów
- YAML z komentarzem deploy CLI — dobra dokumentacja infra
- Cleanup idempotentny — bezpieczny do wielokrotnego wywołania

## Zmiany w Fazie 3 (2026-04-09)

### Stworzone pliki
- `adhd-bot/bot/services/stripe_service.py` — Stripe Customer, Checkout Session, event deduplication, event handlers (4 eventy)
- `adhd-bot/bot/handlers/stripe_webhook_handler.py` — `/stripe/webhook` endpoint z weryfikacją sygnatury, deduplication, routing
- `adhd-bot/bot/handlers/payment_command_handlers.py` — /subscribe (tworzy Checkout Session) + /billing (status subskrypcji)
- `adhd-bot/tests/test_stripe_service.py` — 14 testów serwisu Stripe
- `adhd-bot/tests/test_stripe_webhooks.py` — 12 testów webhook handlera

### Zmodyfikowane pliki
- `adhd-bot/main.py` — podpięty stripe_router
- `adhd-bot/bot/handlers/command_handlers.py` — routing /subscribe i /billing

### Testy (152 testy łącznie, wszystkie przechodzą)
- `tests/test_stripe_service.py` — 14 testów (Customer create/get, Checkout Session PLN, deduplication, 4 event handlers)
- `tests/test_stripe_webhooks.py` — 12 testów (signature verification, deduplication, event routing, blocked user)

### Kluczowe decyzje implementacyjne
- Stripe Customer tworzony lazy (przy /subscribe, nie przy /start) — mniej Stripe API calls dla trial userów
- Deduplication przez `stripe_events/{event_id}` — mark-before-handle (write before processing), spójny wzorzec z telegram dedup
- TESTING=1 mode pomija weryfikację sygnatury Stripe — umożliwia testy bez prawdziwego webhook secret
- `handle_invoice_payment_failed` szuka usera po `stripe_customer_id` — obsługuje eventy bez telegram_user_id w metadata
- Grace period: 3 dni po `invoice.payment_failed`, cleanup job (Unit 10) blokuje po wygaśnięciu

## Źródła

- Requirements doc: `docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md`
- Plan techniczny: `docs/plans/2026-04-09-001-feat-adhd-telegram-reminder-bot-plan.md`
