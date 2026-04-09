---
title: "ADHD Reminder Bot — Zadania"
branch: feature/adhd-telegram-reminder-bot
status: active
created: 2026-04-09
last_updated: 2026-04-09
---

# ADHD Reminder Bot — Zadania

**Branch:** `feature/adhd-telegram-reminder-bot`
**Ostatnia aktualizacja:** 2026-04-09

---

## Faza 1 — Core Bot (Units 1-8)

### Unit 1: GCP Infrastructure + Project Scaffold

- [ ] Stwórz `adhd-bot/main.py` (FastAPI app entry point, endpoint `/health`)
- [ ] Stwórz `adhd-bot/Dockerfile` (python:3.12-slim, gunicorn + uvicorn)
- [ ] Stwórz `adhd-bot/requirements.txt` z pinowanymi wersjami
- [ ] Stwórz `adhd-bot/.env.example`
- [ ] Stwórz `adhd-bot/cloud-run.yaml` (min-instances=1, 512Mi, europe-central2)
- [ ] Stwórz `adhd-bot/bot/__init__.py`
- [ ] Stwórz `adhd-bot/bot/config.py` (dataclass, `__post_init__` fail-fast validation)
- [ ] Stwórz `adhd-bot/bot/handlers/__init__.py`
- [ ] Stwórz `adhd-bot/bot/models/__init__.py`
- [ ] Stwórz `adhd-bot/bot/services/__init__.py`
- [ ] Stwórz `adhd-bot/tests/__init__.py`
- [ ] Stwórz `adhd-bot/tests/test_config.py`
- [ ] Skonfiguruj Secret Manager: TELEGRAM_BOT_TOKEN, TELEGRAM_SECRET_TOKEN, STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, GCP_PROJECT_ID
- [ ] Utwórz dwie Cloud Tasks kolejki: `reminders`, `nudges`
- [ ] Test: Config validation rzuca `ValueError` gdy brakuje wymaganego env vara
- [ ] Test: Config poprawnie ładuje zmienne z environment
- [ ] Test: `/health` zwraca `{"status": "healthy"}` z kodem 200
- [ ] Weryfikacja: `docker build` kończy się sukcesem
- [ ] Weryfikacja: `gcloud run deploy --min-instances=1` kończy się sukcesem
- [ ] Weryfikacja: `/health` zwraca 200 na Cloud Run URL

---

### Unit 2: Telegram Webhook Receiver + Security + Deduplication

- [ ] Stwórz `adhd-bot/bot/webhook.py` (FastAPI router dla `/telegram/webhook`)
- [ ] Stwórz `adhd-bot/bot/services/deduplication.py` (`is_duplicate` + `mark_processed`)
- [ ] Stwórz `adhd-bot/bot/services/firestore_client.py` (singleton Firestore client)
- [ ] Stwórz `adhd-bot/tests/test_webhook_security.py`
- [ ] Stwórz `adhd-bot/tests/test_deduplication.py`
- [ ] Zaimplementuj webhook: kolejność (1) token check → (2) timestamp check → (3) dedup → (4) routing
- [ ] Test: Request bez `X-Telegram-Bot-Api-Secret-Token` → 401
- [ ] Test: Request z błędnym secret token → 401
- [ ] Test: Request z poprawnym tokenem → 200
- [ ] Test: Update z `message.date` starszym niż 120s → 200 (odrzucony cicho)
- [ ] Test: Duplicate `update_id` → 200, `mark_processed` nie wywoływany drugi raz
- [ ] Test: Nowy `update_id` → dokument tworzony w `processed_updates`
- [ ] Weryfikacja: Telegram `/setWebhook` z `secret_token` zwraca success
- [ ] Weryfikacja: Testowy update od Telegram dociera i jest procesowany

---

### Unit 3: Firestore Data Layer + Task State Machine

