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

- [x] Stwórz `adhd-bot/main.py` (FastAPI app entry point, endpoint `/health`)
- [x] Stwórz `adhd-bot/Dockerfile` (python:3.12-slim, gunicorn + uvicorn)
- [x] Stwórz `adhd-bot/requirements.txt` z pinowanymi wersjami
- [x] Stwórz `adhd-bot/.env.example`
- [x] Stwórz `adhd-bot/cloud-run.yaml` (min-instances=1, 512Mi, europe-central2)
- [x] Stwórz `adhd-bot/bot/__init__.py`
- [x] Stwórz `adhd-bot/bot/config.py` (dataclass, `__post_init__` fail-fast validation)
- [x] Stwórz `adhd-bot/bot/handlers/__init__.py`
- [x] Stwórz `adhd-bot/bot/models/__init__.py`
- [x] Stwórz `adhd-bot/bot/services/__init__.py`
- [x] Stwórz `adhd-bot/tests/__init__.py`
- [x] Stwórz `adhd-bot/tests/test_config.py`
- [ ] Skonfiguruj Secret Manager: TELEGRAM_BOT_TOKEN, TELEGRAM_SECRET_TOKEN, STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, GCP_PROJECT_ID
- [ ] Utwórz dwie Cloud Tasks kolejki: `reminders`, `nudges`
- [x] Test: Config validation rzuca `ValueError` gdy brakuje wymaganego env vara
- [x] Test: Config poprawnie ładuje zmienne z environment
- [x] Test: `/health` zwraca `{"status": "healthy"}` z kodem 200
- [ ] Weryfikacja: `docker build` kończy się sukcesem
- [ ] Weryfikacja: `gcloud run deploy --min-instances=1` kończy się sukcesem
- [ ] Weryfikacja: `/health` zwraca 200 na Cloud Run URL

---

### Unit 2: Telegram Webhook Receiver + Security + Deduplication

- [x] Stwórz `adhd-bot/bot/webhook.py` (FastAPI router dla `/telegram/webhook`)
- [x] Stwórz `adhd-bot/bot/services/deduplication.py` (`is_duplicate` + `mark_processed`)
- [x] Stwórz `adhd-bot/bot/services/firestore_client.py` (singleton Firestore client)
- [x] Stwórz `adhd-bot/tests/test_webhook_security.py`
- [x] Stwórz `adhd-bot/tests/test_deduplication.py`
- [x] Zaimplementuj webhook: kolejność (1) token check → (2) timestamp check → (3) dedup → (4) routing
- [x] Test: Request bez `X-Telegram-Bot-Api-Secret-Token` → 401
- [x] Test: Request z błędnym secret token → 401
- [x] Test: Request z poprawnym tokenem → 200
- [x] Test: Update z `message.date` starszym niż 120s → 200 (odrzucony cicho)
- [x] Test: Duplicate `update_id` → 200, `mark_processed` nie wywoływany drugi raz
- [x] Test: Nowy `update_id` → dokument tworzony w `processed_updates`
- [ ] Weryfikacja: Telegram `/setWebhook` z `secret_token` zwraca success
- [ ] Weryfikacja: Testowy update od Telegram dociera i jest procesowany

---

### Unit 3: Firestore Data Layer + Task State Machine

- [x] Stwórz `adhd-bot/bot/models/user.py` (User dataclass + `get_or_create` + `is_subscription_active`)
- [x] Stwórz `adhd-bot/bot/models/task.py` (Task dataclass + `TaskState` enum + `transition` + `InvalidStateTransitionError`)
- [x] Stwórz `adhd-bot/tests/test_user_model.py`
- [x] Stwórz `adhd-bot/tests/test_task_state_machine.py`
- [x] Test: `task.transition(PENDING_CONFIRMATION → SCHEDULED)` → sukces
- [x] Test: `task.transition(SCHEDULED → COMPLETED)` → rzuca `InvalidStateTransitionError`
- [x] Test: `task.transition(REMINDED → COMPLETED)` → `expires_at = now() + 30d`, `completed_at` ustawiony
- [x] Test: `task.transition(REMINDED → REJECTED)` → `expires_at = now() + 30d`, `rejected_at` ustawiony
- [x] Test: `User.get_or_create` tworzy nowego usera z `timezone="Europe/Warsaw"`, `subscription_status="trial"`
- [x] Test: `User.get_or_create` zwraca istniejącego usera bez nadpisania pól
- [x] Test: `User.is_subscription_active()` → `False` gdy `subscription_status="blocked"`
- [x] Test: `User.is_subscription_active()` → `False` gdy `subscription_status="trial"` i `trial_ends_at < now()`
- [ ] Weryfikacja: State machine testy obejmują 100% macierzy przejść (valid i invalid)
- [ ] Weryfikacja: Firestore CRUD działa na Firestore emulatorze (lokalnie)

