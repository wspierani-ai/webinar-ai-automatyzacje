---
title: "ADHD Reminder Bot — Plan Implementacji"
branch: feature/adhd-telegram-reminder-bot
status: active
created: 2026-04-09
last_updated: 2026-04-09
---

# ADHD Reminder Bot — Plan Implementacji

**Branch:** `feature/adhd-telegram-reminder-bot`
**Ostatnia aktualizacja:** 2026-04-09

## Podsumowanie wykonawcze

Bot Telegram dla ADHD-owców eliminujący barierę capture i utrzymania systemu. Jedyna wymagana akcja użytkownika to wysłanie wiadomości tekstowej lub głosowej. AI parsuje intencję i czas, bot scheduluje reminder, user reaguje jednym tapem.

**Stack:** Python FastAPI na Cloud Run, Gemini 2.5 Flash (Vertex AI), Cloud Tasks, Firestore, Stripe, GCP europe-central2.  
**Monetyzacja:** 7-dniowy free trial + 29.99 PLN/mies. przez Stripe.

## Cele i zakres

### Cele

1. Capture zadania < 5 sekund od pojawienia się myśli
2. Zero utrzymania systemu przez użytkownika
3. Konwersja trial → płatny > 30% po 30 dniach

### Granice scope'u (MVP)

- Tylko Telegram, tylko język polski
- Brak aplikacji mobilnej/desktopowej
- Brak integracji z mailem ani innymi komunikatorami
- Brak funkcji społecznościowych
- Brak wykrywania implied commitments
- Brak limitu liczby zadań (płatność to bramka, nie limit)

## Fazowe dostarczanie

| Faza | Zawartość | Cel |
|------|-----------|-----|
| Faza 1 — Core Bot | Units 1-8 | Działający bot: capture → parse → remind → snooze/done. Internal testing. |
| Faza 2 — Polish | Units 9-10 | Nudge system + auto-archival. Stability testing. |
| Faza 3 — Monetyzacja | Unit 11 | Stripe integration. Trial → payment flow. Launch publiczny. |
| Faza 4 — Google Integration | Units 12-14 | OAuth, Calendar sync, Tasks polling. Opcjonalne dla userów. |
| Faza 5 — Admin Dashboard + Security | Units 15-18 | Token tracking, admin UI, security hardening. |
| Faza 6 — Checklista + RODO | Units 19-21 | Szablony checklist, /delete_my_data. |

## Fazy implementacji i Implementation Units

---

### Faza A: Fundament

#### Unit 1: GCP Infrastructure + Project Scaffold (S)

**Cel:** Gotowe środowisko GCP, struktura projektu Python, Dockerfile, deployment config.  
**Wymagania:** Fundament techniczny dla R1-R10.  
**Zależności:** Brak.

**Pliki:**
- `adhd-bot/main.py` — FastAPI app entry point
- `adhd-bot/Dockerfile`
- `adhd-bot/requirements.txt`
- `adhd-bot/.env.example`
- `adhd-bot/cloud-run.yaml`
- `adhd-bot/bot/__init__.py`
- `adhd-bot/bot/config.py` — env vars, constants, fail-fast validation
- `adhd-bot/bot/handlers/__init__.py`
- `adhd-bot/bot/models/__init__.py`
- `adhd-bot/bot/services/__init__.py`
- `adhd-bot/tests/__init__.py`
- `adhd-bot/tests/test_config.py`

**Kryteria akceptacji:**
- `docker build` kończy się sukcesem
- `gcloud run deploy --min-instances=1` kończy się sukcesem
- `/health` zwraca 200 na Cloud Run URL
- Config validation rzuca `ValueError` gdy brakuje env vara

---

#### Unit 2: Telegram Webhook Receiver + Security + Deduplication (M)

**Cel:** Bezpieczny endpoint odbierający Telegram updates. Weryfikacja tokenu (security-first), odrzucanie starych updates, deduplication przez Firestore.  
**Wymagania:** R1 (fundament dla wszystkich flow).  
**Zależności:** Unit 1.

**Pliki:**
- `adhd-bot/bot/webhook.py` — FastAPI router dla `/telegram/webhook`
- `adhd-bot/bot/services/deduplication.py`
- `adhd-bot/bot/services/firestore_client.py` — singleton Firestore client
- `adhd-bot/tests/test_webhook_security.py`
- `adhd-bot/tests/test_deduplication.py`