- [ ] Stwórz `adhd-bot/bot/models/user.py` (User dataclass + `get_or_create` + `is_subscription_active`)
- [ ] Stwórz `adhd-bot/bot/models/task.py` (Task dataclass + `TaskState` enum + `transition` + `InvalidStateTransitionError`)
- [ ] Stwórz `adhd-bot/tests/test_user_model.py`
- [ ] Stwórz `adhd-bot/tests/test_task_state_machine.py`
- [ ] Test: `task.transition(PENDING_CONFIRMATION → SCHEDULED)` → sukces
- [ ] Test: `task.transition(SCHEDULED → COMPLETED)` → rzuca `InvalidStateTransitionError`
- [ ] Test: `task.transition(REMINDED → COMPLETED)` → `expires_at = now() + 30d`, `completed_at` ustawiony
- [ ] Test: `task.transition(REMINDED → REJECTED)` → `expires_at = now() + 30d`, `rejected_at` ustawiony
- [ ] Test: `User.get_or_create` tworzy nowego usera z `timezone="Europe/Warsaw"`, `subscription_status="trial"`
- [ ] Test: `User.get_or_create` zwraca istniejącego usera bez nadpisania pól
- [ ] Test: `User.is_subscription_active()` → `False` gdy `subscription_status="blocked"`
- [ ] Test: `User.is_subscription_active()` → `False` gdy `subscription_status="trial"` i `trial_ends_at < now()`
- [ ] Weryfikacja: State machine testy obejmują 100% macierzy przejść (valid i invalid)
- [ ] Weryfikacja: Firestore CRUD działa na Firestore emulatorze (lokalnie)

---

### Unit 4: Gemini AI Parser (tekst + głos → structured task)

- [ ] Stwórz `adhd-bot/bot/services/ai_parser.py` (`ParsedTask` dataclass + `parse_message` + `parse_voice_message`)
- [ ] Stwórz `adhd-bot/tests/test_ai_parser.py`
- [ ] Zaimplementuj JSON schema output mode (`response_mime_type: application/json`)
- [ ] Zaimplementuj DST-aware parsowanie polskich wyrażeń czasowych (`zoneinfo`)
- [ ] Zaimplementuj `confidence < 0.65` → `scheduled_time = None`
- [ ] Test: "Kupić mleko jutro o 17" → `content="Kupić mleko"`, `scheduled_time=tomorrow 17:00`, `confidence>0.65`
- [ ] Test: "Kupić mleko" (brak czasu) → `scheduled_time=None`, `confidence<0.65`
- [ ] Test: "Za 2 godziny zadzwonić do mamy" → `scheduled_time=now+2h`, `confidence>0.65`
- [ ] Test: "Jutro rano umyć auto" → `is_morning_snooze=True`, `scheduled_time=None`
- [ ] Test: Gemini timeout/exception → `ParsedTask(content=None, confidence=0.0)` bez propagacji wyjątku
- [ ] Test: Voice bytes (mock) → wywołuje Gemini z `Part.from_data(mime_type="audio/ogg")`
- [ ] Weryfikacja: Testy z mock Gemini response przechodzą
- [ ] Weryfikacja: Manual smoke test: 5 polskich wiadomości → poprawne parsowanie

---

### Unit 5: Cloud Tasks Reminder Scheduler

- [ ] Stwórz `adhd-bot/bot/services/scheduler.py` (`schedule_reminder` + `cancel_reminder` + `snooze_reminder`)
- [ ] Stwórz `adhd-bot/bot/handlers/internal_triggers.py` (szkielet endpointów)
- [ ] Stwórz `adhd-bot/tests/test_scheduler.py`
- [ ] Stwórz `adhd-bot/tests/test_internal_triggers.py`
- [ ] Zaimplementuj deterministic task name: `reminder-{task_id}-{int(fire_at.timestamp())}`
- [ ] Zaimplementuj `cancel_reminder` ignorujący `NOT_FOUND`
- [ ] Zaimplementuj OIDC auth dla `/internal/*` endpointów
- [ ] Zaimplementuj `/internal/trigger-reminder` z idempotency guard (state check)
- [ ] Zaimplementuj `/internal/trigger-nudge` z state guard
- [ ] Test: `schedule_reminder` tworzy Cloud Task z poprawnym `schedule_time`
- [ ] Test: `cancel_reminder(None)` → return bez błędu
- [ ] Test: `cancel_reminder` z `NOT_FOUND` → brak wyjątku
- [ ] Test: `snooze_reminder` atomicznie aktualizuje Firestore + tworzy nowy Cloud Task
- [ ] Test: `/internal/trigger-reminder` z `task.state = REMINDED` → 200, brak wysyłki (idempotent)
- [ ] Test: `/internal/trigger-nudge` z `task.state = SNOOZED` → 200, brak nudge
- [ ] Weryfikacja: Cloud Task odpala w ciągu ±10s od `scheduled_time` (test z delay=30s)
- [ ] Weryfikacja: Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

### Unit 6: Onboarding Flow (/start, /timezone, /morning)