---

### Unit 4: Gemini AI Parser (tekst + głos → structured task)

- [x] Stwórz `adhd-bot/bot/services/ai_parser.py` (`ParsedTask` dataclass + `parse_message` + `parse_voice_message`)
- [x] Stwórz `adhd-bot/tests/test_ai_parser.py`
- [x] Zaimplementuj JSON schema output mode (`response_mime_type: application/json`)
- [x] Zaimplementuj DST-aware parsowanie polskich wyrażeń czasowych (`zoneinfo`)
- [x] Zaimplementuj `confidence < 0.65` → `scheduled_time = None`
- [x] Test: "Kupić mleko jutro o 17" → `content="Kupić mleko"`, `scheduled_time=tomorrow 17:00`, `confidence>0.65`
- [x] Test: "Kupić mleko" (brak czasu) → `scheduled_time=None`, `confidence<0.65`
- [x] Test: "Za 2 godziny zadzwonić do mamy" → `scheduled_time=now+2h`, `confidence>0.65`
- [x] Test: "Jutro rano umyć auto" → `is_morning_snooze=True`, `scheduled_time=None`
- [x] Test: Gemini timeout/exception → `ParsedTask(content=None, confidence=0.0)` bez propagacji wyjątku
- [x] Test: Voice bytes (mock) → wywołuje Gemini z `Part.from_data(mime_type="audio/ogg")`
- [ ] Weryfikacja: Testy z mock Gemini response przechodzą
- [ ] Weryfikacja: Manual smoke test: 5 polskich wiadomości → poprawne parsowanie

---

### Unit 5: Cloud Tasks Reminder Scheduler

- [x] Stwórz `adhd-bot/bot/services/scheduler.py` (`schedule_reminder` + `cancel_reminder` + `snooze_reminder`)
- [x] Stwórz `adhd-bot/bot/handlers/internal_triggers.py` (szkielet endpointów)
- [x] Stwórz `adhd-bot/tests/test_scheduler.py`
- [x] Stwórz `adhd-bot/tests/test_internal_triggers.py`
- [x] Zaimplementuj deterministic task name: `reminder-{task_id}-{int(fire_at.timestamp())}`
- [x] Zaimplementuj `cancel_reminder` ignorujący `NOT_FOUND`
- [x] Zaimplementuj OIDC auth dla `/internal/*` endpointów
- [x] Zaimplementuj `/internal/trigger-reminder` z idempotency guard (state check)
- [x] Zaimplementuj `/internal/trigger-nudge` z state guard
- [x] Test: `schedule_reminder` tworzy Cloud Task z poprawnym `schedule_time`
- [x] Test: `cancel_reminder(None)` → return bez błędu
- [x] Test: `cancel_reminder` z `NOT_FOUND` → brak wyjątku
- [x] Test: `snooze_reminder` atomicznie aktualizuje Firestore + tworzy nowy Cloud Task
- [x] Test: `/internal/trigger-reminder` z `task.state = REMINDED` → 200, brak wysyłki (idempotent)
- [x] Test: `/internal/trigger-nudge` z `task.state = SNOOZED` → 200, brak nudge
- [ ] Weryfikacja: Cloud Task odpala w ciągu ±10s od `scheduled_time` (test z delay=30s)
- [ ] Weryfikacja: Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

### Unit 6: Onboarding Flow (/start, /timezone, /morning)

- [x] Stwórz `adhd-bot/bot/handlers/command_handlers.py` (`/start`, `/timezone`, `/morning`)
- [x] Stwórz `adhd-bot/tests/test_onboarding.py`
- [x] Zaimplementuj conversation state w Firestore (`users/{user_id}.conversation_state` z TTL)
- [x] Zaimplementuj walidację IANA timezone przez `zoneinfo.available_timezones()`
- [x] Zaimplementuj walidację HH:MM (regex `^\d{2}:\d{2}$`, 00-23:00-59)
- [x] Test: `/start` dla nowego usera tworzy dokument z `subscription_status="trial"`, `trial_ends_at=now+7d`
- [x] Test: `/start` dla istniejącego usera nie resetuje `subscription_status`
- [x] Test: `/timezone Europe/Warsaw` → `user.timezone = "Europe/Warsaw"`, potwierdza
- [x] Test: `/timezone Invalid/Zone` → błąd walidacji, brak zapisu
- [x] Test: `/morning 08:30` → `user.morning_time = "08:30"`, potwierdza
- [x] Test: `/morning 25:00` → błąd walidacji (nieprawidłowa godzina)
- [ ] Weryfikacja: Nowy user po `/start` ma `subscription_status="trial"` i `trial_ends_at` za 7 dni w Firestore
- [ ] Weryfikacja: `/timezone` i `/morning` poprawnie aktualizują user document