**Kryteria akceptacji:**
- Request bez/z błędnym `X-Telegram-Bot-Api-Secret-Token` → 401
- Update starszy niż 120s → 200 (cichy odrzut)
- Duplicate `update_id` → 200 bez ponownego przetworzenia
- Telegram `/setWebhook` z `secret_token` zwraca success

---

### Faza B: Dane i Inteligencja

#### Unit 3: Firestore Data Layer + Task State Machine (M)

**Cel:** Modele danych dla User i Task, operacje CRUD, explicit state machine z dozwolonymi przejściami.  
**Wymagania:** R2, R5, R6, R9.  
**Zależności:** Unit 1.

**Pliki:**
- `adhd-bot/bot/models/user.py`
- `adhd-bot/bot/models/task.py`
- `adhd-bot/tests/test_user_model.py`
- `adhd-bot/tests/test_task_state_machine.py`

**State machine (dozwolone przejścia):**
```
PENDING_CONFIRMATION → SCHEDULED
SCHEDULED → REMINDED
REMINDED → SNOOZED | NUDGED | COMPLETED | REJECTED
NUDGED → SNOOZED | COMPLETED | REJECTED
SNOOZED → REMINDED
```

**Kryteria akceptacji:**
- Niedozwolone przejście → `InvalidStateTransitionError`
- COMPLETED/REJECTED ustawia `expires_at = now() + 30d`
- `User.get_or_create` atomicznie pobiera lub tworzy usera z defaults
- State machine pokrywa 100% macierzy przejść (valid i invalid)

---

#### Unit 4: Gemini AI Parser (tekst + głos → structured task) (M)

**Cel:** Parsowanie wiadomości przez Gemini 2.5 Flash → `{content, scheduled_time, confidence}`. Jeden request dla tekstu i audio.  
**Wymagania:** R2, R7.  
**Zależności:** Unit 1, Unit 3.

**Pliki:**
- `adhd-bot/bot/services/ai_parser.py`
- `adhd-bot/tests/test_ai_parser.py`

**Kryteria akceptacji:**
- Polskie wyrażenia czasowe poprawnie parsowane (DST-aware)
- `confidence < 0.65` → `scheduled_time = None`
- Voice bytes → wywołuje Gemini z `Part.from_data(mime_type="audio/ogg")`
- Gemini timeout/exception → graceful fallback bez propagacji wyjątku
- Manual smoke test: 5 polskich wiadomości → poprawne parsowanie

---

### Faza C: Harmonogram

#### Unit 5: Cloud Tasks Reminder Scheduler (M)

**Cel:** Schedule/cancel/reschedule reminders w Cloud Tasks. Atomiczne powiązanie z Firestore. Idempotent trigger endpoints.  
**Wymagania:** R4, R5 (snooze), R8 (nudge scheduling).  
**Zależności:** Unit 3.

**Pliki:**
- `adhd-bot/bot/services/scheduler.py`
- `adhd-bot/bot/handlers/internal_triggers.py` — `/internal/trigger-reminder`, `/internal/trigger-nudge`
- `adhd-bot/tests/test_scheduler.py`
- `adhd-bot/tests/test_internal_triggers.py`

**Task name format:** `reminder-{task_id}-{int(fire_at.timestamp())}`

**Kryteria akceptacji:**
- `cancel_reminder(None)` → return bez błędu
- `cancel_reminder` z `NOT_FOUND` → brak wyjątku
- `/internal/trigger-reminder` z `task.state = REMINDED` → 200 (idempotent guard)
- Cloud Task odpala w ciągu ±10s od `scheduled_time`
- Snooze: stary Cloud Task usunięty (brak duplikatów)

---

### Faza D: Flows Użytkownika

#### Unit 6: Onboarding Flow (/start, /timezone, /morning) (S)

**Cel:** Pierwsza interakcja — tworzenie usera, pytanie o strefę czasową. Komendy zarządzania ustawieniami.  
**Wymagania:** R9, Onboarding.  
**Zależności:** Unit 2, Unit 3.

**Pliki:**
- `adhd-bot/bot/handlers/command_handlers.py`
- `adhd-bot/tests/test_onboarding.py`

**Kryteria akceptacji:**
- `/start` dla nowego usera → `subscription_status="trial"`, `trial_ends_at=now+7d`
- `/start` dla istniejącego usera → brak resetowania statusu
- `/timezone Invalid/Zone` → błąd walidacji, brak zapisu
- `/morning 25:00` → błąd walidacji (nieprawidłowa godzina)