- [ ] Stwórz `adhd-bot/bot/handlers/command_handlers.py` (`/start`, `/timezone`, `/morning`)
- [ ] Stwórz `adhd-bot/tests/test_onboarding.py`
- [ ] Zaimplementuj conversation state w Firestore (`users/{user_id}.conversation_state` z TTL)
- [ ] Zaimplementuj walidację IANA timezone przez `zoneinfo.available_timezones()`
- [ ] Zaimplementuj walidację HH:MM (regex `^\d{2}:\d{2}$`, 00-23:00-59)
- [ ] Test: `/start` dla nowego usera tworzy dokument z `subscription_status="trial"`, `trial_ends_at=now+7d`
- [ ] Test: `/start` dla istniejącego usera nie resetuje `subscription_status`
- [ ] Test: `/timezone Europe/Warsaw` → `user.timezone = "Europe/Warsaw"`, potwierdza
- [ ] Test: `/timezone Invalid/Zone` → błąd walidacji, brak zapisu
- [ ] Test: `/morning 08:30` → `user.morning_time = "08:30"`, potwierdza
- [ ] Test: `/morning 25:00` → błąd walidacji (nieprawidłowa godzina)
- [ ] Weryfikacja: Nowy user po `/start` ma `subscription_status="trial"` i `trial_ends_at` za 7 dni w Firestore
- [ ] Weryfikacja: `/timezone` i `/morning` poprawnie aktualizują user document

---

### Unit 7: Task Capture Flow (wiadomość → parse → potwierdź → schedule)

- [ ] Stwórz `adhd-bot/bot/handlers/message_handlers.py` (text + voice handlers)
- [ ] Modyfikuj `adhd-bot/bot/handlers/command_handlers.py` (obsługa conversation states)
- [ ] Stwórz `adhd-bot/tests/test_task_capture.py`
- [ ] Zaimplementuj subscription guard (sprawdzany przed każdym handlerem)
- [ ] Zaimplementuj text message handler (parse → PENDING_CONFIRMATION → confirmation buttons)
- [ ] Zaimplementuj voice message handler (get_file → parse_voice → identyczny flow)
- [ ] Zaimplementuj callback `[✓ OK]` → SCHEDULED + Cloud Task
- [ ] Zaimplementuj callback `[Zmień]` → conversation state `awaiting_time_input`
- [ ] Test: "Kupić mleko jutro o 17" → task `PENDING_CONFIRMATION`, confirmation z buttons
- [ ] Test: "Kupić mleko" (brak czasu) → task `PENDING_CONFIRMATION`, `proposed_time=heuristic`
- [ ] Test: Voice (mock parsed `content="Zadzwonić do mamy"`) → identyczny flow jak text
- [ ] Test: Voice `content=None` (parse fail) → komunikat "wyślij jako tekst"
- [ ] Test: Callback `[✓ OK]` → task `SCHEDULED`, Cloud Task created, buttons usunięte
- [ ] Test: Callback `[Zmień]` → conversation state `awaiting_time_input`, prompt o nowy czas
- [ ] Test: Blocked user → komunikat blokady, brak tworzenia tasku
- [ ] Test [E2E]: Wiadomość "Przypomnij o kawie za 2 minuty" → po ~2 min otrzymać reminder
- [ ] Weryfikacja: Pełny flow od wiadomości do scheduled Cloud Task działa end-to-end w staging
- [ ] Weryfikacja: Task w stanie `SCHEDULED` z poprawnym `scheduled_time` widoczny w Firestore

---

### Unit 8: Reminder Delivery + Inline Button Callbacks (snooze/done/reject)

- [ ] Stwórz `adhd-bot/bot/handlers/callback_handlers.py` (kompletny)
- [ ] Modyfikuj `adhd-bot/bot/handlers/internal_triggers.py` (format reminder message z buttons)
- [ ] Stwórz `adhd-bot/tests/test_reminder_callbacks.py`
- [ ] Zaimplementuj callback data encoding: `snooze:30m:{task_id}`, `snooze:2h:{task_id}`, `snooze:morning:{task_id}`, `done:{task_id}`, `reject:{task_id}`
- [ ] Zaimplementuj `answerCallbackQuery` jako pierwsze wywołanie w każdym callback
- [ ] Zaimplementuj R9 flow: snooze morning gdy `user.morning_time is None`
- [ ] Zaimplementuj fallback: edit message fail → wyślij nową wiadomość
- [ ] Test: Snooze `+30min` → `new_fire_at = now+30m`, stary Cloud Task cancelled, nowy created
- [ ] Test: Snooze `+2h` → `new_fire_at = now+2h`
- [ ] Test: Snooze `morning` gdy `morning_time="08:30"` → `new_fire_at = tomorrow 08:30`
- [ ] Test: Snooze `morning` gdy `morning_time=None` → R9 flow triggered
- [ ] Test: Done → `task.state=COMPLETED`, `expires_at` ustawiony, nudge cancelled
- [ ] Test: Reject → `task.state=REJECTED`, `expires_at` ustawiony
- [ ] Test: Callback na task `COMPLETED` → `answerCallbackQuery`, brak błędu (idempotent)
- [ ] Test: Edit message fail → wyślij nową wiadomość (degraded mode)
- [ ] Test [E2E]: Kliknij `[+30 min]` na reminderze → wiadomość edytowana, nowy reminder za 30 min
- [ ] Weryfikacja: Wszystkie 5 callback flows działają end-to-end w staging
- [ ] Weryfikacja: Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