---

### Unit 7: Task Capture Flow (wiadomość → parse → potwierdź → schedule)

- [x] Stwórz `adhd-bot/bot/handlers/message_handlers.py` (text + voice handlers)
- [x] Modyfikuj `adhd-bot/bot/handlers/command_handlers.py` (obsługa conversation states)
- [x] Stwórz `adhd-bot/tests/test_task_capture.py`
- [x] Zaimplementuj subscription guard (sprawdzany przed każdym handlerem)
- [x] Zaimplementuj text message handler (parse → PENDING_CONFIRMATION → confirmation buttons)
- [x] Zaimplementuj voice message handler (get_file → parse_voice → identyczny flow)
- [x] Zaimplementuj callback `[✓ OK]` → SCHEDULED + Cloud Task
- [x] Zaimplementuj callback `[Zmień]` → conversation state `awaiting_time_input`
- [x] Test: "Kupić mleko jutro o 17" → task `PENDING_CONFIRMATION`, confirmation z buttons
- [x] Test: "Kupić mleko" (brak czasu) → task `PENDING_CONFIRMATION`, `proposed_time=heuristic`
- [x] Test: Voice (mock parsed `content="Zadzwonić do mamy"`) → identyczny flow jak text
- [x] Test: Voice `content=None` (parse fail) → komunikat "wyślij jako tekst"
- [ ] Test: Callback `[✓ OK]` → task `SCHEDULED`, Cloud Task created, buttons usunięte
- [ ] Test: Callback `[Zmień]` → conversation state `awaiting_time_input`, prompt o nowy czas
- [x] Test: Blocked user → komunikat blokady, brak tworzenia tasku
- [ ] Test [E2E]: Wiadomość "Przypomnij o kawie za 2 minuty" → po ~2 min otrzymać reminder
- [ ] Weryfikacja: Pełny flow od wiadomości do scheduled Cloud Task działa end-to-end w staging
- [ ] Weryfikacja: Task w stanie `SCHEDULED` z poprawnym `scheduled_time` widoczny w Firestore

---

### Unit 8: Reminder Delivery + Inline Button Callbacks (snooze/done/reject)

- [x] Stwórz `adhd-bot/bot/handlers/callback_handlers.py` (kompletny)
- [x] Modyfikuj `adhd-bot/bot/handlers/internal_triggers.py` (format reminder message z buttons)
- [x] Stwórz `adhd-bot/tests/test_reminder_callbacks.py`
- [x] Zaimplementuj callback data encoding: `snooze:30m:{task_id}`, `snooze:2h:{task_id}`, `snooze:morning:{task_id}`, `done:{task_id}`, `reject:{task_id}`
- [x] Zaimplementuj `answerCallbackQuery` jako pierwsze wywołanie w każdym callback
- [x] Zaimplementuj R9 flow: snooze morning gdy `user.morning_time is None`
- [x] Zaimplementuj fallback: edit message fail → wyślij nową wiadomość
- [x] Test: Snooze `+30min` → `new_fire_at = now+30m`, stary Cloud Task cancelled, nowy created
- [x] Test: Snooze `+2h` → `new_fire_at = now+2h`
- [x] Test: Snooze `morning` gdy `morning_time="08:30"` → `new_fire_at = tomorrow 08:30`
- [x] Test: Snooze `morning` gdy `morning_time=None` → R9 flow triggered
- [x] Test: Done → `task.state=COMPLETED`, `expires_at` ustawiony, nudge cancelled
- [x] Test: Reject → `task.state=REJECTED`, `expires_at` ustawiony
- [x] Test: Callback na task `COMPLETED` → `answerCallbackQuery`, brak błędu (idempotent)
- [x] Test: Edit message fail → wyślij nową wiadomość (degraded mode)
- [ ] Test [E2E]: Kliknij `[+30 min]` na reminderze → wiadomość edytowana, nowy reminder za 30 min
- [ ] Weryfikacja: Wszystkie 5 callback flows działają end-to-end w staging
- [ ] Weryfikacja: Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