---

#### Unit 7: Task Capture Flow (wiadomość → parse → potwierdź → schedule) (L)

**Cel:** Główny flow: odbiór wiadomości tekstowej lub głosowej → Gemini parsing → potwierdzenie czasu → zapis → schedule.  
**Wymagania:** R1, R2, R3, R4, R7.  
**Zależności:** Unit 2, Unit 3, Unit 4, Unit 5, Unit 6.

**Pliki:**
- `adhd-bot/bot/handlers/message_handlers.py`
- Modyfikacja: `adhd-bot/bot/handlers/command_handlers.py` — obsługa conversation states
- `adhd-bot/tests/test_task_capture.py`

**Kryteria akceptacji:**
- Wiadomość z czasem → `PENDING_CONFIRMATION`, `proposed_time=parsed_time`, confirmation z buttons
- Wiadomość bez czasu → `proposed_time=heuristic`, confirmation z buttons
- Callback `[✓ OK]` → task `SCHEDULED`, Cloud Task created, buttons usunięte
- Callback `[Zmień]` → conversation state `awaiting_time_input`, prompt o nowy czas
- Blocked user → komunikat blokady, brak tworzenia tasku
- Pełny flow od wiadomości do scheduled Cloud Task działa E2E w staging

---

#### Unit 8: Reminder Delivery + Inline Button Callbacks (snooze/done/reject) (L)

**Cel:** Wysłanie wiadomości remindera z inline buttons. Obsługa 5 przycisków: snooze (3 opcje), done, reject.  
**Wymagania:** R4, R5, R9.  
**Zależności:** Unit 3, Unit 5, Unit 6.

**Pliki:**
- `adhd-bot/bot/handlers/callback_handlers.py`
- Modyfikacja: `adhd-bot/bot/handlers/internal_triggers.py` — format wiadomości remindera
- `adhd-bot/tests/test_reminder_callbacks.py`

**Kryteria akceptacji:**
- Snooze `+30min` → `new_fire_at = now+30m`, stary task cancelled, nowy created
- Snooze `morning` gdy `morning_time=None` → R9 flow triggered
- Done → `task.state=COMPLETED`, `expires_at` ustawiony, nudge cancelled
- Callback na task `COMPLETED` → `answerCallbackQuery`, brak błędu (idempotent)
- Edit message fail → wyślij nową wiadomość (degraded mode)
- Wszystkie 5 callback flows działają E2E w staging

---

### Faza E: Prace w tle

#### Unit 9: Nudge System (1h brak reakcji → gentle nudge) (S)

**Cel:** Po 1h od wysłania remindera bez akcji → jeden gentle nudge. Dokładnie jeden nudge per task.  
**Wymagania:** R8.  
**Zależności:** Unit 5, Unit 8.

**Pliki:**
- Modyfikacja: `adhd-bot/bot/handlers/internal_triggers.py` — implementacja `/internal/trigger-nudge`
- `adhd-bot/tests/test_nudge.py`

**Kryteria akceptacji:**
- `trigger-nudge` z `task.state=REMINDED` → wysyła nudge, `task.state=NUDGED`
- `trigger-nudge` z `task.state=COMPLETED` → 200, brak nudge (idempotent)
- Brak drugiego nudge: stan NUDGED nie scheduje kolejnego Cloud Task
- Task `REMINDED` przez 1h → nudge wysłany (staging: `fire_at=now+65s`)

---

#### Unit 10: Auto-Archival + Orphan Cloud Task Cleanup (M)

**Cel:** Firestore TTL auto-kasuje zadania po 30 dniach. Codziennie cleanup job porządkuje orphaned Cloud Tasks i aktualizuje statusy subskrypcji.  
**Wymagania:** R6.  
**Zależności:** Unit 3, Unit 5.

**Pliki:**
- `adhd-bot/infra/firestore-indexes.json` — TTL policy config
- `adhd-bot/bot/handlers/cleanup_handler.py` — Cloud Run endpoint `/internal/cleanup`
- `adhd-bot/infra/cloud-scheduler-cleanup.yaml`
- `adhd-bot/tests/test_cleanup.py`

**Harmonogram cleanup:** `0 3 * * *` (03:00 Europe/Warsaw)