## Faza 2 — Polish (Units 9-10)

### Unit 9: Nudge System (1h brak reakcji → gentle nudge)

- [ ] Modyfikuj `adhd-bot/bot/handlers/internal_triggers.py` (implementacja `/internal/trigger-nudge`)
- [ ] Stwórz `adhd-bot/tests/test_nudge.py`
- [ ] Zaimplementuj scheduling nudge Cloud Task za 60 min po wysłaniu remindera (queue: `nudges`)
- [ ] Zaimplementuj state-based guard: `task.state != REMINDED` → 200 bez akcji
- [ ] Test: `trigger-nudge` z `task.state=REMINDED` → wysyła nudge message, `task.state=NUDGED`
- [ ] Test: `trigger-nudge` z `task.state=COMPLETED` → 200, brak nudge
- [ ] Test: `trigger-nudge` z `task.state=SNOOZED` → 200, brak nudge
- [ ] Test: `trigger-nudge` z `task.state=NUDGED` → 200, brak drugiego nudge (idempotent)
- [ ] Test: Nudge message zawiera `task.content`
- [ ] Weryfikacja: Task w `REMINDED` przez 1h → nudge wysłany (test staging z `fire_at=now+65s`)
- [ ] Weryfikacja: Task `COMPLETED` przed upływem 1h → nudge nie wysłany (sprawdź Firestore state)

---

### Unit 10: Auto-Archival + Orphan Cloud Task Cleanup

- [ ] Stwórz `adhd-bot/infra/firestore-indexes.json` (TTL policy config dla kolekcji `tasks`, pole `expires_at`)
- [ ] Stwórz `adhd-bot/bot/handlers/cleanup_handler.py` (endpoint `/internal/cleanup`)
- [ ] Stwórz `adhd-bot/infra/cloud-scheduler-cleanup.yaml` (cron `0 3 * * *`)
- [ ] Stwórz `adhd-bot/tests/test_cleanup.py`
- [ ] Skonfiguruj Firestore TTL: `gcloud firestore fields ttls update expires_at --collection-group=tasks`
- [ ] Zaimplementuj cleanup: expired trial → blocked, expired grace_period → blocked
- [ ] Zaimplementuj cleanup: orphaned Cloud Tasks delete (ignore NOT_FOUND)
- [ ] Test: Cleanup aktualizuje `subscription_status="blocked"` dla expired trial users
- [ ] Test: Cleanup aktualizuje `subscription_status="blocked"` dla expired grace_period users
- [ ] Test: Cleanup usuwa orphaned Cloud Tasks (mock tasks_client)
- [ ] Test: Cleanup z pustą listą → 200, brak błędów
- [ ] Test: `/internal/cleanup` bez OIDC auth → 401
- [ ] Weryfikacja: Task z `expires_at = now() - 31 days` znika z Firestore w ciągu 25h (TTL propagation)
- [ ] Weryfikacja: Cleanup job w Cloud Scheduler widoczny jako `SUCCESS` w GCP Console

---

## Faza 3 — Monetyzacja (Unit 11)

### Unit 11: Stripe Subscription (trial, payment, grace period, blokada)