## Do poprawy po review fazy 1

- [x] 🟠 [important] **bot/webhook.py:26** — Zastąp `==` przez `hmac.compare_digest()` dla porównania secret token (timing attack mitigation)
- [x] 🟠 [important] **bot/handlers/internal_triggers.py** — Zaimplementuj weryfikację OIDC auth na `/internal/trigger-reminder` i `/internal/trigger-nudge` (endpointy są publicznie dostępne wbrew planowi Unit 5)
- [x] 🟠 [important] **bot/services/firestore_client.py:7** — Przenieś `MagicMock` import poza produkcyjny kod; użyj wzorca z osobną fabryką testową lub `importlib` zamiast importu `unittest.mock` w pliku produkcyjnym
- [x] 🟠 [important] **bot/models/user.py:92-108** — Usuń dead code (`@db.transaction` + `_txn` nigdy nie wywołane) lub zaimplementuj prawdziwą transakcję; obecna nieatomiyczna ścieżka get→set narażona na race condition przy concurrent `/start`
- [x] 🟠 [important] **bot/main.py:14-18** + **bot/webhook.py:84-100** — Podepnij routery webhook, command, message i callback handlers w `main.py` oraz zaimplementuj routing w `_route_update` (bot nie jest funkcjonalny end-to-end)
- [x] 🟠 [important] **bot/handlers/message_handlers.py:247-254** — Stwórz `adhd-bot/infra/firestore-indexes.json` z composite index na `(telegram_user_id, state, created_at DESC)` dla kolekcji `tasks`; bez tego query w `_handle_time_input` zgłosi `FAILED_PRECONDITION` w produkcji
- [x] 🟠 [important] **tests/test_reminder_callbacks.py:TestSnooze30Min** (linia 99) — Dodaj asercję: `mock_snooze.call_args` → zweryfikuj że `new_fire_at ≈ now + 30min` (±5s tolerance)
- [x] 🟠 [important] **tests/test_reminder_callbacks.py:TestSnooze2h** (linia 124) — Dodaj asercję weryfikującą stan tasku (`SNOOZED`) lub że `snooze_reminder` wywołany z `new_fire_at ≈ now + 2h`
- [ ] 🟡 [nit] **bot/handlers/callback_handlers.py:17**, **internal_triggers.py:18**, **message_handlers.py:16** — Wyciągnij `TELEGRAM_BASE_URL` do `bot/config.py` lub `bot/__init__.py` (duplikacja stałej w 3 plikach)
- [ ] 🟡 [nit] **bot/services/scheduler.py:18-21** — Dodaj singleton dla `CloudTasksClient` (wzorzec jak `firestore_client.py`) żeby uniknąć tworzenia nowego połączenia gRPC per operacja
- [ ] 🟡 [nit] **bot/services/ai_parser.py:55-63** — `_get_gemini_client()` wywołuje `vertexai.init()` przy każdym parsowaniu; uczyń inicjalizację jednorazową (moduł-level singleton z guard)
- [ ] 🟡 [nit] **tests/test_task_capture.py:TestTextMessageWithoutTime** (linia 135) — Wzmocnij asercję: oprócz `mock_send.called` sprawdź że task był zapisany w stanie `PENDING_CONFIRMATION` i że wiadomość zawiera confirmation keyboard
- [ ] 🟡 [nit] **tests/test_task_capture.py** — Dodaj 2 brakujące testy z planu Unit 7: (1) callback `[✓ OK]` → task SCHEDULED + Cloud Task created; (2) callback `[Zmień]` → conversation state `awaiting_time_input`

## Do poprawy po re-run review fazy 1

- [x] 🟠 [important] **bot/models/user.py:126** — `except Exception:` zmienione na `except (ImportError, AttributeError, TypeError):` — naprawa zweryfikowana ✅ (cykl 2 re-run 2026-04-09)
- [ ] 🟡 [nit] **bot/handlers/callback_handlers.py:17**, **internal_triggers.py:18**, **message_handlers.py:17** — `TELEGRAM_BASE_URL` nadal zduplikowany w 3 plikach; wyciągnij do `bot/config.py`
- [ ] 🟡 [nit] **bot/services/scheduler.py:18-21** — `_get_tasks_client()` tworzy nową instancję `CloudTasksClient` per wywołanie; dodaj singleton jak w `firestore_client.py`
- [ ] 🟡 [nit] **bot/services/ai_parser.py** — `_get_gemini_client()` wywołuje `vertexai.init()` przy każdym parsowaniu; uczyń jednorazową (moduł-level singleton z guard)