**Kryteria akceptacji:**
- Cleanup aktualizuje `subscription_status="blocked"` dla expired trial i grace_period users
- `/internal/cleanup` bez OIDC auth → 401
- Task z `expires_at = now() - 31 days` znika z Firestore w ciągu 25h (TTL)
- Cleanup job w Cloud Scheduler widoczny jako `SUCCESS`

---

### Faza F: Monetyzacja

#### Unit 11: Stripe Subscription (trial, payment, grace period, blokada) (L)

**Cel:** 7-dniowy trial zarządzany lokalnie → Stripe Checkout → subskrypcja 29.99 PLN/mies. Grace period 3 dni. Blokada po grace period.  
**Wymagania:** R10.  
**Zależności:** Unit 3, Unit 6, Unit 10.

**Pliki:**
- `adhd-bot/bot/services/stripe_service.py`
- `adhd-bot/bot/handlers/stripe_webhook_handler.py` — `/stripe/webhook`
- `adhd-bot/bot/handlers/payment_command_handlers.py` — `/subscribe`, `/billing`
- `adhd-bot/tests/test_stripe_service.py`
- `adhd-bot/tests/test_stripe_webhooks.py`

**Obsługiwane Stripe eventy:** `checkout.session.completed`, `invoice.payment_failed`, `invoice.payment_succeeded`, `customer.subscription.deleted`

**Kryteria akceptacji:**
- Duplicate Stripe `event.id` → 200, brak drugiego przetworzenia
- Webhook z błędnym `STRIPE_WEBHOOK_SECRET` → 400
- Blocked user wysyła wiadomość → komunikat blokady + link `/subscribe`
- Stripe Dashboard pokazuje subskrypcję po pełnym `/subscribe` flow (E2E sandbox)

---

### Faza G: Integracja Google

#### Unit 12: Google OAuth 2.0 + Token Management (M)

**Cel:** User łączy konto Google przez OAuth 2.0. Tokeny przechowywane w Firestore z auto-refresh.  
**Wymagania:** R11, R12 (prerequisite dla Google sync).  
**Zależności:** Unit 3, Unit 6.

**Pliki:**
- `adhd-bot/bot/services/google_auth.py`
- `adhd-bot/bot/handlers/google_oauth_handler.py` — `/auth/google/callback`
- `adhd-bot/tests/test_google_auth.py`

**Kryteria akceptacji:**
- Callback ze złym/wygasłym `state` → 400
- `get_valid_token` wywołuje refresh gdy token wygasł
- Tokeny poprawnie zaszyfrowane w Firestore (brak plain text)
- Pełny OAuth flow E2E: kliknięcie linka → autoryzacja → bot wysyła potwierdzenie

---

#### Unit 13: Google Calendar Integration (jednostronna sync bot → Calendar) (M)

**Cel:** Bot tworzy/aktualizuje/usuwa Calendar events zsynchronizowane z taskami. Tylko bot → Calendar.  
**Wymagania:** R11.  
**Zależności:** Unit 12, Unit 5, Unit 3.

**Pliki:**
- `adhd-bot/bot/services/google_calendar.py`
- `adhd-bot/tests/test_google_calendar.py`

**Kryteria akceptacji:**
- `create_calendar_event` dla usera bez Google → skip, brak błędu
- Utwórz reminder → event pojawia się w Google Calendar
- Snooze → czas eventu zaktualizowany w Google Calendar
- Done → event zielony w kalendarzu

---

#### Unit 14: Google Tasks Integration (bot→Tasks + polling Tasks→bot) (M)

**Cel:** Bot tworzy Google Task przy ustawieniu remindera. Polling co 5 min wykrywa ukończenie w Google Tasks.  
**Wymagania:** R12.  
**Zależności:** Unit 12, Unit 3, Unit 8.

**Pliki:**
- `adhd-bot/bot/services/google_tasks.py`
- `adhd-bot/bot/handlers/gtasks_polling_handler.py` — `/internal/poll-google-tasks`
- `adhd-bot/tests/test_google_tasks.py`

**Uwaga:** Google Tasks API limit: 50,000 req/day. Przy >200 userach z polling co 5 min → zwiększ interval do 15 min.

**Kryteria akceptacji:**
- Oznacz task jako done w Google Tasks → po ≤5 min bot wysyła Telegram potwierdzenie
- Polling dla 0 userów z Google → 200, brak błędów
- `create_google_task` dla usera bez Google → skip, brak błędu

---

### Faza H: Admin Dashboard + Security

#### Unit 15: Gemini Token Usage Tracking (S)