- [ ] Stwórz `adhd-bot/bot/services/stripe_service.py`
- [ ] Stwórz `adhd-bot/bot/handlers/stripe_webhook_handler.py` (router `/stripe/webhook`)
- [ ] Stwórz `adhd-bot/bot/handlers/payment_command_handlers.py` (`/subscribe`, `/billing`)
- [ ] Stwórz `adhd-bot/tests/test_stripe_service.py`
- [ ] Stwórz `adhd-bot/tests/test_stripe_webhooks.py`
- [ ] Utwórz Stripe Price ID 29.99 PLN/mies. w Stripe Dashboard (test mode)
- [ ] Zaimplementuj Stripe Customer create przy `/start`
- [ ] Zaimplementuj deduplication przez `stripe_events/{event_id}` w Firestore
- [ ] Zaimplementuj obsługę: `checkout.session.completed`, `invoice.payment_failed`, `invoice.payment_succeeded`, `customer.subscription.deleted`
- [ ] Test: `/subscribe` tworzy Stripe Checkout Session z `currency="PLN"`, poprawnym `price_id`
- [ ] Test: `checkout.session.completed` webhook → `subscription_status="active"`, `stripe_subscription_id` zapisany
- [ ] Test: `invoice.payment_failed` webhook → `subscription_status="grace_period"`, `grace_period_until=now+3d`
- [ ] Test: `invoice.payment_succeeded` webhook → `subscription_status="active"`, `grace_period_until=None`
- [ ] Test: `customer.subscription.deleted` webhook → `subscription_status="blocked"`
- [ ] Test: Duplicate Stripe `event.id` → 200, brak drugiego przetworzenia
- [ ] Test: Webhook z błędnym `STRIPE_WEBHOOK_SECRET` → 400
- [ ] Test: Blocked user wysyła wiadomość → komunikat blokady + link `/subscribe`
- [ ] Test [E2E]: Przejdź przez Stripe Checkout Sandbox → `subscription_status="active"` w Firestore
- [ ] Weryfikacja: Stripe Dashboard pokazuje subskrypcję po pełnym `/subscribe` flow
- [ ] Weryfikacja: `payment_failed` webhook aktualizuje status w Firestore w ciągu 30s
- [ ] Weryfikacja: Blocked user nie inicjuje nowych Cloud Tasks

---

## Faza 4 — Google Integration (Units 12-14)

### Unit 12: Google OAuth 2.0 + Token Management

- [ ] Stwórz `adhd-bot/bot/services/google_auth.py` (OAuth flow + `get_valid_token` z auto-refresh)
- [ ] Stwórz `adhd-bot/bot/handlers/google_oauth_handler.py` (`/auth/google/callback`, `/connect-google`, `/disconnect-google`)
- [ ] Stwórz `adhd-bot/tests/test_google_auth.py`
- [ ] Skonfiguruj Google OAuth Client w Google Cloud Console
- [ ] Zaimplementuj OAuth state token (nanoid, TTL=10 min, Firestore `oauth_states/{state}`)
- [ ] Zaimplementuj szyfrowanie tokenów przez AES-256 (klucz z Secret Manager)
- [ ] Test: `/connect-google` generuje poprawny OAuth URL ze wszystkimi wymaganymi scope'ami
- [ ] Test: Callback ze złym `state` → 400, brak zapisu tokenów
- [ ] Test: Callback z wygasłym `state` (TTL) → 400
- [ ] Test: `get_valid_token` wywołuje refresh gdy token wygasł
- [ ] Test: `get_valid_token` nie wywołuje refresh gdy token ważny
- [ ] Test: Refresh fail → user oznaczony jako disconnected, Telegram notification
- [ ] Weryfikacja: Pełny OAuth flow end-to-end: kliknięcie linka → autoryzacja Google → bot wysyła potwierdzenie
- [ ] Weryfikacja: Tokeny poprawnie zaszyfrowane w Firestore (brak plain text)

---

### Unit 13: Google Calendar Integration (jednostronna sync bot → Calendar)

- [ ] Stwórz `adhd-bot/bot/services/google_calendar.py` (`create_calendar_event`, `update_calendar_event_time`, `complete_calendar_event`, `delete_calendar_event`)
- [ ] Stwórz `adhd-bot/tests/test_google_calendar.py`
- [ ] Enable Google Calendar API w GCP Console
- [ ] Zintegruj `create_calendar_event` w Unit 7 po `task.transition(→ SCHEDULED)`
- [ ] Zintegruj `update_calendar_event_time` w Unit 8 przy snoozie
- [ ] Zintegruj `complete_calendar_event` i `delete_calendar_event` w Unit 8
- [ ] Test: `create_calendar_event` tworzy event z poprawnym `scheduled_time`
- [ ] Test: `create_calendar_event` dla usera bez Google → skip, brak błędu
- [ ] Test: `update_calendar_event_time` wywołuje `events.patch` z nowym czasem
- [ ] Test: `complete_calendar_event` wywołuje patch z zielonym kolorem
- [ ] Test: `delete_calendar_event` wywołuje events.delete
- [ ] Weryfikacja: Utwórz reminder → event pojawia się w Google Calendar
- [ ] Weryfikacja: Snooze → czas eventu zaktualizowany w Google Calendar
- [ ] Weryfikacja: Done → event zielony w kalendarzu