---

## Faza 2 — Polish (Units 9-10)

### Unit 9: Nudge System (1h brak reakcji → gentle nudge)

- [x] Modyfikuj `adhd-bot/bot/handlers/internal_triggers.py` (implementacja `/internal/trigger-nudge`)
- [x] Stwórz `adhd-bot/tests/test_nudge.py`
- [x] Zaimplementuj scheduling nudge Cloud Task za 60 min po wysłaniu remindera (queue: `nudges`)
- [x] Zaimplementuj state-based guard: `task.state != REMINDED` → 200 bez akcji
- [x] Test: `trigger-nudge` z `task.state=REMINDED` → wysyła nudge message, `task.state=NUDGED`
- [x] Test: `trigger-nudge` z `task.state=COMPLETED` → 200, brak nudge
- [x] Test: `trigger-nudge` z `task.state=SNOOZED` → 200, brak nudge
- [x] Test: `trigger-nudge` z `task.state=NUDGED` → 200, brak drugiego nudge (idempotent)
- [x] Test: Nudge message zawiera `task.content`
- [ ] Weryfikacja: Task w `REMINDED` przez 1h → nudge wysłany (test staging z `fire_at=now+65s`)
- [ ] Weryfikacja: Task `COMPLETED` przed upływem 1h → nudge nie wysłany (sprawdź Firestore state)

---

### Unit 10: Auto-Archival + Orphan Cloud Task Cleanup

- [x] Stwórz `adhd-bot/infra/firestore-indexes.json` (TTL policy config dla kolekcji `tasks`, pole `expires_at`)
- [x] Stwórz `adhd-bot/bot/handlers/cleanup_handler.py` (endpoint `/internal/cleanup`)
- [x] Stwórz `adhd-bot/infra/cloud-scheduler-cleanup.yaml` (cron `0 3 * * *`)
- [x] Stwórz `adhd-bot/tests/test_cleanup.py`
- [ ] Skonfiguruj Firestore TTL: `gcloud firestore fields ttls update expires_at --collection-group=tasks`
- [x] Zaimplementuj cleanup: expired trial → blocked, expired grace_period → blocked
- [x] Zaimplementuj cleanup: orphaned Cloud Tasks delete (ignore NOT_FOUND)
- [x] Test: Cleanup aktualizuje `subscription_status="blocked"` dla expired trial users
- [x] Test: Cleanup aktualizuje `subscription_status="blocked"` dla expired grace_period users
- [x] Test: Cleanup usuwa orphaned Cloud Tasks (mock tasks_client)
- [x] Test: Cleanup z pustą listą → 200, brak błędów
- [x] Test: `/internal/cleanup` bez OIDC auth → 401
- [ ] Weryfikacja: Task z `expires_at = now() - 31 days` znika z Firestore w ciągu 25h (TTL propagation)
- [ ] Weryfikacja: Cleanup job w Cloud Scheduler widoczny jako `SUCCESS` w GCP Console

---

## Do poprawy po review fazy 2

- [x] 🟠 [important] **bot/handlers/cleanup_handler.py:55** + **bot/handlers/internal_triggers.py:46** — Zawęź `except Exception` w `_verify_oidc_token` do konkretnych typów `GoogleAuthError`, `TransportError`, `ValueError`; generyczny catch maskuje błędy konfiguracji jako 401 — naprawione ✅ (re-run cykl 1 2026-04-10)
- [x] 🟠 [important] **bot/handlers/cleanup_handler.py:106-111** — Dodaj `logger.warning` dla case `grace_period_until is None` (silent blocking bez logu utrudnia diagnozę); rozwaź `continue` (skip) zamiast natychmiastowego blokowania gdy pole brakuje — naprawione ✅ (re-run cykl 1 2026-04-10)
- [x] 🟠 [important] **bot/handlers/cleanup_handler.py:148-167** — Scal dwa oddzielne `doc.reference.update()` (dla `cloud_task_name` i `nudge_task_name`) w jedno wywołanie; obecny N+1 pattern przy 1000+ COMPLETED taskach → timeout cleanup jobu — naprawione ✅ (re-run cykl 1 2026-04-10)
- [ ] 🟡 [nit] **bot/handlers/cleanup_handler.py** + **bot/handlers/internal_triggers.py** — Duplikacja `_verify_oidc_token` w 2 plikach; wyciągnij do wspólnego modułu (naturalne miejsce: Unit 18 Security Hardening)
- [ ] 🟡 [nit] **bot/handlers/internal_triggers.py:18** — `TELEGRAM_BASE_URL` carry-over z Fazy 1; wyciągnij do `bot/config.py`
- [ ] 🟡 [nit] **tests/test_nudge.py** — Dodaj testy dla stanów `PENDING_CONFIRMATION` i `SCHEDULED` (nie tylko COMPLETED/SNOOZED/NUDGED/REJECTED)
- [ ] 🟡 [nit] **tests/test_cleanup.py** — Dodaj test dla task z oboma `cloud_task_name` i `nudge_task_name` ustawionymi (weryfikuje że `cancel_reminder` wywołany 2x, count=1)