**Cel:** Rejestrowanie zużycia tokenów Gemini per user per dzień. Podstawa dla cost analytics w dashboardzie.  
**Wymagania:** R13.  
**Zależności:** Unit 4.

**Pliki:**
- Modyfikacja: `adhd-bot/bot/services/ai_parser.py` — token tracking do każdego wywołania
- `adhd-bot/bot/services/token_tracker.py`
- `adhd-bot/tests/test_token_tracker.py`

**Firestore:** `token_usage/{YYYY-MM-DD}/{user_id}` — dzienne agregaty z atomic increment.

**Kryteria akceptacji:**
- `record_usage` nie blokuje parse_message (fire-and-forget)
- `record_usage` nie rzuca wyjątku gdy Firestore niedostępny (graceful fail)
- Koszt PLN bliski rzeczywistemu rachunkowi Vertex AI

---

#### Unit 16: Admin Authentication (Google SSO + Role Management) (M)

**Cel:** Zabezpieczony dostęp do dashboardu przez Google SSO. Role admin/read-only. JWT session cookie. Audit log.  
**Wymagania:** R14.  
**Zależności:** Unit 1, Unit 3.

**Pliki:**
- `adhd-bot/bot/admin/__init__.py`
- `adhd-bot/bot/admin/auth.py` — OAuth flow + JWT session
- `adhd-bot/bot/admin/middleware.py` — FastAPI dependency dla auth guard
- `adhd-bot/tests/test_admin_auth.py`

**JWT:** claims `{email, role, exp: now+8h}`. HttpOnly cookie `admin_session`.

**Kryteria akceptacji:**
- Email spoza whitelist → 403 bez dostępu
- Request z wygasłym JWT → redirect do `/admin/login`
- `require_admin_write` z role="read-only" → 403
- Audit log tworzony po każdej write akcji na `/admin/*`

---

#### Unit 17: Admin Dashboard API + Web UI (L)

**Cel:** API endpoints z danymi i minimalna strona webowa (Jinja2 + Tailwind + Alpine.js). Widoki: overview, lista klientów, szczegóły usera, przychody.  
**Wymagania:** R13, R14.  
**Zależności:** Unit 15, Unit 16, Unit 11.

**Pliki:**
- `adhd-bot/bot/admin/router.py` — FastAPI router `/admin/*`
- `adhd-bot/bot/admin/queries.py` — Firestore queries dla metryk
- `adhd-bot/templates/admin/base.html`
- `adhd-bot/templates/admin/dashboard.html`
- `adhd-bot/templates/admin/users.html`
- `adhd-bot/templates/admin/user_detail.html`
- `adhd-bot/tests/test_admin_queries.py`

**Kryteria akceptacji:**
- `PATCH /admin/api/users/{id}/subscription` z read-only auth → 403
- Dashboard ładuje się w przeglądarce z poprawnymi danymi
- Wykres MRR renderuje się z Chart.js

---

#### Unit 18: Security Hardening (M)

**Cel:** Szyfrowanie przez Cloud KMS, security headers, rate limiting, Firestore Security Rules, input validation.  
**Wymagania:** R15.  
**Zależności:** Wszystkie poprzednie unity (cross-cutting). Implementuj jako hardening pass na końcu.

**Pliki:**
- `adhd-bot/bot/security/__init__.py`
- `adhd-bot/bot/security/encryption.py` — Cloud KMS wrapper
- `adhd-bot/bot/security/rate_limiter.py` — slowapi config
- `adhd-bot/bot/security/headers.py` — FastAPI middleware
- `adhd-bot/bot/security/validators.py` — input validation helpers
- `adhd-bot/firestore.rules`
- Modyfikacja: `adhd-bot/main.py` — dodaj middleware
- Modyfikacja: `adhd-bot/bot/services/google_auth.py` — użyj encryption.py
- `adhd-bot/tests/test_security.py`

**Rate limits:** webhook 30/min per IP, `/auth/google/callback` 10/min per IP, admin 100/min per IP.

**Kryteria akceptacji:**
- Security headers obecne we wszystkich `/admin/*` responses
- Rate limiter zwraca 429 po przekroczeniu limitu
- Bezpośredni dostęp do Firestore REST API → permission denied
- Brak plain text sekretów w Cloud Run env vars

---

### Faza I: Checklista + RODO

#### Unit 19: Checklist Template Management (M)