---

### Unit 14: Google Tasks Integration (bot→Tasks + polling Tasks→bot)

- [ ] Stwórz `adhd-bot/bot/services/google_tasks.py` (`create_google_task`, `complete_google_task`, `delete_google_task`)
- [ ] Stwórz `adhd-bot/bot/handlers/gtasks_polling_handler.py` (`/internal/poll-google-tasks`)
- [ ] Stwórz `adhd-bot/tests/test_google_tasks.py`
- [ ] Enable Google Tasks API w GCP Console
- [ ] Skonfiguruj Cloud Scheduler: `*/5 * * * *` → `/internal/poll-google-tasks`
- [ ] Zaimplementuj `nextSyncToken` dla delta queries
- [ ] Test: `create_google_task` tworzy task z poprawnym `title` i `due`
- [ ] Test: `create_google_task` dla usera bez Google → skip, brak błędu
- [ ] Test: `complete_google_task` wywołuje `tasks.patch` ze `status: "completed"`
- [ ] Test: Polling: Google Task `status: "completed"` → bot task → COMPLETED, Telegram notification
- [ ] Test: Polling: Google Task nie zmieniony → brak akcji
- [ ] Test: Polling dla 0 userów z Google → 200, brak błędów
- [ ] Weryfikacja: Utwórz reminder → task pojawia się w Google Tasks
- [ ] Weryfikacja: Oznacz task jako done w Google Tasks → po ≤5 min bot wysyła Telegram potwierdzenie
- [ ] Weryfikacja: Ukończ task w bocie → Google Task oznaczony jako done

---

## Faza 5 — Admin Dashboard + Security (Units 15-18)

### Unit 15: Gemini Token Usage Tracking

- [ ] Modyfikuj `adhd-bot/bot/services/ai_parser.py` (dodaj token tracking jako fire-and-forget)
- [ ] Stwórz `adhd-bot/bot/services/token_tracker.py` (`record_usage` z atomic Firestore increment)
- [ ] Stwórz `adhd-bot/tests/test_token_tracker.py`
- [ ] Test: `record_usage` zapisuje poprawne wartości w Firestore (atomic increment)
- [ ] Test: Koszt PLN kalkulowany poprawnie dla znanych token counts
- [ ] Test: `record_usage` nie blokuje parse_message (fire-and-forget)
- [ ] Test: `record_usage` nie rzuca wyjątku gdy Firestore niedostępny (graceful fail)
- [ ] Weryfikacja: Po 5 wywołaniach Gemini: kolekcja `token_usage` zawiera poprawne sumy
- [ ] Weryfikacja: Koszt PLN bliski rzeczywistemu rachunkowi Vertex AI

---

### Unit 16: Admin Authentication (Google SSO + Role Management)