---

## Faza 3 — Monetyzacja (Unit 11)

### Unit 11: Stripe Subscription (trial, payment, grace period, blokada)

- [x] Stwórz `adhd-bot/bot/services/stripe_service.py`
- [x] Stwórz `adhd-bot/bot/handlers/stripe_webhook_handler.py` (router `/stripe/webhook`)
- [x] Stwórz `adhd-bot/bot/handlers/payment_command_handlers.py` (`/subscribe`, `/billing`)
- [x] Stwórz `adhd-bot/tests/test_stripe_service.py`
- [x] Stwórz `adhd-bot/tests/test_stripe_webhooks.py`
- [ ] Utwórz Stripe Price ID 29.99 PLN/mies. w Stripe Dashboard (test mode)
- [x] Zaimplementuj Stripe Customer create przy `/subscribe` (lazy — przy pierwszym zakupie)
- [x] Zaimplementuj deduplication przez `stripe_events/{event_id}` w Firestore
- [x] Zaimplementuj obsługę: `checkout.session.completed`, `invoice.payment_failed`, `invoice.payment_succeeded`, `customer.subscription.deleted`
- [x] Test: `/subscribe` tworzy Stripe Checkout Session z `currency="PLN"`, poprawnym `price_id`
- [x] Test: `checkout.session.completed` webhook → `subscription_status="active"`, `stripe_subscription_id` zapisany
- [x] Test: `invoice.payment_failed` webhook → `subscription_status="grace_period"`, `grace_period_until=now+3d`
- [x] Test: `invoice.payment_succeeded` webhook → `subscription_status="active"`, `grace_period_until=None`
- [x] Test: `customer.subscription.deleted` webhook → `subscription_status="blocked"`
- [x] Test: Duplicate Stripe `event.id` → 200, brak drugiego przetworzenia
- [x] Test: Webhook z błędnym `STRIPE_WEBHOOK_SECRET` → 400
- [x] Test: Blocked user wysyła wiadomość → komunikat blokady + link `/subscribe`
- [ ] Test [E2E]: Przejdź przez Stripe Checkout Sandbox → `subscription_status="active"` w Firestore
- [ ] Weryfikacja: Stripe Dashboard pokazuje subskrypcję po pełnym `/subscribe` flow
- [ ] Weryfikacja: `payment_failed` webhook aktualizuje status w Firestore w ciągu 30s
- [ ] Weryfikacja: Blocked user nie inicjuje nowych Cloud Tasks

---

## Do poprawy po review fazy 3