**Cel:** Tworzenie i edycja szablonów checklist. AI sugeruje itemy. Komendy `/new_checklist`, `/checklists`, `/evening`.  
**Wymagania:** R17, R19.  
**Zależności:** Unit 3, Unit 4, Unit 6.

**Pliki:**
- `adhd-bot/bot/models/checklist.py`
- `adhd-bot/bot/handlers/checklist_command_handlers.py`
- `adhd-bot/bot/services/checklist_ai.py`
- `adhd-bot/tests/test_checklist_templates.py`

**Kryteria akceptacji:**
- Szablon z >12 itemami → błąd walidacji
- AI sugestie: sensowne itemy dla "Siłownia", "Praca", "Lotnisko"
- `/checklists` dla usera bez szablonów → "Nie masz jeszcze żadnych list"
- `/evening 25:00` → błąd walidacji

---

#### Unit 20: Checklist Session Flow (wieczorny + poranny reminder, item callbacks) (XL)

**Cel:** Tworzenie sesji checklisty po wykryciu eventu. Wieczorny reminder z pełną listą. Poranny z nieodznaczonymi. Odznaczanie itemów. Auto-zamknięcie.  
**Wymagania:** R18, R19.  
**Zależności:** Unit 19, Unit 4, Unit 5, Unit 7.

**Pliki:**
- `adhd-bot/bot/services/checklist_session.py`
- `adhd-bot/bot/handlers/checklist_callbacks.py`
- Modyfikacja: `adhd-bot/bot/handlers/internal_triggers.py` — trigger-checklist-evening, trigger-checklist-morning
- Modyfikacja: `adhd-bot/bot/handlers/message_handlers.py` — integracja Gemini event detection
- `adhd-bot/tests/test_checklist_session.py`

**Kryteria akceptacji:**
- Kliknięcie ostatniego itemu → auto-zamknięcie z komunikatem gratulacyjnym
- Sesja tworzona ze snapshot'em itemów (edycja szablonu po tym nie wpływa)
- trigger-checklist-morning gdy wszystkie zaznaczone → gratulacje bez listy

---

#### Unit 21: RODO — /delete_my_data + Polityka Prywatności (S)

**Cel:** Komenda `/delete_my_data` kasująca wszystkie dane usera. Statyczna strona z polityką prywatności.  
**Wymagania:** R16.  
**Zależności:** Unit 3.

**Pliki:**
- Modyfikacja: `adhd-bot/bot/handlers/command_handlers.py` — dodaj `/delete_my_data`
- `adhd-bot/templates/privacy_policy.html`
- `adhd-bot/tests/test_gdpr.py`

**Kryteria akceptacji:**
- `/delete_my_data` bez potwierdzenia → brak usunięcia
- Po potwierdzeniu: brak dokumentów usera w żadnej kolekcji Firestore
- Anuluje subskrypcję Stripe jeśli istnieje
- `/privacy` dostępne publicznie bez autentykacji (200 HTML)

---

## Ocena ryzyka

| Ryzyko | Prawdopodobieństwo | Mitygacja |
|--------|--------------------|-----------|
| Cloud Tasks cancellation race przy snoozie | Średnie | Idempotency guard w trigger-reminder (sprawdzenie state) |
| Gemini 2.5 Flash GA (kwiecień 2026) | Niskie | Pinować `gemini-2.5-flash-001` dla stabilności |
| Google Tasks rate limit (50k/day) | Średnie przy >200 userach | Zwiększyć interval do 15 min przy >150 userach |
| Firestore TTL eventual (delay do 24h) | Niskie | Filtry UI uwzględniają `expires_at < now()` |
| Google Calendar push channel expiry co 7 dni | Średnie | Cloud Scheduler renewal + fallback check przy każdym webhook |
| Google OAuth refresh_token w Firestore | Wysokie (security) | Cloud KMS encryption, Firestore Security Rules |
| Min-instances cost ($10-15/mies.) | Niskie | Akceptowalne dla stabilności webhooków |

## Metryki sukcesu

- Capture do scheduled Cloud Task < 5s od wysłania wiadomości
- Voice message processed < 8s (download + Gemini + response)
- Reminder delivery accuracy: ±30s od `scheduled_time`
- Zero duplicate reminders (Firestore state guards)
- Trial → subskrypcja conversion: > 30% po 30 dniach

## Źródła

- Requirements doc: `docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md`
- Plan techniczny: `docs/plans/2026-04-09-001-feat-adhd-telegram-reminder-bot-plan.md`