- [ ] Stwórz `adhd-bot/bot/admin/__init__.py`
- [ ] Stwórz `adhd-bot/bot/admin/auth.py` (OAuth flow + JWT session, ADMIN_JWT_SECRET z Secret Manager)
- [ ] Stwórz `adhd-bot/bot/admin/middleware.py` (`require_admin` + `require_admin_write` Depends)
- [ ] Stwórz `adhd-bot/tests/test_admin_auth.py`
- [ ] Dodaj pierwszego admina do Firestore `admin_users/{email}`
- [ ] Zaimplementuj audit log middleware dla POST/PATCH/DELETE na `/admin/*`
- [ ] Test: Callback z emailem nie w `admin_users` → 403
- [ ] Test: Callback z poprawnym emailem → JWT cookie ustawiony, redirect do `/admin`
- [ ] Test: Request bez cookie → redirect do `/admin/login`
- [ ] Test: Request z wygasłym JWT → redirect do `/admin/login`
- [ ] Test: `require_admin_write` z role="read-only" → 403
- [ ] Test: POST /admin/* → audit log tworzony z poprawnym email i action
- [ ] Weryfikacja: Logowanie przez Google → dostęp do dashboardu
- [ ] Weryfikacja: Email spoza whitelist → 403 bez dostępu
- [ ] Weryfikacja: Audit log widoczny w Firestore po każdej write akcji

---

### Unit 17: Admin Dashboard API + Web UI

- [ ] Stwórz `adhd-bot/bot/admin/router.py` (FastAPI router `/admin/*`)
- [ ] Stwórz `adhd-bot/bot/admin/queries.py` (Firestore queries dla metryk)
- [ ] Stwórz `adhd-bot/templates/admin/base.html`
- [ ] Stwórz `adhd-bot/templates/admin/dashboard.html` (overview + Chart.js)
- [ ] Stwórz `adhd-bot/templates/admin/users.html` (tabela z paginacją, filtry)
- [ ] Stwórz `adhd-bot/templates/admin/user_detail.html` (szczegóły + akcje admina)
- [ ] Stwórz `adhd-bot/tests/test_admin_queries.py`
- [ ] Zaimplementuj `GET /admin/api/overview` (MRR, ARR, churn, conversion rate)
- [ ] Zaimplementuj `GET /admin/api/users` (paginacja, filter, search)
- [ ] Zaimplementuj `GET /admin/api/users/{user_id}` (szczegóły + Stripe history)
- [ ] Zaimplementuj `PATCH /admin/api/users/{user_id}/subscription` (unblock, extend_trial)
- [ ] Test: `GET /admin/api/overview` bez auth → redirect do login
- [ ] Test: `GET /admin/api/overview` z read-only auth → 200 z poprawnymi polami
- [ ] Test: `PATCH /admin/api/users/{id}/subscription` z read-only auth → 403
- [ ] Test: `PATCH /admin/api/users/{id}/subscription` z admin auth → 200, audit log created
- [ ] Test: Query `users` z filter `status=blocked` → tylko blocked userzy
- [ ] Weryfikacja: Dashboard ładuje się w przeglądarce z poprawnymi danymi
- [ ] Weryfikacja: Lista userów pokazuje poprawne statusy
- [ ] Weryfikacja: Wykres MRR renderuje się z Chart.js

---

### Unit 18: Security Hardening

- [ ] Stwórz `adhd-bot/bot/security/__init__.py`
- [ ] Stwórz `adhd-bot/bot/security/encryption.py` (Cloud KMS wrapper: encrypt/decrypt)
- [ ] Stwórz `adhd-bot/bot/security/rate_limiter.py` (slowapi config per endpoint)
- [ ] Stwórz `adhd-bot/bot/security/headers.py` (HSTS, CSP, X-Frame-Options middleware)
- [ ] Stwórz `adhd-bot/bot/security/validators.py` (`validate_timezone`, `validate_time_format`, `validate_text_length`, `sanitize_for_logging`)
- [ ] Stwórz `adhd-bot/firestore.rules` (deny all direct access)
- [ ] Modyfikuj `adhd-bot/main.py` (dodaj security middleware)
- [ ] Modyfikuj `adhd-bot/bot/services/google_auth.py` (użyj encryption.py dla tokenów)
- [ ] Stwórz `adhd-bot/tests/test_security.py`
- [ ] Utwórz Cloud KMS key ring i klucz `oauth-tokens` w europe-central2
- [ ] Przenieś wszystkie sekrety do Secret Manager (checklist w Unit 18 specyfikacji)
- [ ] Test: `encrypt` + `decrypt` round-trip → identyczny plaintext
- [ ] Test: Security headers obecne we wszystkich `/admin/*` responses
- [ ] Test: Rate limiter zwraca 429 po przekroczeniu limitu `/auth/google/callback`
- [ ] Test: Firestore rules: bezpośredni request HTTP do Firestore REST API → permission denied
- [ ] Test: `validate_timezone("Invalid/Zone")` → rzuca `ValidationError`
- [ ] Test: `sanitize_for_logging("token abc123")` → nie zawiera pełnego tokenu w output
- [ ] Weryfikacja: Security headers sprawdzone przez `curl -I {url}`
- [ ] Weryfikacja: Rate limiting aktywne: 11 szybkich requestów do `/auth/google/callback` → ostatni 429
- [ ] Weryfikacja: Pentest: bezpośredni dostęp do Firestore REST API bez service account → denied
- [ ] Weryfikacja: Brak plain text sekretów w Cloud Run env vars (sprawdź w GCP Console)

---

## Faza 6 — Checklista + RODO (Units 19-21)

### Unit 19: Checklist Template Management

- [ ] Stwórz `adhd-bot/bot/models/checklist.py` (`ChecklistTemplate`, `ChecklistSession` dataclasses)
- [ ] Stwórz `adhd-bot/bot/handlers/checklist_command_handlers.py` (`/new_checklist`, `/checklists`, `/evening`)
- [ ] Stwórz `adhd-bot/bot/services/checklist_ai.py` (`suggest_items` przez Gemini)
- [ ] Stwórz `adhd-bot/tests/test_checklist_templates.py`
- [ ] Zaimplementuj max 12 itemów per szablon (walidacja)
- [ ] Zaimplementuj auto-zapis szablonu po pierwszym użyciu
- [ ] Test: `/new_checklist Siłownia` → Gemini sugeruje ≤8 itemów
- [ ] Test: Szablon z >12 itemami → błąd walidacji
- [ ] Test: `/checklists` dla usera bez szablonów → "Nie masz jeszcze żadnych list"
- [ ] Test: `[Usuń]` szablon → usunięty z Firestore
- [ ] Test: `/evening 20:30` → `user.evening_time = "20:30"`
- [ ] Test: `/evening 25:00` → błąd walidacji
- [ ] Weryfikacja: Pełny flow tworzenia szablonu → widoczny w `/checklists`
- [ ] Weryfikacja: AI sugestie: sensowne itemy dla "Siłownia", "Praca", "Lotnisko"

---

### Unit 20: Checklist Session Flow (wieczorny + poranny reminder, item callbacks)

- [ ] Stwórz `adhd-bot/bot/services/checklist_session.py` (`ChecklistSession.create`)
- [ ] Stwórz `adhd-bot/bot/handlers/checklist_callbacks.py` (item callbacks + snooze listy)
- [ ] Modyfikuj `adhd-bot/bot/handlers/internal_triggers.py` (trigger-checklist-evening, trigger-checklist-morning)
- [ ] Modyfikuj `adhd-bot/bot/handlers/message_handlers.py` (integracja Gemini event detection)
- [ ] Stwórz `adhd-bot/tests/test_checklist_session.py`
- [ ] Dodaj `event_type: "task" | "event_with_preparation"` do `ParsedTask` (modyfikacja Unit 4)
- [ ] Zaimplementuj snapshot itemów przy tworzeniu sesji (niezależny od edycji szablonu)
- [ ] Test: Event z pasującym szablonem → bot proponuje szablon bezpośrednio
- [ ] Test: Event bez szablonu → bot pyta "czy coś zabrać?"
- [ ] Test: Sesja tworzona ze snapshot'em itemów (edycja szablonu po tym nie wpływa)
- [ ] Test: trigger-checklist-morning gdy wszystkie zaznaczone → wiadomość gratulacyjna bez listy
- [ ] Test: trigger-checklist-morning gdy 3/5 zaznaczonych → tylko 2 nieodznaczone z buttonami
- [ ] Test: Kliknięcie ostatniego itemu → auto-zamknięcie z komunikatem gratulacyjnym
- [ ] Test: Snooze całej listy → nowy Cloud Task za 30 min
- [ ] Weryfikacja: Napisz "jutro siłownia o 7" → bot proponuje listę → o 21:00 wieczorna wiadomość → o 7:00 tylko nieodznaczone
- [ ] Weryfikacja: Kliknij wszystkie itemy wieczorem → rano gratulacje bez listy

---

### Unit 21: RODO — /delete_my_data + Polityka Prywatności

- [ ] Modyfikuj `adhd-bot/bot/handlers/command_handlers.py` (dodaj `/delete_my_data` z potwierdzeniem)
- [ ] Stwórz `adhd-bot/templates/privacy_policy.html` (statyczna strona RODO)
- [ ] Stwórz `adhd-bot/tests/test_gdpr.py`
- [ ] Zaimplementuj `GET /privacy` (publiczny, bez auth)
- [ ] Zaimplementuj kaskadowe usuwanie: tasks, token_usage, checklist_templates, checklist_sessions, processed_updates, users document
- [ ] Zaimplementuj cancel Stripe subscription przy delete
- [ ] Zaimplementuj revoke Google token przy delete
- [ ] Test: `/delete_my_data` bez potwierdzenia → brak usunięcia
- [ ] Test: `/delete_my_data` z potwierdzeniem → wszystkie kolekcje usera usunięte z Firestore
- [ ] Test: `/delete_my_data` anuluje subskrypcję Stripe jeśli istnieje
- [ ] Test: `/delete_my_data` revoke Google token jeśli połączone
- [ ] Test: `GET /privacy` zwraca 200 z HTML
- [ ] Weryfikacja: Po `/delete_my_data` brak dokumentów usera w żadnej kolekcji Firestore
- [ ] Weryfikacja: `/privacy` dostępne publicznie bez autentykacji