- [x] 🟠 [important] **bot/handlers/stripe_webhook_handler.py:89,105-108** — Mark-before-handle: `mark_event_processed` wywołane PRZED handlerem; przy exception handlera zwracany jest 500, Stripe ponawia, dedup zwraca duplicate → event trwale pominięty. Zamień kolejność: uruchom handler → jeśli sukces → mark → 200; jeśli wyjątek → return 500 bez mark — naprawione ✅ (re-run cykl 1 2026-04-09)
- [x] 🟠 [important] **bot/services/stripe_service.py:137-217** — Brak Telegram notification w `handle_invoice_payment_failed` (wymagane: "Płatność nie powiodła się 💳 Masz 3 dni na aktualizację karty: /billing") i `handle_subscription_deleted` (wymagane: "Subskrypcja anulowana. Wznów przez /subscribe.") — user nie jest informowany przez bota o problemach z płatnością — naprawione ✅ (re-run cykl 1 2026-04-09)
- [x] 🟠 [important] **bot/handlers/payment_command_handlers.py:98-153** — `/billing` nie implementuje Stripe Billing Portal (plan: `stripe.billing_portal.Session.create(customer=customer_id) → wyślij URL`); aktualna implementacja pokazuje tylko status tekstowy bez możliwości zarządzania kartą; zaimplementuj portal lub udokumentuj świadomą zmianę w kontekście — naprawione ✅ (re-run cykl 1 2026-04-09)
- [ ] 🟡 [nit] **bot/handlers/stripe_webhook_handler.py:60** — `except Exception` w `_verify_stripe_signature` — zawęź do `except (stripe.error.SignatureVerificationError, ValueError):` (wzorzec z naprawy Fazy 2)
- [ ] 🟡 [nit] **bot/services/stripe_service.py:15-19** + **stripe_webhook_handler.py:57** — `STRIPE_API_KEY` odczytywany z `os.environ` przy każdym wywołaniu zamiast z Config singleton; dodaj walidację że klucz nie jest pusty
- [ ] 🟡 [nit] **bot/handlers/stripe_webhook_handler.py:105** — `except Exception` w routerze eventów — zawęź do konkretnych typów (google.cloud.exceptions.DeadlineExceeded, etc.)
- [ ] 🟡 [nit] **bot/handlers/payment_command_handlers.py:71** — `except Exception` w `handle_subscribe` — ukrywa AuthenticationError Stripe; zawęź lub re-raise dla nieoczekiwanych typów
- [ ] 🟡 [nit] **bot/handlers/payment_command_handlers.py:16** — `TELEGRAM_BASE_URL` zduplikowany teraz w 5 plikach (carryover z Faz 1-2); wyciągnij do `bot/config.py`

---

## Faza 4 — Google Integration (Units 12-14)

### Unit 12: Google OAuth 2.0 + Token Management

- [x] Stwórz `adhd-bot/bot/services/google_auth.py` (OAuth flow + `get_valid_token` z auto-refresh)
- [x] Stwórz `adhd-bot/bot/handlers/google_oauth_handler.py` (`/auth/google/callback`, `/connect-google`, `/disconnect-google`)
- [x] Stwórz `adhd-bot/tests/test_google_auth.py`
- [ ] Skonfiguruj Google OAuth Client w Google Cloud Console
- [x] Zaimplementuj OAuth state token (nanoid, TTL=10 min, Firestore `oauth_states/{state}`)
- [x] Zaimplementuj szyfrowanie tokenów przez AES-256 (klucz z Secret Manager)
- [x] Test: `/connect-google` generuje poprawny OAuth URL ze wszystkimi wymaganymi scope'ami
- [x] Test: Callback ze złym `state` → 400, brak zapisu tokenów
- [x] Test: Callback z wygasłym `state` (TTL) → 400
- [x] Test: `get_valid_token` wywołuje refresh gdy token wygasł
- [x] Test: `get_valid_token` nie wywołuje refresh gdy token ważny
- [x] Test: Refresh fail → user oznaczony jako disconnected, Telegram notification
- [ ] Weryfikacja: Pełny OAuth flow end-to-end: kliknięcie linka → autoryzacja Google → bot wysyła potwierdzenie
- [ ] Weryfikacja: Tokeny poprawnie zaszyfrowane w Firestore (brak plain text)

---

### Unit 13: Google Calendar Integration (jednostronna sync bot → Calendar)

- [x] Stwórz `adhd-bot/bot/services/google_calendar.py` (`create_calendar_event`, `update_calendar_event_time`, `complete_calendar_event`, `delete_calendar_event`)
- [x] Stwórz `adhd-bot/tests/test_google_calendar.py`
- [ ] Enable Google Calendar API w GCP Console
- [ ] Zintegruj `create_calendar_event` w Unit 7 po `task.transition(→ SCHEDULED)`
- [ ] Zintegruj `update_calendar_event_time` w Unit 8 przy snoozie
- [ ] Zintegruj `complete_calendar_event` i `delete_calendar_event` w Unit 8
- [x] Test: `create_calendar_event` tworzy event z poprawnym `scheduled_time`
- [x] Test: `create_calendar_event` dla usera bez Google → skip, brak błędu
- [x] Test: `update_calendar_event_time` wywołuje `events.patch` z nowym czasem
- [x] Test: `complete_calendar_event` wywołuje patch z zielonym kolorem
- [x] Test: `delete_calendar_event` wywołuje events.delete
- [ ] Weryfikacja: Utwórz reminder → event pojawia się w Google Calendar
- [ ] Weryfikacja: Snooze → czas eventu zaktualizowany w Google Calendar
- [ ] Weryfikacja: Done → event zielony w kalendarzu

---

### Unit 14: Google Tasks Integration (bot→Tasks + polling Tasks→bot)

- [x] Stwórz `adhd-bot/bot/services/google_tasks.py` (`create_google_task`, `complete_google_task`, `delete_google_task`)
- [x] Stwórz `adhd-bot/bot/handlers/gtasks_polling_handler.py` (`/internal/poll-google-tasks`)
- [x] Stwórz `adhd-bot/tests/test_google_tasks.py`
- [ ] Enable Google Tasks API w GCP Console
- [ ] Skonfiguruj Cloud Scheduler: `*/5 * * * *` → `/internal/poll-google-tasks`
- [x] Zaimplementuj `nextSyncToken` dla delta queries
- [x] Test: `create_google_task` tworzy task z poprawnym `title` i `due`
- [x] Test: `create_google_task` dla usera bez Google → skip, brak błędu
- [x] Test: `complete_google_task` wywołuje `tasks.patch` ze `status: "completed"`
- [x] Test: Polling: Google Task `status: "completed"` → bot task → COMPLETED, Telegram notification
- [x] Test: Polling: Google Task nie zmieniony → brak akcji
- [x] Test: Polling dla 0 userów z Google → 200, brak błędów
- [ ] Weryfikacja: Utwórz reminder → task pojawia się w Google Tasks
- [ ] Weryfikacja: Oznacz task jako done w Google Tasks → po ≤5 min bot wysyła Telegram potwierdzenie
- [ ] Weryfikacja: Ukończ task w bocie → Google Task oznaczony jako done

---

## Do poprawy po review fazy 4

- [x] 🔴 [blocking] **requirements.txt** — `cryptography` package brak w requirements.txt; AES-256 encryption tokenów Google nie zadziała w produkcji (fallback do plain base64); dodaj `cryptography==44.0.0`
- [x] 🟠 [important] **bot/handlers/gtasks_polling_handler.py:192** — `completable_states` zawiera `TaskState.SCHEDULED` ale state machine zabrania `SCHEDULED → COMPLETED`; wywołanie `task.transition(TaskState.COMPLETED)` rzuci `InvalidStateTransitionError`, silently swallowed; usuń SCHEDULED z setu
- [x] 🟠 [important] **bot/services/google_auth.py:300** — `except Exception` w `_refresh_access_token` zbyt szeroki; maskuje TypeError/AttributeError z logiki szyfrowania jako network failure i disconnectuje usera; restrukturyzacja: encryption/storage przeniesione poza try/except, błędy szyfrowania propagują się zamiast być maskowane
- [x] 🟠 [important] **bot/services/google_auth.py:115-137** — `verify_oauth_state` nie waliduje typu `telegram_user_id`; jeśli pole jest None/string zamiast int, downstream code traktuje je jako prawidłowe; dodaj `return user_id if isinstance(user_id, int) else None`
- [x] 🟠 [important] **bot/services/google_calendar.py:83** + **bot/services/google_tasks.py:67** — synchroniczne `service.*.execute()` blokuje async event loop FastAPI; użyj `await asyncio.to_thread(...)` do owinięcia wywołań Google API
- [ ] 🟡 [nit] **bot/handlers/gtasks_polling_handler.py:34** — `_verify_oidc_token` zduplikowana teraz w 3 plikach (carryover z Faz 1-3); wyciągnij do wspólnego modułu w Unit 18
- [ ] 🟡 [nit] **bot/handlers/google_oauth_handler.py:37** + **bot/handlers/gtasks_polling_handler.py:29** — `TELEGRAM_BASE_URL` zduplikowany teraz w 8 plikach (carryover); wyciągnij do `bot/config.py` przed Fazą 5
- [ ] 🟡 [nit] **bot/services/google_calendar.py:32** — `import httplib2` nieużywany bezpośrednio; usuń zbędny import
- [ ] 🟡 [nit] **bot/handlers/google_oauth_handler.py:228-244** — `_html_response` interpoluje parametry bez `html.escape()`; aktualnie bezpieczne (hardcoded strings) ale fragile; dodaj escaping
- [ ] 🟡 [nit] **bot/services/google_auth.py:50-54** — `_get_encryption_key` zwraca zeroed key bez ostrzeżenia w produkcji; dodaj `logger.error` gdy env var pusty i TESTING!=1
- [ ] 🟡 [nit] **tests/test_google_tasks.py** — brak testu dla `delete_google_task` (zdefiniowany w planie technicznym linia 960)

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
