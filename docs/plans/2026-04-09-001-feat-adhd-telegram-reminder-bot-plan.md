---
title: "feat: ADHD Reminder Bot — Telegram + GCP + Stripe"
type: feat
status: active
date: 2026-04-09
origin: docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md
---

# feat: ADHD Reminder Bot — Telegram + GCP + Stripe

## Przegląd

Bot Telegram dla ADHD-owców: minimalna akcja capture → AI-parsowanie → automatyczny reminder → snooze/done flow. Monetyzacja przez Stripe (7-dniowy trial + 29.99 PLN/mies.). Stack: Python FastAPI na Cloud Run, Gemini 2.5 Flash, Cloud Tasks, Firestore, Stripe. Region: europe-central2.

## Ujęcie problemu

ADHD-owcy płacą „podatek od ADHD" w czasie i pieniądzach: zapominają o zadaniach, nie inicjują działania, tracą kontekst przy przerwaniu. Istniejące narzędzia wymagają za dużo kroków przy capture i regularnego utrzymania systemu. Bot eliminuje obie bariery: jedyna wymagana akcja to wysłanie wiadomości, a system nie wymaga żadnego utrzymania przez użytkownika.

(zob. źródło: docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md)

## Śledzenie wymagań

- R1. Wiadomość tekstowa lub głosowa = jedyna wymagana akcja do zapisania zadania.
- R2. Gemini parsuje: treść zadania + czas remindera (jeśli podany).
- R3. Brak czasu → bot proponuje czas automatycznie + inline `[✓ OK] [Zmień]`.
- R4. Reminder w ustalonym czasie z oryginalnym kontekstem zadania.
- R5. Z poziomu remindera: `[+30 min] [+2h] [Jutro rano]` (snooze) lub `[✓ Zrobione] [✗ Odrzuć]`.
- R6. Brak utrzymania — ukończone/przeterminowane archiwizowane 30 dni, potem auto-kasowane.
- R7. Wiadomości głosowe transkrybowane i przetwarzane identycznie jak tekstowe.
- R8. Brak reakcji na reminder przez 1h → jeden gentle nudge z treścią zadania.
- R9. Przy pierwszym użyciu „Jutro rano" → bot pyta o preferowaną godzinę poranną i zapamiętuje.
- R10. 7-dniowy free trial → 29.99 PLN/mies. przez Stripe. Nieudana płatność → 3-dniowy grace period → blokada.
- R11. Google Calendar — jednostronna sync (bot → Calendar): bot tworzy event przy ustawieniu remindera; snooze aktualizuje czas eventu; ukończenie/odrzucenie aktualizuje event. Opcjonalne — user łączy przez `/connect-google`. Dwukierunkowa sync (GCal → bot) odłożona do v2.
- R12. Google Tasks — bot tworzy task przy ustawieniu remindera; ukończenie w bocie → Google Task done; zmiany w Google Tasks synkowane do bota przez polling (Cloud Scheduler co 5 min).
- R13. Admin dashboard (web): lista klientów + status subskrypcji, zużycie tokenów Gemini (koszt w PLN), aktywność (liczba tasków, ostatnia aktywność), przychody (MRR, ARR, churn, trial conversions).
- R14. Multi-user admin: Google SSO (email whitelist), role `admin`/`read-only`, audit log każdej akcji admina.
- R15. Security hardening: Cloud KMS dla wrażliwych danych, Secret Manager dla sekretów, rate limiting, security headers, CORS, input validation.
- R16. RODO/GDPR: komenda `/delete_my_data` kasująca wszystkie dane usera; statyczna strona z polityką prywatności pod publicznym URL.
- R17. Checklista — szablony: `/new_checklist` + AI sugestie itemów + edycja przez `/checklists`; max 12 itemów; bot pyta o zapisanie szablonu po pierwszym użyciu.
- R18. Checklista — flow: dwa remininery (wieczorny 21:00 via `/evening` + poranny via `/morning`); rano tylko nieodznaczone; każdy item = osobny button; ostatni item → auto-zamknięcie; snooze całej listy.
- R19. Checklista — wykrywanie: Gemini klasyfikuje event type; istniejący szablon → bot proponuje go bezpośrednio; brak szablonu przy event type → pyta "czy coś zabrać?"; `/evening` globalne dla wszystkich szablonów.

## Granice scope'u

- Brak natywnej aplikacji mobilnej/desktopowej.
- Brak integracji z mailem ani innymi zewnętrznymi źródłami (poza Google Calendar i Google Tasks).
- Brak webowego dashboardu.
- Tylko Telegram (nie WhatsApp, nie inne komunikatory).
- Brak funkcji społecznościowych (accountability partner, body double).
- Brak wykrywania implied commitments — user musi aktywnie wysłać zadanie.
- Tylko język polski w MVP.
- Brak limitu liczby zadań (płatność to bramka, nie limit funkcji).

## Kontekst i research

### Relevantny kod i wzorce

Projekt świeży — brak istniejącego kodu. Poniższe wzorce ustalone na podstawie research.

### Wiedza instytucjonalna

Brak wpisów w `docs/solutions/` dla tego projektu.

### Referencje zewnętrzne

- **Telegram webhook security**: weryfikacja `X-Telegram-Bot-Api-Secret-Token` PRZED parsowaniem body. Odrzucaj updates starsze niż 120s.
- **python-telegram-bot v21+**: najdojrzalsza async library dla Telegram + Python.
- **Cloud Tasks + snooze**: snooze = DELETE old task (ignore NOT_FOUND) + CREATE new task z deterministic task name.
- **Firestore TTL**: pole `expires_at` (Timestamp) — auto-delete po 30 dniach, z opóźnieniem do 24h.
- **Stripe webhooks**: dedup przez `stripe_events/{event_id}` w Firestore. Eventy: `invoice.payment_failed`, `customer.subscription.deleted`, `checkout.session.completed`, `invoice.payment_succeeded`.
- **Gemini 2.5 Flash**: structured JSON output mode (`response_mime_type: application/json`) dla deterministycznego parsowania. GA kwiecień 2026.
- **Cloud Run**: Python 3.12-slim + FastAPI + Gunicorn + Uvicorn. Min-instances=1 dla uniknięcia cold start na webhookach Telegram.

## Kluczowe decyzje techniczne

- **Python FastAPI zamiast Node.js/TypeScript**: python-telegram-bot v21 (async, najdojrzalszy), Vertex AI SDK dla Python. Startup time różnica (400-600ms Node vs 800-1200ms Python) jest akceptowalna z min-instances=1.
- **Firestore-only deduplication (bez Redis)**: deduplikacja `update_id` przez Firestore transaction. Redis dodaje zależność infrastrukturalną — dla MVP Firestore wystarczy (sub-100ms dla cloud-local calls w europe-central2).
- **State machine z 7 stanami**: `PENDING_CONFIRMATION → SCHEDULED → REMINDED → NUDGED / SNOOZED → COMPLETED / REJECTED`. Archiwizacja przez TTL (nie osobny stan).
- **Cloud Task name = `reminder-{task_id}-{fire_at_unix}`**: deterministyczny format umożliwia cancel przy snoozie bez osobnego przechowywania handle.
- **Grace period: custom logika w Firestore, nie Stripe built-in**: Stripe `payment_failed` webhook → zapisuje `grace_period_until = now() + 3 days` w Firestore. Daily cleanup job sprawdza wygasłe grace periods i ustawia `blocked`.
- **Zmień (R3)**: po kliknięciu bot wysyła wiadomość tekstową proszącą o wpisanie czasu. Prostsze niż inline time-picker.
- **Gemini confidence threshold = 0.65**: `confidence < 0.65` → `scheduled_time = None` → R3 flow (bot proponuje czas). Eliminuje potrzebę oddzielnego fallback modelu.
- **Wiadomości głosowe**: limit Telegrama = 60s (rzeczywiste ograniczenie). Gemini obsługuje bez dodatkowego limitowania.
- **"Jutro" = następny dzień od momentu wysłania** w strefie czasowej usera. DST-aware przez `zoneinfo` (Python stdlib).
- **Google OAuth 2.0**: Cloud Run obsługuje callback (`/auth/google/callback`). Tokeny (access + refresh) przechowywane w Firestore w dokumencie usera. Access_token wygasa co 1h — auto-refresh przez `google-auth` library.
- **Google Calendar — jednostronna sync (v1)**: tylko bot → Calendar. Tworzenie/aktualizacja/usuwanie eventów. Brak webhooków GCal w v1 — dwukierunkowa sync odłożona do v2.
- **Google Calendar push notifications**: `events.watch()` — kanały wygasają co 7 dni. Cloud Scheduler co 6 dni odnawia kanały dla aktywnych userów z połączonym kontem Google.
- **Google Tasks polling**: Google Tasks API (2026) nie ma push notifications. Cloud Scheduler co 5 min odpytuje Tasks dla userów z połączonym kontem. `nextSyncToken` dla delta queries.
- **Integracja opcjonalna**: bot działa w pełni bez Google. User łączy konto przez `/connect-google`. Brak połączenia = brak sync, core flow bez zmian.
- **Admin dashboard UI**: Jinja2 templates + Tailwind CSS (CDN) + Alpine.js serwowane przez FastAPI na `/admin/*`. Brak osobnego buildu frontendu — jeden Cloud Run service. Charts przez Chart.js CDN. Wystarczające dla kilku adminów.
- **Admin auth: Google SSO** (nie hasła) — admini logują się przez Google OAuth. Whitelist dozwolonych emaili w Firestore kolekcji `admin_users`. JWT session cookie (HttpOnly, Secure, SameSite=Strict) z TTL 8h. Brak haseł do zarządzania i wycieku.
- **Token usage tracking**: każde wywołanie Gemini API zwraca `usage_metadata` (input/output tokens). Zapisywane do kolekcji `token_usage/{YYYY-MM}/{user_id}` jako dzienne agregaty. Koszt w PLN kalkulowany na podstawie cennika Vertex AI.
- **Szyfrowanie wrażliwych danych**: Google refresh tokens i access tokens szyfrowane przez Cloud KMS (symetryczny klucz per-environment). Telegram user IDs i treści tasków nie są szyfrowane (wymagają wyszukiwania), ale Firestore Security Rules blokują bezpośredni dostęp.
- **Security headers**: middleware FastAPI dodaje HSTS, CSP, X-Frame-Options, X-Content-Type-Options do wszystkich odpowiedzi. CORS: whitelist tylko własna domena admina.
- **Rate limiting**: `slowapi` library (FastAPI) — limity per IP i per user_id. Telegram webhook: 30 req/s. Admin API: 100 req/min per IP. Stripe webhook: unlimited (Stripe IPs whitelisted).

## Otwarte pytania

### Rozwiązane podczas planowania

- **Snooze race condition**: Firestore transaction atomicznie aktualizuje stan taska + zapisuje nowy cloud_task_name. trigger-reminder endpoint sprawdza state przed wysyłką (idempotency guard).
- **Message ID persistence failure**: task document zawiera `reminder_message_id`. Na callback → editMessageReplyMarkup. Jeśli edit failuje → wyślij nową wiadomość (degraded mode).
- **answerCallbackQuery timing**: wywoływane natychmiast jako pierwsze (zapobiega spinnerowi Telegram po ~3s).
- **Stripe subscription creation timing**: Stripe customer tworzony przy `/start` bez payment method. Trial zarządzany lokalnie przez Firestore + cleanup job. Stripe Checkout uruchamiany przez `/subscribe` po wygaśnięciu trialu.
- **Blocking behavior**: gdy `subscription_status = blocked`, bot odpowiada na każdą wiadomość komunikatem blokady + link do Stripe. Żadne nowe Cloud Tasks nie są tworzone.
- **Concurrent reminders (R6)**: Cloud Tasks gwarantuje at-least-once delivery. State guard w trigger-reminder zapobiega wysyłce duplikatów.

### Odroczone do implementacji

- **Gemini prompt dla polskich wyrażeń czasowych**: konkretny prompt wymaga iteracji z rzeczywistymi wiadomościami testowymi.
- **Cloud Tasks queue konfiguracja**: max dispatch rate i max concurrent dispatches — zależne od obserwowanego traffic pattern.
- **Stripe Price ID**: tworzony ręcznie w Stripe Dashboard przed deployem production.
- **Smart time suggestion (R3)**: algorytm proponowania czasu gdy user go nie podał — do ustalenia w implementacji (np. "za 2 godziny" jako default, lub time-of-day heuristic).

## Implementation Units

### Faza A: Fundament

- [ ] **Unit 1: GCP Infrastructure + Project Scaffold**

**Cel:** Gotowe środowisko GCP, struktura projektu Python, Dockerfile, deployment config. Punkt startowy dla wszystkich kolejnych unitów.

**Wymagania:** Fundament techniczny dla R1-R10.

**Zależności:** Brak.

**Pliki:**
- Stwórz: `adhd-bot/main.py` (FastAPI app entry point)
- Stwórz: `adhd-bot/Dockerfile`
- Stwórz: `adhd-bot/requirements.txt`
- Stwórz: `adhd-bot/.env.example`
- Stwórz: `adhd-bot/cloud-run.yaml`
- Stwórz: `adhd-bot/bot/__init__.py`
- Stwórz: `adhd-bot/bot/config.py` (env vars, constants, fail-fast validation)
- Stwórz: `adhd-bot/bot/handlers/__init__.py`
- Stwórz: `adhd-bot/bot/models/__init__.py`
- Stwórz: `adhd-bot/bot/services/__init__.py`
- Stwórz: `adhd-bot/tests/__init__.py`
- Stwórz: `adhd-bot/tests/test_config.py`

**Podejście:**
- Dependencies: `fastapi`, `python-telegram-bot[webhooks]>=21`, `google-cloud-aiplatform`, `google-cloud-tasks`, `google-cloud-firestore`, `stripe`, `uvicorn`, `gunicorn`
- Dockerfile: `FROM python:3.12-slim-bullseye`. CMD: `gunicorn --workers=2 --worker-class=uvicorn.workers.UvicornWorker --bind=0.0.0.0:8080 --timeout=60 main:app`
- `bot/config.py`: dataclass z wszystkimi env vars, `__post_init__` waliduje required vars — fail-fast przy starcie
- Cloud Run: `min-instances=1`, `memory=512Mi`, `timeout=60`, `concurrency=80`, `region=europe-central2`
- Secret Manager: TELEGRAM_BOT_TOKEN, TELEGRAM_SECRET_TOKEN, STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, GCP_PROJECT_ID
- Dwie Cloud Tasks kolejki: `reminders`, `nudges`
- `main.py`: endpoint `/health` → 200 OK

**Wzorce do naśladowania:**
- Dockerfile z research: `python:3.12-slim` + `gunicorn --worker-class=uvicorn.workers.UvicornWorker`

**Scenariusze testowe:**
- [Unit] Config validation rzuca `ValueError` gdy brakuje wymaganego env var
- [Unit] Config poprawnie ładuje zmienne z environment
- [Unit] `/health` endpoint zwraca `{"status": "healthy"}` z kodem 200

**Weryfikacja:**
- `docker build` kończy się sukcesem
- `gcloud run deploy --min-instances=1` kończy się sukcesem
- `/health` zwraca 200 na Cloud Run URL

---

- [ ] **Unit 2: Telegram Webhook Receiver + Security + Deduplication**

**Cel:** Bezpieczny endpoint odbierający Telegram updates. Weryfikacja tokenu (security-first), odrzucanie starych updates, deduplication przez Firestore.

**Wymagania:** R1 (fundament dla wszystkich flow).

**Zależności:** Unit 1.

**Pliki:**
- Stwórz: `adhd-bot/bot/webhook.py` (FastAPI router dla `/telegram/webhook`)
- Stwórz: `adhd-bot/bot/services/deduplication.py`
- Stwórz: `adhd-bot/bot/services/firestore_client.py` (singleton Firestore client)
- Stwórz: `adhd-bot/tests/test_webhook_security.py`
- Stwórz: `adhd-bot/tests/test_deduplication.py`

**Podejście:**

Kolejność operacji w `/telegram/webhook POST`:
1. Weryfikuj `X-Telegram-Bot-Api-Secret-Token` header PRZED `await request.json()` → 401 jeśli brak/niepoprawny
2. Odrzuć update jeśli `message.date < now() - 120s` → return 200 (cicho, nie błąd)
3. Deduplication: Firestore kolekcja `processed_updates/{update_id}` z TTL field `expires_at = now() + 24h`. Jeśli dokument istnieje → return 200. Jeśli nie → atomic Firestore transaction: create doc + dispatch update
4. Routing: `message.text` → text handler, `message.voice` → voice handler, `callback_query` → callback handler, `/start` `/timezone` `/morning` `/subscribe` `/billing` → command handler
5. Return 200 natychmiast (Telegram nie retry'uje 200)

`deduplication.py`: `is_duplicate(update_id: int) -> bool` + `mark_processed(update_id: int)` — Firestore transaction dla atomiczności.

**Wzorce do naśladowania:**
- Research: token check PRZED body parse (resource exhaustion prevention)
- Firestore transaction dla atomic check-and-set

**Scenariusze testowe:**
- [Unit] Request bez `X-Telegram-Bot-Api-Secret-Token` → 401
- [Unit] Request z błędnym secret token → 401
- [Unit] Request z poprawnym tokenem → 200
- [Unit] Update z `message.date` starszym niż 120s → 200 (odrzucony cicho)
- [Unit] Duplicate `update_id` → 200, `mark_processed` nie wywoływany drugi raz
- [Unit] Nowy `update_id` → dokument tworzony w `processed_updates`

**Weryfikacja:**
- Telegram `/setWebhook` call z `secret_token` zwraca success
- Testowy update od Telegram dociera i jest procesowany
- Duplicate test update nie powoduje podwójnego przetworzenia (Firestore)

---

### Faza B: Dane i Inteligencja

- [ ] **Unit 3: Firestore Data Layer + Task State Machine**

**Cel:** Modele danych dla User i Task, operacje CRUD, explicit state machine z dozwolonymi przejściami. Fundament dla całego lifecycle zadania.

**Wymagania:** R2, R5, R6, R9 (dane przez cały lifecycle).

**Zależności:** Unit 1.

**Pliki:**
- Stwórz: `adhd-bot/bot/models/user.py`
- Stwórz: `adhd-bot/bot/models/task.py`
- Stwórz: `adhd-bot/tests/test_user_model.py`
- Stwórz: `adhd-bot/tests/test_task_state_machine.py`

**Podejście:**

**Firestore kolekcja `users/{telegram_user_id}`:**
```
timezone: str                        # IANA format, default "Europe/Warsaw"
morning_time: str | null             # "HH:MM", ustawiane przy R9
subscription_status: str             # "trial" | "active" | "grace_period" | "blocked"
trial_ends_at: Timestamp
grace_period_until: Timestamp | null
stripe_customer_id: str | null
stripe_subscription_id: str | null
google_access_token: str | null      # szyfrowany, wygasa co 1h
google_refresh_token: str | null     # szyfrowany, długotrwały
google_token_expiry: Timestamp | null
google_calendar_id: str | null       # ID kalendarza (zazwyczaj "primary")
google_tasks_list_id: str | null     # ID listy Google Tasks
google_cal_watch_channel_id: str | null  # ID aktywnego push channel
google_cal_watch_expiry: Timestamp | null  # wygaśnięcie push channel
google_tasks_sync_token: str | null  # nextSyncToken dla delta queries
created_at: Timestamp
```

**Firestore kolekcja `tasks/{task_id}`** (task_id = nanoid 12 znaków):
```
user_id: str
content: str
state: str                          # TaskState enum value
proposed_time: Timestamp | null
scheduled_time: Timestamp | null
reminded_at: Timestamp | null
nudged_at: Timestamp | null
snoozed_until: Timestamp | null
completed_at: Timestamp | null
rejected_at: Timestamp | null
cloud_task_name: str | null         # Cloud Tasks task name dla cancel
nudge_task_name: str | null         # Cloud Tasks name dla nudge cancel
reminder_message_id: int | null     # Telegram message_id dla edit
google_calendar_event_id: str | null  # GCal event ID (null gdy brak integracji)
google_tasks_task_id: str | null      # Google Tasks task ID
created_at: Timestamp
expires_at: Timestamp | null        # TTL — ustawiany przy COMPLETED/REJECTED + 30 dni
```

**Task State Machine (enum `TaskState`):**

Dozwolone przejścia (allowlist):
```
PENDING_CONFIRMATION → SCHEDULED
SCHEDULED → REMINDED
REMINDED → SNOOZED
REMINDED → NUDGED
REMINDED → COMPLETED
REMINDED → REJECTED
NUDGED → SNOOZED
NUDGED → COMPLETED
NUDGED → REJECTED
SNOOZED → REMINDED
```

Metoda `task.transition(new_state: TaskState)`:
- Sprawdza czy przejście dozwolone → rzuca `InvalidStateTransitionError(AppError)` jeśli nie
- Ustawia odpowiednie timestamp fields (`completed_at`, `rejected_at`, itp.)
- Przy COMPLETED/REJECTED: `expires_at = now() + 30 days`

**User model:**
- `User.get_or_create(telegram_user_id) -> User`: atomicznie pobiera lub tworzy usera z defaults
- `User.is_subscription_active() -> bool`: zwraca `True` dla "trial" (gdy `trial_ends_at > now()`), "active", "grace_period"

**Wzorce do naśladowania:**
- Allowlist transitions zamiast free-form strings
- `nanoid` (biblioteka) dla task_id

**Scenariusze testowe:**
- [Unit] `task.transition(PENDING_CONFIRMATION → SCHEDULED)` → sukces, state zmieniony
- [Unit] `task.transition(SCHEDULED → COMPLETED)` → rzuca `InvalidStateTransitionError`
- [Unit] `task.transition(REMINDED → COMPLETED)` → `expires_at = now() + 30d`, `completed_at` ustawiony
- [Unit] `task.transition(REMINDED → REJECTED)` → `expires_at = now() + 30d`, `rejected_at` ustawiony
- [Unit] `User.get_or_create` tworzy nowego usera z `timezone="Europe/Warsaw"`, `subscription_status="trial"`
- [Unit] `User.get_or_create` zwraca istniejącego usera bez nadpisania pól
- [Unit] `User.is_subscription_active()` → `False` gdy `subscription_status="blocked"`
- [Unit] `User.is_subscription_active()` → `False` gdy `subscription_status="trial"` i `trial_ends_at < now()`

**Weryfikacja:**
- State machine testy obejmują 100% macierzy przejść (valid i invalid)
- Firestore CRUD działa na Firestore emulatorze (lokalnie)

---

- [ ] **Unit 4: Gemini AI Parser (tekst + głos → structured task)**

**Cel:** Parsowanie wiadomości przez Gemini 2.5 Flash → `{ content, scheduled_time, confidence }`. Jeden request dla tekstu i audio (R7).

**Wymagania:** R2, R7.

**Zależności:** Unit 1, Unit 3.

**Pliki:**
- Stwórz: `adhd-bot/bot/services/ai_parser.py`
- Stwórz: `adhd-bot/tests/test_ai_parser.py`

**Podejście:**

**Dataclass `ParsedTask`:**
```python
@dataclass
class ParsedTask:
    content: str | None          # None = parse failure
    scheduled_time: datetime | None
    confidence: float            # 0.0-1.0
    is_morning_snooze: bool      # True gdy wykryto "jutro rano" bez konkretnej godziny
```

**`parse_message(text: str, user_timezone: str, current_time: datetime) -> ParsedTask`:**
- Model: `gemini-2.5-flash-001` via Vertex AI SDK
- `generation_config={"response_mime_type": "application/json"}`
- System prompt: parsowanie polskich wyrażeń czasowych relative do `current_time` w `user_timezone`. DST-aware przez `zoneinfo`.
- JSON schema output: `{content, scheduled_time_iso8601, confidence, is_morning_snooze}`
- Timeout: 10s (`asyncio.wait_for`)
- Jeśli `confidence < 0.65` → `scheduled_time = None`
- Exception → `ParsedTask(content=None, scheduled_time=None, confidence=0.0)`

**`parse_voice_message(voice_bytes: bytes, user_timezone: str, current_time: datetime) -> ParsedTask`:**
- Encode audio: `base64.standard_b64encode(voice_bytes)`
- Gemini call: `[Part.from_data(mime_type="audio/ogg", data=audio_b64), prompt_text]`
- Jeden request: transkrypcja + parsowanie (R7: bez osobnego STT API)
- Ten sam fallback co `parse_message`

**Gemini fallback gdy `content is None`:**
- Wywołujący (message_handler) wyśle: "Nie udało mi się przetworzyć wiadomości. Spróbuj napisać jako tekst."

**Wzorce do naśladowania:**
- Research: `generation_config={"response_mime_type": "application/json"}` dla structured output
- Research: non-streaming dla deterministycznych wyników

**Scenariusze testowe:**
- [Unit] "Kupić mleko jutro o 17" → `content="Kupić mleko"`, `scheduled_time=tomorrow 17:00`, `confidence>0.65`
- [Unit] "Kupić mleko" (brak czasu) → `scheduled_time=None`, `confidence<0.65`
- [Unit] "Za 2 godziny zadzwonić do mamy" → `scheduled_time=now+2h`, `confidence>0.65`
- [Unit] "Jutro rano umyć auto" → `is_morning_snooze=True`, `scheduled_time=None`
- [Unit] Gemini timeout/exception → `ParsedTask(content=None, confidence=0.0)` bez propagacji wyjątku
- [Unit] Voice bytes (mock) → wywołuje Gemini z `Part.from_data(mime_type="audio/ogg")`

**Weryfikacja:**
- Testy z mock Gemini response przechodzą
- Manual smoke test: 5 polskich wiadomości → poprawne parsowanie

---

### Faza C: Harmonogram

- [ ] **Unit 5: Cloud Tasks Reminder Scheduler**

**Cel:** Schedule/cancel/reschedule reminders w Cloud Tasks. Atomiczne powiązanie z Firestore. Idempotent trigger endpoints.

**Wymagania:** R4, R5 (snooze), R8 (nudge scheduling).

**Zależności:** Unit 3.

**Pliki:**
- Stwórz: `adhd-bot/bot/services/scheduler.py`
- Stwórz: `adhd-bot/bot/handlers/internal_triggers.py` (endpointy `/internal/trigger-reminder`, `/internal/trigger-nudge`)
- Stwórz: `adhd-bot/tests/test_scheduler.py`
- Stwórz: `adhd-bot/tests/test_internal_triggers.py`

**Podejście:**

**`schedule_reminder(task_id: str, fire_at: datetime) -> str`** (zwraca cloud_task_name):
- Task name: `projects/{proj}/locations/{loc}/queues/reminders/tasks/reminder-{task_id}-{int(fire_at.timestamp())}`
- HTTP target: `POST /internal/trigger-reminder` z body `{"task_id": task_id}`
- OIDC authentication header dla Cloud Run auth
- Return: pełna task name

**`cancel_reminder(cloud_task_name: str | None)`:**
- Jeśli `cloud_task_name is None` → return (brak tasku do cancel)
- `tasks_client.delete_task(name=cloud_task_name)` — ignore `NOT_FOUND` exception

**`snooze_reminder(task_id: str, old_task_name: str | None, new_fire_at: datetime) -> str`:**
- Firestore transaction: `task.transition(→ SNOOZED)`, `task.snoozed_until = new_fire_at`
- `cancel_reminder(old_task_name)` (outside transaction — eventually consistent)
- `schedule_reminder(task_id, new_fire_at)` → nowy task name
- Update Firestore: `task.cloud_task_name = new_task_name`
- Return: nowy cloud_task_name

**`/internal/trigger-reminder` POST:**
- Auth: weryfikacja OIDC token (Cloud Tasks service account header)
- Pobierz task z Firestore
- Jeśli `task.state != SCHEDULED` → return 200 (idempotent guard)
- Wyślij reminder message przez Telegram Bot API z inline buttons
- Zapisz `reminder_message_id` w task document
- `task.transition(→ REMINDED)`, `reminded_at = now()`
- Schedule nudge task za 60 min (queue `nudges`): task name `nudge-{task_id}-{int(now().timestamp())}`
- Zapisz `nudge_task_name` w task document

**`/internal/trigger-nudge` POST:**
- Auth: OIDC token
- Pobierz task
- Jeśli `task.state != REMINDED` → return 200 (user już zareagował)
- Wyślij **nową wiadomość** (nie edit) z treścią nudge + te same inline buttons
- `task.transition(→ NUDGED)`, `nudged_at = now()`

**Wzorce do naśladowania:**
- Research: deterministic task name = cancel bez przechowywania handle
- Research: ignore `NOT_FOUND` przy delete

**Scenariusze testowe:**
- [Unit] `schedule_reminder` tworzy Cloud Task z poprawnym `schedule_time`
- [Unit] `cancel_reminder(None)` → return bez błędu
- [Unit] `cancel_reminder` z `NOT_FOUND` → brak wyjątku
- [Unit] `snooze_reminder` atomicznie aktualizuje Firestore + tworzy nowy Cloud Task
- [Unit] `/internal/trigger-reminder` z `task.state = REMINDED` → 200, brak wysyłki (idempotent)
- [Unit] `/internal/trigger-nudge` z `task.state = SNOOZED` → 200, brak nudge

**Weryfikacja:**
- Cloud Task odpala w ciągu ±10s od `scheduled_time` (test z delay=30s)
- Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

### Faza D: Flows Użytkownika

- [ ] **Unit 6: Onboarding Flow (/start, /timezone, /morning)**

**Cel:** Pierwsza interakcja — tworzenie usera, pytanie o strefę czasową. Komendy /timezone i /morning do zarządzania ustawieniami.

**Wymagania:** R9 (morning time przy pierwszym użyciu „Jutro rano"), Onboarding (spec).

**Zależności:** Unit 2, Unit 3.

**Pliki:**
- Stwórz: `adhd-bot/bot/handlers/command_handlers.py`
- Stwórz: `adhd-bot/tests/test_onboarding.py`

**Podejście:**

**`/start` handler:**
1. `User.get_or_create(telegram_user_id)` z defaults: `subscription_status="trial"`, `trial_ends_at=now()+7d`, `timezone="Europe/Warsaw"`
2. Jeśli nowy user: wyślij powitalną wiadomość + pytanie o strefę czasową z inline buttons: `[🇵🇱 Europe/Warsaw] [Inna →]`
3. Jeśli istniejący user: wyślij powitanie bez pytania o timezone
4. Kliknięcie `[🇵🇱 Europe/Warsaw]` → zapisuje "Europe/Warsaw", potwierdza
5. Kliknięcie `[Inna →]` → wyślij "Wpisz strefę czasową (np. Europe/London)"

**`/timezone` handler:**
- Wyślij prośbę o wpisanie IANA timezone
- Kolejna wiadomość od usera (conversation state: `awaiting_timezone: true` w Firestore z TTL=10 min)
- Waliduj: `timezone_str in zoneinfo.available_timezones()`
- Zapisz, potwierdź: "Strefa czasowa ustawiona na {timezone}"
- Błąd walidacji: "Nieznana strefa. Sprawdź listę na en.wikipedia.org/wiki/List_of_tz_database_time_zones"

**`/morning [HH:MM]` handler:**
- Z argumentem `/morning 08:30` → waliduj HH:MM (regex `^\d{2}:\d{2}$`, 00-23:00-59) → zapisz
- Bez argumentu → wyślij prośbę, conversation state `awaiting_morning_time: true`
- Potwierdź: "Godzina 'Jutro rano' ustawiona na {time}"

**Automatyczny R9 flow (wywoływany z callback_handler):**
- Gdy user kliknie [Jutro rano] i `user.morning_time is None`
- Bot: "O której chcesz dostawać 'Jutro rano' remininery? (np. 08:30)"
- Conversation state: `awaiting_morning_time: true` + `pending_morning_task_id: {task_id}`
- Kolejna wiadomość → parse jako godzina → zapisz → kontynuuj snooze flow

**Conversation state** przechowywany jako field w `users/{user_id}` z `conversation_state: {type, expires_at}`.

**Scenariusze testowe:**
- [Unit] `/start` dla nowego usera tworzy dokument z `subscription_status="trial"`, `trial_ends_at=now+7d`
- [Unit] `/start` dla istniejącego usera nie resetuje `subscription_status`
- [Unit] `/timezone Europe/Warsaw` → `user.timezone = "Europe/Warsaw"`, potwierdza
- [Unit] `/timezone Invalid/Zone` → błąd walidacji, brak zapisu
- [Unit] `/morning 08:30` → `user.morning_time = "08:30"`, potwierdza
- [Unit] `/morning 25:00` → błąd walidacji (nieprawidłowa godzina)

**Weryfikacja:**
- Nowy user po `/start` ma `subscription_status="trial"` i `trial_ends_at` za 7 dni w Firestore
- `/timezone` i `/morning` poprawnie aktualizują user document

---

- [ ] **Unit 7: Task Capture Flow (wiadomość → parse → potwierdź → schedule)**

**Cel:** Główny flow: odbiór wiadomości tekstowej lub głosowej → Gemini parsing → potwierdzenie czasu → zapis → schedule.

**Wymagania:** R1, R2, R3, R4, R7.

**Zależności:** Unit 2, Unit 3, Unit 4, Unit 5, Unit 6.

**Pliki:**
- Stwórz: `adhd-bot/bot/handlers/message_handlers.py`
- Modyfikuj: `adhd-bot/bot/handlers/command_handlers.py` (dodaj obsługę conversation states)
- Stwórz: `adhd-bot/tests/test_task_capture.py`

**Podejście:**

**Subscription guard (sprawdzany przed każdym handlerem):**
- Pobierz usera. Jeśli `subscription_status = "blocked"` → wyślij komunikat blokady + `/subscribe` link → return
- Jeśli `subscription_status = "trial"` i `trial_ends_at < now()` → cleanup job powinien był zmienić, ale guard też sprawdza i aktualizuje

**Text message handler:**
1. Sprawdź subscription guard
2. Sprawdź conversation state (`awaiting_timezone`, `awaiting_morning_time`, `awaiting_time_input`) — jeśli aktywny, obsłuż jako input do conversation, nie jako nowe zadanie
3. `parsed = await ai_parser.parse_message(text, user.timezone, now())`
4. Utwórz task document (state=`PENDING_CONFIRMATION`, `content=parsed.content or text`)
5. Jeśli `parsed.scheduled_time` i `confidence >= 0.65`:
   - `proposed_time = parsed.scheduled_time`
   - Wyślij: "Przypomnę Ci o **{content}** {formatted_time}" + buttons `[✓ OK] [Zmień]`
6. Jeśli `scheduled_time is None` lub `confidence < 0.65`:
   - Bot proponuje czas (heuristic: `now() + 2h` lub inna logika do ustalenia w implementacji)
   - `proposed_time = heuristic_time`
   - Wyślij: "Zapisałem! Przypomnę Ci o **{content}** {proposed_time_formatted}" + buttons `[✓ OK] [Zmień]`
7. Zapisz `proposed_time` w task document, zapisz `confirm_message_id`

**Voice message handler:**
1. Subscription guard
2. `file = await bot.get_file(voice.file_id)`, pobierz bytes
3. `parsed = await ai_parser.parse_voice_message(bytes, user.timezone, now())`
4. Jeśli `parsed.content is None` → "Nie udało się przetworzyć głosówki 🎤 Wyślij jako tekst."
5. Kontynuuj identycznie jak text handler od kroku 4

**Callback: `[✓ OK]`:**
- `answerCallbackQuery` natychmiast
- `task.transition(→ SCHEDULED)`
- `cloud_task_name = await scheduler.schedule_reminder(task_id, task.proposed_time)`
- Zapisz `cloud_task_name` w task document
- Edit wiadomości: usuń buttons, "✅ Przypomnę Ci {formatted_time}!"

**Callback: `[Zmień]`:**
- `answerCallbackQuery`
- Wyślij: "Kiedy mam Ci przypomnieć? (np. 'jutro o 9', 'za 3 godziny')"
- Conversation state: `awaiting_time_input: task_id`
- Kolejna wiadomość → parse jako czas → nowe proposed_time → nowe confirmation message

**Wzorce do naśladowania:**
- `answerCallbackQuery` jako pierwsze wywołanie w każdym callback handler

**Scenariusze testowe:**
- [Unit] "Kupić mleko jutro o 17" → task `PENDING_CONFIRMATION`, `proposed_time=tomorrow 17:00`, confirmation message z buttons
- [Unit] "Kupić mleko" (brak czasu) → task `PENDING_CONFIRMATION`, `proposed_time=heuristic`, confirmation z buttons
- [Unit] Voice (mock parsed `content="Zadzwonić do mamy"`) → identyczny flow jak text
- [Unit] Voice `content=None` (parse fail) → komunikat "wyślij jako tekst"
- [Unit] Callback `[✓ OK]` → task `SCHEDULED`, Cloud Task created, buttons usunięte
- [Unit] Callback `[Zmień]` → conversation state `awaiting_time_input`, prompt o nowy czas
- [Unit] Blocked user → komunikat blokady, brak tworzenia tasku
- [E2E] Wiadomość "Przypomnij o kawie za 2 minuty" → po ~2 min otrzymać reminder

**Weryfikacja:**
- Pełny flow od wiadomości do scheduled Cloud Task działa end-to-end w staging
- Task w stanie `SCHEDULED` z poprawnym `scheduled_time` widoczny w Firestore

---

- [ ] **Unit 8: Reminder Delivery + Inline Button Callbacks (snooze/done/reject)**

**Cel:** Wysłanie wiadomości remindera z inline buttons. Obsługa wszystkich 5 przycisków: snooze (3 opcje), done, reject. R9 flow dla pierwszego „Jutro rano".

**Wymagania:** R4, R5, R9.

**Zależności:** Unit 3, Unit 5, Unit 6.

**Pliki:**
- Stwórz: `adhd-bot/bot/handlers/callback_handlers.py` (kompletny)
- Modyfikuj: `adhd-bot/bot/handlers/internal_triggers.py` (reminder message format)
- Stwórz: `adhd-bot/tests/test_reminder_callbacks.py`

**Podejście:**

**Reminder message format** (wysyłane przez `trigger-reminder`):
```
🔔 Przypomnienie: {task.content}

Dodano: {task.created_at | format: '%d.%m o %H:%M'}
```
Inline keyboard:
```
[+30 min]  [+2h]  [Jutro rano]
[✓ Zrobione]    [✗ Odrzuć]
```

**Callback data encoding**: `snooze:30m:{task_id}`, `snooze:2h:{task_id}`, `snooze:morning:{task_id}`, `done:{task_id}`, `reject:{task_id}`

**Snooze callback (ogólny pattern):**
1. `answerCallbackQuery(show_alert=False)` — ZAWSZE jako pierwsze
2. Pobierz task; jeśli state nie pozwala na snooze (COMPLETED, REJECTED) → cicha odpowiedź
3. Oblicz `new_fire_at` od `now()` (nie od original time)
4. Wywołaj `scheduler.snooze_reminder(task_id, task.cloud_task_name, new_fire_at)`
5. Edit reminder message: usuń buttons, dodaj "💤 Przypomnę o {new_fire_at_formatted}"

**Snooze „Jutro rano":**
- Jeśli `user.morning_time is None` → R9 flow (patrz Unit 6 "Automatyczny R9 flow")
- Jeśli `user.morning_time` ustawiony → `new_fire_at = tomorrow + morning_time` (DST-aware)

**Done callback:**
1. `answerCallbackQuery`
2. Cancel nudge task: `scheduler.cancel_reminder(task.nudge_task_name)`
3. `task.transition(→ COMPLETED)` (ustawia `expires_at`, `completed_at`)
4. Edit message: usuń buttons, "✅ Zrobione! Dobra robota 🎉"

**Reject callback:**
1. `answerCallbackQuery`
2. Cancel nudge task
3. `task.transition(→ REJECTED)` (ustawia `expires_at`, `rejected_at`)
4. Edit message: usuń buttons, "✗ Odrzucone"

**Fallback gdy edit failuje** (np. `reminder_message_id` brak lub Telegram API error):
- Wyślij nową wiadomość zamiast edit (degraded mode, bez błędu dla usera)

**Scenariusze testowe:**
- [Unit] Snooze `+30min` → `new_fire_at = now+30m`, stary Cloud Task cancelled, nowy created
- [Unit] Snooze `+2h` → `new_fire_at = now+2h`
- [Unit] Snooze `morning` gdy `morning_time="08:30"` → `new_fire_at = tomorrow 08:30`
- [Unit] Snooze `morning` gdy `morning_time=None` → R9 flow triggered
- [Unit] Done → `task.state=COMPLETED`, `expires_at` ustawiony, nudge cancelled
- [Unit] Reject → `task.state=REJECTED`, `expires_at` ustawiony
- [Unit] Callback na task `COMPLETED` → `answerCallbackQuery`, brak błędu (idempotent)
- [Unit] Edit message fail → wyślij nową wiadomość (degraded mode)
- [E2E] Kliknij `[+30 min]` na reminderze → wiadomość edytowana, nowy reminder za 30 min

**Weryfikacja:**
- Wszystkie 5 callback flows działają end-to-end w staging
- Snooze: stary Cloud Task usunięty (brak duplikatów w GCP Console)

---

### Faza E: Prace w tle

- [ ] **Unit 9: Nudge System (1h brak reakcji → gentle nudge)**

**Cel:** Po 1h od wysłania remindera bez akcji → jeden gentle nudge. Dokładnie jeden nudge per task.

**Wymagania:** R8.

**Zależności:** Unit 5, Unit 8.

**Pliki:**
- Modyfikuj: `adhd-bot/bot/handlers/internal_triggers.py` (implementacja `/internal/trigger-nudge`)
- Stwórz: `adhd-bot/tests/test_nudge.py`

**Podejście:**

**Scheduling nudge** (wewnątrz `trigger-reminder`):
- Po wysłaniu reminder message: schedule nudge Cloud Task za 60 min
- Queue: `nudges`, task name: `nudge-{task_id}-{int(now().timestamp())}`
- Zapisz `nudge_task_name` w task document

**`/internal/trigger-nudge` handler:**
1. OIDC auth
2. Pobierz task
3. Jeśli `task.state != REMINDED` → return 200 (user zareagował, state-based guard)
4. Wyślij **nową wiadomość** (nie edit) z treścią:
   ```
   🔔 Hej, jeszcze to masz do zrobienia: {task.content}
   ```
   Z identycznymi inline buttons jak reminder
5. `task.transition(→ NUDGED)`, `nudged_at = now()`

**Brak drugiego nudge**: stan NUDGED nie ma zaplanowanego kolejnego Cloud Task. User musi podjąć akcję lub task archiwizuje się przez TTL.

**Scenariusze testowe:**
- [Unit] `trigger-nudge` z `task.state=REMINDED` → wysyła nudge message, `task.state=NUDGED`
- [Unit] `trigger-nudge` z `task.state=COMPLETED` → 200, brak nudge
- [Unit] `trigger-nudge` z `task.state=SNOOZED` → 200, brak nudge
- [Unit] `trigger-nudge` z `task.state=NUDGED` → 200, brak drugiego nudge (idempotent)
- [Unit] Nudge message zawiera `task.content`

**Weryfikacja:**
- Task w `REMINDED` przez 1h → nudge wysłany (test staging z `fire_at=now+65s`)
- Task `COMPLETED` przed upływem 1h → nudge nie wysłany (sprawdź Firestore state)

---

- [ ] **Unit 10: Auto-Archival + Orphan Cloud Task Cleanup**

**Cel:** Firestore TTL auto-kasuje zadania po 30 dniach. Codziennie cleanup job porządkuje orphaned Cloud Tasks i aktualizuje statusy subskrypcji.

**Wymagania:** R6.

**Zależności:** Unit 3, Unit 5.

**Pliki:**
- Stwórz: `adhd-bot/infra/firestore-indexes.json` (TTL policy config)
- Stwórz: `adhd-bot/bot/handlers/cleanup_handler.py` (Cloud Run endpoint)
- Stwórz: `adhd-bot/infra/cloud-scheduler-cleanup.yaml`
- Stwórz: `adhd-bot/tests/test_cleanup.py`

**Podejście:**

**Firestore TTL:**
- Kolekcja `tasks`, pole `expires_at` (Timestamp)
- TTL policy: Firestore automatycznie usuwa dokumenty gdy `expires_at < now()` (z opóźnieniem do 24h)
- Konfiguracja przez `gcloud firestore fields ttls update expires_at --collection-group=tasks`

**Cleanup job (Cloud Scheduler → Cloud Run):**
- Harmonogram: `0 3 * * *` (codziennie 03:00 Europe/Warsaw)
- Endpoint: `POST /internal/cleanup` z OIDC auth
- Zadania cleanup:
  1. Userzy z `subscription_status="trial"` i `trial_ends_at < now()`: → `subscription_status="blocked"` (jeśli brak aktywnej Stripe subscription)
  2. Userzy z `subscription_status="grace_period"` i `grace_period_until < now()`: → `subscription_status="blocked"`, wyślij Telegram notification
  3. Taski z `expires_at < now() - 25h` i `cloud_task_name != null`: delete Cloud Task (orphan cleanup, ignore NOT_FOUND)
  4. Taski z `expires_at < now() - 25h` i `nudge_task_name != null`: delete nudge Cloud Task

**Batch operacje:** Firestore query z `limit=500`, batch delete dla performance.

**Uwaga:** TTL jest eventual — dokument z `expires_at` w przeszłości może być widoczny przez kilka godzin. UI powinno filtrować po `expires_at`.

**Scenariusze testowe:**
- [Unit] Cleanup aktualizuje `subscription_status="blocked"` dla expired trial users
- [Unit] Cleanup aktualizuje `subscription_status="blocked"` dla expired grace_period users
- [Unit] Cleanup usuwa orphaned Cloud Tasks (mock tasks_client)
- [Unit] Cleanup z pustą listą → 200, brak błędów
- [Unit] `/internal/cleanup` bez OIDC auth → 401

**Weryfikacja:**
- Task z `expires_at = now() - 31 days` znika z Firestore w ciągu 25h (TTL propagation)
- Cleanup job w Cloud Scheduler widoczny jako `SUCCESS` w GCP Console

---

### Faza F: Monetyzacja

- [ ] **Unit 11: Stripe Subscription (trial, payment, grace period, blokada)**

**Cel:** 7-dniowy trial zarządzany lokalnie → Stripe Checkout → subskrypcja 29.99 PLN/mies. Grace period 3 dni przy failed payment. Blokada po grace period.

**Wymagania:** R10.

**Zależności:** Unit 3, Unit 6, Unit 10 (cleanup aktualizuje statusy).

**Pliki:**
- Stwórz: `adhd-bot/bot/services/stripe_service.py`
- Stwórz: `adhd-bot/bot/handlers/stripe_webhook_handler.py` (router dla `/stripe/webhook`)
- Stwórz: `adhd-bot/bot/handlers/payment_command_handlers.py` (`/subscribe`, `/billing`)
- Stwórz: `adhd-bot/tests/test_stripe_service.py`
- Stwórz: `adhd-bot/tests/test_stripe_webhooks.py`

**Podejście:**

**Trial flow:**
- Przy `/start`: `stripe.Customer.create(metadata={"telegram_user_id": user_id})` → zapisz `stripe_customer_id`
- Trial zarządzany przez Firestore (`trial_ends_at`, `subscription_status="trial"`)
- Brak Stripe Subscription podczas trialu

**Po wygaśnięciu trialu (cleanup job):**
- `subscription_status = "blocked"`
- Na następną wiadomość: "Twój 7-dniowy trial wygasł ⏰ Subskrybuj za 29.99 PLN/mies.: /subscribe"

**`/subscribe` komenda:**
- `stripe.checkout.Session.create(mode="subscription", customer=customer_id, line_items=[{price: STRIPE_PRICE_ID}], currency="PLN")`
- Wyślij URL do Stripe Checkout
- Po płatności: Stripe webhook `checkout.session.completed` → aktualizuj status

**`/billing` komenda:**
- `stripe.billing_portal.Session.create(customer=customer_id)` → wyślij URL
- User zarządza kartą/anulowaniem przez Stripe Portal

**Stripe Webhook handler (`/stripe/webhook`):**
1. Weryfikacja: `stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)` → 400 jeśli invalid
2. Deduplication: `stripe_events/{event.id}` w Firestore → return 200 jeśli duplicate
3. Pobierz `telegram_user_id` z `event.data.object.metadata` lub przez `stripe_subscription_id`

Obsługiwane eventy:
- `checkout.session.completed`: `subscription_status="active"`, zapisz `stripe_subscription_id`
- `invoice.payment_failed`: `subscription_status="grace_period"`, `grace_period_until=now()+3d`. Wyślij Telegram: "Płatność nie powiodła się 💳 Masz 3 dni na aktualizację karty: /billing"
- `invoice.payment_succeeded`: `subscription_status="active"`, wyczyść `grace_period_until`
- `customer.subscription.deleted`: `subscription_status="blocked"`. Wyślij: "Subskrypcja anulowana. Wznów przez /subscribe."

**Scenariusze testowe:**
- [Unit] `/subscribe` tworzy Stripe Checkout Session z `currency="PLN"`, poprawnym `price_id`
- [Unit] `checkout.session.completed` webhook → `subscription_status="active"`, `stripe_subscription_id` zapisany
- [Unit] `invoice.payment_failed` webhook → `subscription_status="grace_period"`, `grace_period_until=now+3d`
- [Unit] `invoice.payment_succeeded` webhook → `subscription_status="active"`, `grace_period_until=None`
- [Unit] `customer.subscription.deleted` webhook → `subscription_status="blocked"`
- [Unit] Duplicate Stripe `event.id` → 200, brak drugiego przetworzenia
- [Unit] Webhook z błędnym `STRIPE_WEBHOOK_SECRET` → 400
- [Unit] Blocked user wysyła wiadomość → komunikat blokady + link `/subscribe`
- [E2E] Przejdź przez Stripe Checkout Sandbox → `subscription_status="active"` w Firestore

**Weryfikacja:**
- Stripe Dashboard pokazuje subskrypcję po pełnym `/subscribe` flow
- `payment_failed` webhook aktualizuje status w Firestore w ciągu 30s
- Blocked user nie inicjuje nowych Cloud Tasks

---

### Faza G: Integracja Google

- [ ] **Unit 12: Google OAuth 2.0 + Token Management**

**Cel:** User łączy konto Google przez OAuth 2.0. Tokeny przechowywane w Firestore z auto-refresh. Komendy `/connect-google` i `/disconnect-google`.

**Wymagania:** R11, R12 (prerequisite dla Google sync).

**Zależności:** Unit 3, Unit 6.

**Pliki:**
- Stwórz: `adhd-bot/bot/services/google_auth.py`
- Stwórz: `adhd-bot/bot/handlers/google_oauth_handler.py` (endpoint `/auth/google/callback`)
- Stwórz: `adhd-bot/tests/test_google_auth.py`

**Podejście:**

**`/connect-google` komenda:**
1. Generuj OAuth state token (nanoid, TTL=10 min, przechowuj w Firestore `oauth_states/{state}`)
2. Zbuduj Google OAuth URL: `accounts.google.com/o/oauth2/auth` z scope: `calendar`, `tasks`, `calendar.events`, `openid`
3. Wyślij link do Telegram: "Kliknij aby połączyć Google: {url}"

**`/auth/google/callback` GET endpoint:**
1. Zweryfikuj `state` param → pobierz `user_id` z `oauth_states`, sprawdź TTL
2. Wymień `code` na tokeny: `google.oauth2.flow.Flow.from_client_config(...).fetch_token(code=code)`
3. Pobierz `access_token`, `refresh_token`, `token_expiry`
4. Zapisz w Firestore `users/{user_id}`: szyfruj tokeny przez AES-256 (klucz z Secret Manager), zapisz `google_token_expiry`
5. Pobierz ID kalendarza (`calendar.calendarList().get('primary')`) i listy Tasks (`tasks.tasklists().list()` → pierwsza lista)
6. Zapisz `google_calendar_id`, `google_tasks_list_id`
7. Zamknij okno przeglądarki z komunikatem "Połączono! Wróć do Telegram."
8. Bot wysyła do usera przez Telegram: "✅ Konto Google połączone! Od teraz twoje zadania będą synchronizowane z Google Calendar i Google Tasks."

**`/disconnect-google` komenda:**
- Usuń tokeny z Firestore
- Anuluj push channel (`events.stop({channelId, resourceId})`)
- Potwierdź przez Telegram

**Auto-refresh access_token:**
- `google_auth.get_valid_token(user_id)`: jeśli `token_expiry < now() + 5min` → refresh przez `google.oauth2.credentials.Credentials.refresh()`
- Zapisz nowy `access_token` i `token_expiry`
- Jeśli refresh fail (refresh_token revoked) → oznacz Google jako disconnected, powiadom usera

**Scenariusze testowe:**
- [Unit] `/connect-google` generuje poprawny OAuth URL ze wszystkimi wymaganymi scope'ami
- [Unit] Callback ze złym `state` → 400, brak zapisu tokenów
- [Unit] Callback z wygasłym `state` (TTL) → 400
- [Unit] `get_valid_token` wywołuje refresh gdy token wygasł
- [Unit] `get_valid_token` nie wywołuje refresh gdy token ważny
- [Unit] Refresh fail → user oznaczony jako disconnected, Telegram notification

**Weryfikacja:**
- Pełny OAuth flow end-to-end: kliknięcie linka → autoryzacja Google → powrót → bot wysyła potwierdzenie
- Tokeny poprawnie zaszyfrowane w Firestore (brak plain text)

---

- [ ] **Unit 13: Google Calendar Integration (jednostronna sync bot → Calendar)**

**Cel:** Bot tworzy/aktualizuje/usuwa Calendar events zsynchronizowane z taskami. Wyłącznie jednostronna sync — bot pisze do Kalendarza, nie odbiera zmian z GCal (v2).

**Wymagania:** R11.

**Zależności:** Unit 12, Unit 5 (scheduler), Unit 3 (task model).

**Pliki:**
- Stwórz: `adhd-bot/bot/services/google_calendar.py`
- Stwórz: `adhd-bot/tests/test_google_calendar.py`

**Podejście:**

`create_calendar_event(user_id, task) -> event_id`:
- `get_valid_token(user_id)` → jeśli brak/disconnected → skip (integracja opcjonalna)
- `calendar.events().insert(calendarId=user.google_calendar_id, body={summary: task.content, start: {dateTime: scheduled_time}, end: {dateTime: scheduled_time+30min}, description: "Zadanie z ADHD Bot"})`
- Zapisz `google_calendar_event_id` w task document
- Wywołane z Unit 7 po `task.transition(→ SCHEDULED)`

`update_calendar_event_time(user_id, task, new_time)`:
- `calendar.events().patch(eventId=task.google_calendar_event_id, body={start, end})`
- Wywołane przy snoozie (Unit 8)

`complete_calendar_event(user_id, task)`:
- Patch: `colorId: "2"` (zielony = done) + `summary` prefix "✅ "
- Wywołane przy COMPLETED

`delete_calendar_event(user_id, task)`:
- `calendar.events().delete(eventId=task.google_calendar_event_id)`
- Wywołane przy REJECTED

**v2 (nie implementowane teraz):** GCal → Bot sync przez push notifications (`events.watch()`), renewal job, conflict resolution.

**Scenariusze testowe:**
- [Unit] `create_calendar_event` tworzy event z poprawnym `scheduled_time`
- [Unit] `create_calendar_event` dla usera bez Google → skip, brak błędu
- [Unit] `update_calendar_event_time` wywołuje `events.patch` z nowym czasem
- [Unit] `complete_calendar_event` wywołuje patch z zielonym kolorem
- [Unit] `delete_calendar_event` wywołuje events.delete

**Weryfikacja:**
- Utwórz reminder w bocie → event pojawia się w Google Calendar w europe-central2
- Snooze → czas eventu zaktualizowany w Google Calendar
- Done → event zielony w kalendarzu

---

- [ ] **Unit 14: Google Tasks Integration (bot→Tasks + polling Tasks→bot)**

**Cel:** Bot tworzy Google Task przy ustawieniu remindera. Ukończenie w bocie → Google Task done. Polling co 5 min wykrywa ukończenie w Google Tasks i oznacza task w bocie.

**Wymagania:** R12.

**Zależności:** Unit 12, Unit 3, Unit 8.

**Pliki:**
- Stwórz: `adhd-bot/bot/services/google_tasks.py`
- Stwórz: `adhd-bot/bot/handlers/gtasks_polling_handler.py` (endpoint `/internal/poll-google-tasks`)
- Stwórz: `adhd-bot/tests/test_google_tasks.py`

**Podejście:**

**Bot → Google Tasks (sync outbound):**

`create_google_task(user_id, task) -> google_task_id`:
- `get_valid_token(user_id)` → skip jeśli brak
- `tasks.tasks().insert(tasklist=user.google_tasks_list_id, body={title: task.content, due: scheduled_time_rfc3339, notes: "Zadanie z ADHD Bot"})`
- Zapisz `google_tasks_task_id` w task document
- Wywołane z Unit 7 po `task.transition(→ SCHEDULED)`

`complete_google_task(user_id, task)`:
- `tasks.tasks().patch(tasklist=..., task=task.google_tasks_task_id, body={status: "completed"})`
- Wywołane przy COMPLETED

`delete_google_task(user_id, task)`:
- `tasks.tasks().delete(tasklist=..., task=task.google_tasks_task_id)`
- Wywołane przy REJECTED

**Google Tasks → Bot (polling):**

**`/internal/poll-google-tasks` POST (Cloud Scheduler co 5 min):**
1. Pobierz userów z `google_refresh_token != null` (aktywna integracja Google)
2. Dla każdego usera (batch, max 100 userów per invocation):
   - `tasks.tasks().list(tasklist=..., updatedMin=last_poll_time, showCompleted=true, showHidden=true)`
   - Jeśli API wspiera: użyj `nextSyncToken` z poprzedniego poll (delta queries)
   - Dla każdego completed Google Task: znajdź task po `google_tasks_task_id`
   - Jeśli task state REMINDED/NUDGED/SCHEDULED i Google Task `status: "completed"`:
     - `task.transition(→ COMPLETED)`, anuluj Cloud Tasks
     - Wyślij Telegram: "✅ Zadanie ukończone w Google Tasks: {task.content}"
3. Zapisz `last_poll_time` i `google_tasks_sync_token` w user document

**Ograniczenia Google Tasks API:**
- Brak webhooków → polling jest jedynym sposobem
- Rate limit: 50,000 requests/day per project. Przy 1000 userach i poll co 5 min = 288,000 requests/day → limit bliski. Dla >200 userów zwiększ interval do 15 min lub użyj batch requests.

**Scenariusze testowe:**
- [Unit] `create_google_task` tworzy task z poprawnym `title` i `due`
- [Unit] `create_google_task` dla usera bez Google → skip, brak błędu
- [Unit] `complete_google_task` wywołuje `tasks.patch` ze `status: "completed"`
- [Unit] Polling: Google Task `status: "completed"` → bot task → COMPLETED, Telegram notification
- [Unit] Polling: Google Task nie zmieniony → brak akcji
- [Unit] Polling dla 0 userów z Google → 200, brak błędów

**Weryfikacja:**
- Utwórz reminder → task pojawia się w Google Tasks
- Oznacz task jako done w Google Tasks → po ≤5 min bot wysyła Telegram potwierdzenie
- Ukończ task w bocie → Google Task oznaczony jako done

---

### Faza H: Admin Dashboard + Security

- [ ] **Unit 15: Gemini Token Usage Tracking**

**Cel:** Rejestrowanie zużycia tokenów Gemini per user per dzień. Podstawa dla cost analytics w dashboardzie.

**Wymagania:** R13 (zużycie tokenów w dashboardzie).

**Zależności:** Unit 4 (Gemini parser).

**Pliki:**
- Modyfikuj: `adhd-bot/bot/services/ai_parser.py` (dodaj token tracking do każdego wywołania)
- Stwórz: `adhd-bot/bot/services/token_tracker.py`
- Stwórz: `adhd-bot/tests/test_token_tracker.py`

**Podejście:**

**Firestore kolekcja `token_usage/{YYYY-MM-DD}/{user_id}`:**
```
input_tokens: int      # suma input tokens tego dnia
output_tokens: int     # suma output tokens tego dnia
call_count: int        # liczba wywołań Gemini
cost_pln: float        # szacunkowy koszt (kalkulowany)
updated_at: Timestamp
```

**`token_tracker.record_usage(user_id, usage_metadata)`:**
- Pobierz `usage_metadata.prompt_token_count` i `candidates_token_count` z Gemini response
- Koszt PLN: `input_tokens * 0.30/1_000_000 * 4.0` (PLN) + `output_tokens * 2.50/1_000_000 * 4.0` (kurs 4.0 PLN/USD dla Vertex AI pricing)
- Firestore: `increment` na `input_tokens`, `output_tokens`, `call_count`, `cost_pln` (atomic increment)
- Fire-and-forget (async, nie blokuje response do usera)

**Integracja w `ai_parser.py`:**
- Po każdym `model.generate_content(...)` → `asyncio.create_task(token_tracker.record_usage(user_id, response.usage_metadata))`

**Miesięczne agregaty** (dla dashboard MRR view):
- Kolekcja `token_usage_monthly/{YYYY-MM}/{user_id}` aktualizowana przez cleanup job (Unit 10)

**Scenariusze testowe:**
- [Unit] `record_usage` zapisuje poprawne wartości w Firestore (atomic increment)
- [Unit] Koszt PLN kalkulowany poprawnie dla znanych token counts
- [Unit] `record_usage` nie blokuje parse_message (fire-and-forget)
- [Unit] `record_usage` nie rzuca wyjątku gdy Firestore niedostępny (graceful fail)

**Weryfikacja:**
- Po 5 wywołaniach Gemini: kolekcja `token_usage` zawiera poprawne sumy
- Koszt PLN bliski rzeczywistemu rachunkowi Vertex AI

---

- [ ] **Unit 16: Admin Authentication (Google SSO + Role Management)**

**Cel:** Zabezpieczony dostęp do dashboardu przez Google SSO. Role admin/read-only. JWT session cookie. Audit log.

**Wymagania:** R14.

**Zależności:** Unit 1, Unit 3.

**Pliki:**
- Stwórz: `adhd-bot/bot/admin/__init__.py`
- Stwórz: `adhd-bot/bot/admin/auth.py` (OAuth flow + JWT session)
- Stwórz: `adhd-bot/bot/admin/middleware.py` (FastAPI dependency dla auth guard)
- Stwórz: `adhd-bot/tests/test_admin_auth.py`

**Podejście:**

**Firestore kolekcja `admin_users/{email}`:**
```
role: "admin" | "read-only"
name: str
added_by: str         # email admina który dodał
added_at: Timestamp
last_login: Timestamp
```

**OAuth flow:**
- `GET /admin/login` → redirect do Google OAuth URL (scope: `openid email profile`)
- `GET /admin/auth/callback?code=...` → wymień code na Google ID token → zweryfikuj email w `admin_users` → jeśli istnieje: utwórz JWT session → set HttpOnly cookie `admin_session`
- JWT claims: `{email, role, exp: now+8h}`. Podpisany kluczem z Secret Manager (`ADMIN_JWT_SECRET`)
- `GET /admin/logout` → wyczyść cookie

**FastAPI dependency `require_admin(role="read-only")`:**
- Pobierz `admin_session` cookie → decode JWT → sprawdź `exp` → sprawdź `role`
- Jeśli invalid/expired → redirect do `/admin/login`
- Dostępne jako `Depends(require_admin)` i `Depends(require_admin_write)` (role="admin")

**Audit log** — Firestore kolekcja `admin_audit_log`:
```
timestamp: Timestamp
admin_email: str
action: str           # "view_user", "change_role", "export_data"
target: str | null    # user_id lub inny obiekt akcji
ip: str
user_agent: str
```
Logowane automatycznie przez middleware dla wszystkich `POST`/`PATCH`/`DELETE` na `/admin/*`.

**Scenariusze testowe:**
- [Unit] Callback z emailem nie w `admin_users` → 403
- [Unit] Callback z poprawnym emailem → JWT cookie ustawiony, redirect do `/admin`
- [Unit] Request bez cookie → redirect do `/admin/login`
- [Unit] Request z wygasłym JWT → redirect do `/admin/login`
- [Unit] `require_admin_write` z role="read-only" → 403
- [Unit] POST /admin/* → audit log tworzony z poprawnym email i action

**Weryfikacja:**
- Logowanie przez Google → dostęp do dashboardu
- Email spoza whitelist → 403 bez dostępu
- Audit log widoczny w Firestore po każdej write akcji

---

- [ ] **Unit 17: Admin Dashboard API + Web UI**

**Cel:** API endpoints z danymi i minimalna strona webowa (Jinja2 + Tailwind + Alpine.js). Widoki: overview, lista klientów, szczegóły usera, przychody.

**Wymagania:** R13, R14.

**Zależności:** Unit 15, Unit 16, Unit 11 (Stripe data).

**Pliki:**
- Stwórz: `adhd-bot/bot/admin/router.py` (FastAPI router `/admin/*`)
- Stwórz: `adhd-bot/bot/admin/queries.py` (Firestore queries dla metryk)
- Stwórz: `adhd-bot/templates/admin/base.html`
- Stwórz: `adhd-bot/templates/admin/dashboard.html` (overview)
- Stwórz: `adhd-bot/templates/admin/users.html` (lista klientów)
- Stwórz: `adhd-bot/templates/admin/user_detail.html` (szczegóły)
- Stwórz: `adhd-bot/tests/test_admin_queries.py`

**Podejście:**

**API Endpoints (JSON, używane przez Alpine.js):**

`GET /admin/api/overview` (require read-only):
```json
{
  "total_users": 150,
  "active_subscriptions": 87,
  "trial_users": 23,
  "blocked_users": 5,
  "mrr_pln": 2600.13,
  "arr_pln": 31201.56,
  "trial_conversion_rate": 0.34,
  "total_gemini_cost_pln_this_month": 45.20,
  "churn_rate_last_30d": 0.05
}
```

`GET /admin/api/users?status=&search=&page=&limit=50` (require read-only):
- Zwraca paginowaną listę userów z: `user_id`, `created_at`, `subscription_status`, `trial_ends_at`, `last_activity`, `task_count`, `token_cost_this_month_pln`
- Filter by `subscription_status`
- Search by `user_id` (Telegram ID)

`GET /admin/api/users/{user_id}` (require read-only):
- Szczegóły usera: historia zadań (ostatnie 20), token usage per dzień (ostatnie 30 dni), historia płatności (z Stripe API), subscription details

`PATCH /admin/api/users/{user_id}/subscription` (require admin):
- Body: `{action: "unblock" | "extend_trial_days"}` — ręczne zarządzanie subskrypcjami
- Audit log wymagany

`GET /admin/api/revenue` (require read-only):
- MRR, ARR, churn rate, trial conversions — dane z Firestore + Stripe

**Web UI (Jinja2 templates serwowane przez FastAPI):**

`GET /admin` → `dashboard.html`:
- Cards: Total users, Active, MRR, Gemini cost this month
- Wykres MRR (ostatnie 6 miesięcy) — Chart.js CDN
- Wykres trial conversions

`GET /admin/users` → `users.html`:
- Tabela z paginacją, filtrem po statusie, wyszukiwarką
- Kolumny: Telegram ID, Status (badge kolorowy), Ostatnia aktywność, Taski, Koszt tokenów, Subskrypcja do

`GET /admin/users/{user_id}` → `user_detail.html`:
- Header z kluczowymi danymi usera
- Sekcje: Historia subskrypcji, Token usage (wykres dzienny), Ostatnie zadania, Akcje admina (unblock, extend trial)

**Obliczanie MRR:**
- Firestore: count aktywnych subskrypcji × 29.99 PLN
- Churn: userzy którzy z `active` przeszli do `blocked` w ostatnich 30 dniach / total active 30 dni temu

**Scenariusze testowe:**
- [Unit] `GET /admin/api/overview` bez auth → redirect do login
- [Unit] `GET /admin/api/overview` z read-only auth → 200 z poprawnymi polami
- [Unit] `PATCH /admin/api/users/{id}/subscription` z read-only auth → 403
- [Unit] `PATCH /admin/api/users/{id}/subscription` z admin auth → 200, audit log created
- [Unit] Query `users` z filter `status=blocked` → tylko blocked userzy

**Weryfikacja:**
- Dashboard ładuje się w przeglądarce z poprawnymi danymi
- Lista userów pokazuje poprawne statusy
- Wykres MRR renderuje się z Chart.js

---

- [ ] **Unit 18: Security Hardening**

**Cel:** Szyfrowanie wrażliwych danych przez Cloud KMS, security headers, rate limiting, Firestore Security Rules, input validation. Przekrojowe — modyfikuje wiele istniejących modułów.

**Wymagania:** R15.

**Zależności:** Wszystkie poprzednie unity (cross-cutting).

**Notatka wykonawcza:** Implementuj na końcu jako hardening pass — nie blokuj wcześniejszych faz tym unitem. Każda sekcja może być wdrożona niezależnie.

**Pliki:**
- Stwórz: `adhd-bot/bot/security/__init__.py`
- Stwórz: `adhd-bot/bot/security/encryption.py` (Cloud KMS wrapper)
- Stwórz: `adhd-bot/bot/security/rate_limiter.py` (slowapi config)
- Stwórz: `adhd-bot/bot/security/headers.py` (FastAPI middleware)
- Stwórz: `adhd-bot/bot/security/validators.py` (input validation helpers)
- Stwórz: `adhd-bot/firestore.rules` (Firestore Security Rules)
- Modyfikuj: `adhd-bot/main.py` (dodaj middleware)
- Modyfikuj: `adhd-bot/bot/services/google_auth.py` (użyj encryption.py dla tokenów)
- Stwórz: `adhd-bot/tests/test_security.py`

**Podejście:**

**1. Szyfrowanie przez Cloud KMS:**
`encryption.py` — wrapper:
- `encrypt(plaintext: str) -> str`: wywołuje Cloud KMS `cryptoKeyVersions.encrypt`, zwraca base64 ciphertext
- `decrypt(ciphertext: str) -> str`: Cloud KMS `cryptoKeyVersions.decrypt`
- Użyj: Google OAuth refresh_token i access_token w Firestore (Units 12-13)
- Klucz: `projects/{proj}/locations/europe-central2/keyRings/adhd-bot/cryptoKeys/oauth-tokens`

**2. Security Headers (FastAPI middleware):**
```python
# Wszystkie responses dostają:
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Content-Security-Policy: default-src 'self'; script-src 'self' cdn.tailwindcss.com cdn.jsdelivr.net
Referrer-Policy: strict-origin-when-cross-origin
```
CORS: `allow_origins=[ADMIN_DOMAIN]` (tylko domena admina, nie `*`)

**3. Rate Limiting (`slowapi`):**
```python
# Per endpoint limity:
/telegram/webhook:    30/minute per IP
/auth/google/callback: 10/minute per IP  (brute-force protection)
/admin/*:             100/minute per IP
/stripe/webhook:      unlimited (Stripe IPs)
/internal/*:          unlimited (OIDC protected)
```

**4. Firestore Security Rules:**
```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Brak dostępu publicznego — tylko Server SDK (service account)
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```
Wszystkie operacje przez Server SDK (service account) — reguły blokują bezpośredni dostęp z przeglądarki.

**5. Input Validation:**
`validators.py`:
- `validate_timezone(tz: str)` → sprawdza `zoneinfo.available_timezones()`
- `validate_time_format(t: str)` → regex `^\d{2}:\d{2}$`
- `validate_text_length(text: str, max_len=4096)` → Telegram limit
- `sanitize_for_logging(text: str)` → usuwa potencjalne PII przed logowaniem

**6. Secret Manager — wszystkie sekrety:**
Upewnij się że żaden sekret nie jest w env vars ani kodzie. Checklist:
- `TELEGRAM_BOT_TOKEN` → Secret Manager
- `TELEGRAM_SECRET_TOKEN` → Secret Manager
- `STRIPE_API_KEY` → Secret Manager
- `STRIPE_WEBHOOK_SECRET` → Secret Manager
- `ADMIN_JWT_SECRET` → Secret Manager
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` → Secret Manager
- `GCP_PROJECT_ID` → env var (nie wrażliwy)

**Scenariusze testowe:**
- [Unit] `encrypt` + `decrypt` round-trip → identyczny plaintext
- [Unit] Security headers obecne we wszystkich `/admin/*` responses
- [Unit] Rate limiter zwraca 429 po przekroczeniu limitu `/auth/google/callback`
- [Unit] Firestore rules: bezpośredni request HTTP do Firestore REST API → permission denied
- [Unit] `validate_timezone("Invalid/Zone")` → rzuca `ValidationError`
- [Unit] `sanitize_for_logging("token abc123")` → nie zawiera pełnego tokenu w output

**Weryfikacja:**
- Security headers sprawdzone przez `curl -I {url}` lub securityheaders.com
- Rate limiting aktywne: 11 szybkich requestów do `/auth/google/callback` → ostatni 429
- Pentest: bezpośredni dostęp do Firestore REST API bez service account → denied
- Brak plain text sekretów w Cloud Run env vars (sprawdź w GCP Console)

---

## Wpływ systemowy

```
Telegram User
    ↓ (webhook)
Cloud Run / FastAPI
    ├── Gemini 2.5 Flash (Vertex AI)  — parsowanie tekstu i głosu
    ├── Firestore                      — dane users/tasks, dedup, conversation state
    ├── Cloud Tasks                    — scheduled reminders i nudges
    ├── Stripe                         — subskrypcje i webhooks
    ├── Google Calendar API            — events CRUD + push notifications
    └── Google Tasks API               — tasks CRUD

Cloud Tasks       → Cloud Run /internal/trigger-reminder  → Telegram + Google Calendar/Tasks
Cloud Tasks       → Cloud Run /internal/trigger-nudge     → Telegram
Stripe            → Cloud Run /stripe/webhook             → Firestore + Telegram
Google Calendar   → Cloud Run /webhooks/google-calendar   → Firestore + Cloud Tasks + Telegram
Cloud Scheduler   → Cloud Run /internal/cleanup           → Firestore + Cloud Tasks
Cloud Scheduler   → Cloud Run /internal/poll-google-tasks → Google Tasks API + Telegram
Cloud Scheduler   → Cloud Run /internal/renew-gcal-channels → Google Calendar API
```

- **Propagacja błędów:** Gemini timeout → parse failure → degraded mode (pytaj o czas). Cloud Tasks delivery failure → auto-retry (max 3 razy, exponential backoff). Stripe webhook failure → Stripe retry przez 72h.
- **Ryzyka cyklu życia stanu:** Snooze atomiczne przez Firestore transaction. `expires_at` ustawiany tylko raz przy COMPLETED/REJECTED. Cleanup job idempotent (ignore NOT_FOUND).
- **Parytet surface API:** Endpointy `/internal/*` dostępne tylko dla Cloud Tasks service account (OIDC). `/stripe/webhook` weryfikuje Stripe signature. `/telegram/webhook` weryfikuje secret token.
- **Pokrycie integracyjne:** E2E flow (wiadomość → reminder → snooze → drugi reminder) wymaga staging environment z real Cloud Tasks. Unit testy mockują scheduler.

## Ryzyki i zależności

- **Gemini 2.5 Flash GA**: per research jest GA od kwietnia 2026. Pinować model version `gemini-2.5-flash-001` dla stabilności.
- **Cloud Tasks cancellation race**: Task może odpalonić się tuż przed cancel przy snoozie → idempotency guard w `trigger-reminder` (sprawdzenie state przed wysyłką) zapobiega duplikatom.
- **Min-instances cost**: Cloud Run min-instances=1 przy 512MB ≈ ~$10-15/mies. Akceptowalne dla stabilności webhooków.
- **Stripe PLN**: Stripe obsługuje PLN. Konto Stripe wymaga weryfikacji przed live payments. Test mode wystarczy dla development i staging.
- **Firestore TTL eventual**: delete następuje z opóźnieniem do 24h od `expires_at`. Filtry UI muszą uwzględniać `expires_at < now()`.
- **Google Calendar push channel expiry**: kanały wygasają co 7 dni — bez renewal bot nie dostaje zmian z GCal. Cloud Scheduler musi być niezawodny. Fallback: przy każdym webhook request sprawdź `watch_expiry` i odnów jeśli < 2 dni.
- **Google Tasks rate limit**: 50,000 req/day per project. Przy >200 aktywnych userach z Google polling co 5 min → zbliżamy się do limitu. Mitigacja: zwiększ interval do 15 min przy >150 userach lub użyj batch API.
- **Google OAuth token storage security**: refresh_token w Firestore wymaga szyfrowania. Użyj Cloud KMS lub AES-256 z kluczem z Secret Manager. Plain text refresh_token w DB = krytyczne ryzyko bezpieczeństwa.
- **Conflict resolution simplicity**: "last write wins" może powodować nieoczekiwane zachowanie gdy user edytuje z obu stron. Akceptowalne dla MVP, wymaga doprecyzowania w v2.
- **Google Tasks brak webhooków**: 5-minutowe opóźnienie przy sync Tasks→Bot. Akceptowalne — user rozumie że to nie real-time.

## Metryki sukcesu (dla weryfikacji po implementacji)

- Capture do scheduled Cloud Task < 5s od wysłania wiadomości (Telegram)
- Voice message processed < 8s (download + Gemini + response)
- Reminder delivery accuracy: ±30s od `scheduled_time`
- Zero duplicate reminders (weryfikacja przez Firestore state guards)
- Trial → subskrypcja: target > 30% po 30 dniach

## Fazowe dostarczanie

### Faza 1 — Core Bot (Units 1-8)
Działający bot: capture → parse → remind → snooze/done. Bez płatności (wszystko na free). Internal testing + dogfooding przez zespół.

### Faza 2 — Polish (Units 9-10)
Nudge system + auto-archival. Stability testing z rzeczywistymi danymi.

### Faza 3 — Monetyzacja (Unit 11)
Stripe integration. Trial → payment flow. Blocking logic. Launch publiczny.

### Faza 4 — Google Integration (Units 12-14)
Google OAuth, Calendar sync (dwukierunkowa), Tasks sync (polling). Wymaga Google Cloud Console setup: OAuth client, Calendar API, Tasks API włączone. Opcjonalne dla userów — nie blokuje Fazy 3.

### Faza 5 — Admin Dashboard + Security (Units 15-18)
Token tracking, admin auth (Google SSO), dashboard UI, security hardening. Unit 18 (Security Hardening) może być częściowo wdrożony wcześniej (rate limiting, headers) — nie blokuje Faz 1-4.

### Faza 6 — Checklista + RODO (Units 19-21)
Szablony checklist, flow reminderów (wieczorny + poranny), item callbacks, /delete_my_data. Może być wdrożona równolegle z Fazą 4 (Google) — brak zależności między nimi.

### Faza I: Checklista + RODO

- [ ] **Unit 19: Checklist Template Management**

**Cel:** Tworzenie i edycja szablonów checklist. AI sugeruje itemy. Komendy `/new_checklist`, `/checklists`, `/evening`. Zapis szablonu po pierwszym użyciu.

**Wymagania:** R17, R19.

**Zależności:** Unit 3 (Firestore), Unit 4 (Gemini — AI sugestie), Unit 6 (komendy).

**Pliki:**
- Stwórz: `adhd-bot/bot/models/checklist.py` (ChecklistTemplate, ChecklistSession dataclasses)
- Stwórz: `adhd-bot/bot/handlers/checklist_command_handlers.py`
- Stwórz: `adhd-bot/bot/services/checklist_ai.py` (Gemini sugestie itemów)
- Stwórz: `adhd-bot/tests/test_checklist_templates.py`

**Podejście:**

**Nowe kolekcje Firestore:**
```
checklist_templates/{template_id}
  user_id: str
  name: str              # "Siłownia", "Praca", "Zakupy"
  items: list[str]       # max 12
  evening_enabled: bool  # default true
  created_at: Timestamp
  updated_at: Timestamp

checklist_sessions/{session_id}
  user_id: str
  template_id: str
  template_name: str
  items: list[{text: str, checked: bool}]  # snapshot przy tworzeniu
  event_time: Timestamp     # czas eventu
  evening_reminder_time: Timestamp
  morning_reminder_time: Timestamp
  evening_message_id: int | null
  morning_message_id: int | null
  cloud_task_name_evening: str | null
  cloud_task_name_morning: str | null
  state: str  # "pending_evening" | "evening_sent" | "morning_sent" | "completed"
  created_at: Timestamp
  expires_at: Timestamp | null
```

**`/new_checklist` komenda:**
1. Bot pyta o nazwę szablonu
2. Wywołaj `checklist_ai.suggest_items(name)` → Gemini sugeruje do 8 itemów
3. Bot wysyła: *"Proponuję taką listę dla '{name}':\n1. Buty\n2. Ręcznik...\n\n`[✓ Użyj tej] [Edytuj] [Zacznij od nowa]`"*
4. `[✓ Użyj tej]` → zapisz szablon
5. `[Edytuj]` → conversational flow: bot pyta o każdy item (dodaj/usuń)

**`/checklists` komenda:**
- Wyświetla listę szablonów usera z przyciskami `[Edytuj] [Usuń]` per szablon
- `[Edytuj]` → pokazuje itemy z `[+ Dodaj item] [✕ Usuń item]`
- `[Usuń]` → potwierdza usunięcie szablonu

**`/evening [HH:MM]` komenda:**
- Globalna godzina wieczornego remindera dla wszystkich checklist
- Domyślnie: 21:00. Zapisywana w `users/{user_id}.evening_time`
- Analogiczna do `/morning`

**`checklist_ai.suggest_items(template_name: str) -> list[str]`:**
- Gemini prompt: "Zaproponuj do 8 rzeczy do zabrania/przygotowania przed: {template_name}. JSON array stringów, po polsku."
- Max 8 sugestii (user może dodać do łącznie 12)

**Auto-zapis szablonu po pierwszym użyciu:**
- Po użyciu ad-hoc checklisty (bez szablonu) bot pyta: *"Zapisać tę listę jako '{name}' na przyszłość? `[✓ Zapisz] [Nie]`"*

**Scenariusze testowe:**
- [Unit] `/new_checklist Siłownia` → Gemini sugeruje ≤8 itemów
- [Unit] Szablon z >12 itemami → błąd walidacji
- [Unit] `/checklists` dla usera bez szablonów → "Nie masz jeszcze żadnych list"
- [Unit] `[Usuń]` szablon → usunięty z Firestore
- [Unit] `/evening 20:30` → `user.evening_time = "20:30"`
- [Unit] `/evening 25:00` → błąd walidacji

**Weryfikacja:**
- Pełny flow tworzenia szablonu → widoczny w `/checklists`
- AI sugestie: sensowne itemy dla "Siłownia", "Praca", "Lotnisko"

---

- [ ] **Unit 20: Checklist Session Flow (wieczorny + poranny reminder, item callbacks)**

**Cel:** Tworzenie sesji checklisty po wykryciu eventu. Wieczorny reminder z pełną listą. Poranny z nieodznaczonymi. Odznaczanie itemów. Auto-zamknięcie.

**Wymagania:** R18, R19.

**Zależności:** Unit 19, Unit 4 (Gemini event detection), Unit 5 (scheduler), Unit 7 (task capture).

**Pliki:**
- Stwórz: `adhd-bot/bot/services/checklist_session.py`
- Stwórz: `adhd-bot/bot/handlers/checklist_callbacks.py`
- Modyfikuj: `adhd-bot/bot/handlers/internal_triggers.py` (dodaj trigger-checklist-evening, trigger-checklist-morning)
- Modyfikuj: `adhd-bot/bot/handlers/message_handlers.py` (integracja Gemini event detection)
- Stwórz: `adhd-bot/tests/test_checklist_session.py`

**Podejście:**

**Gemini event detection (modyfikacja Unit 4):**

Nowe pole w `ParsedTask`: `event_type: "task" | "event_with_preparation" | null`
- `"event_with_preparation"` gdy Gemini wykryje: trening, wyjście, podróż, spotkanie poza domem, wydarzenie wymagające zabrania rzeczy

W `message_handlers.py` po parsowaniu:
- Jeśli `event_type == "event_with_preparation"`:
  - Sprawdź `checklist_templates` usera dla pasującej nazwy (case-insensitive match na `template.name` vs słowa kluczowe w `parsed.content`)
  - Jeśli match → wyślij: *"Masz listę '{template.name}' — dodać ją do remindera? `[✓ Dodaj listę] [Nie, tylko reminder]`"*
  - Jeśli brak match → utwórz zwykły reminder, potem zapytaj: *"Czy jest coś co musisz zabrać? `[✓ Stwórz listę] [Nie]`"*

**Tworzenie sesji:**
- `ChecklistSession.create(user_id, template_id, event_time)`:
  - Kopiuje itemy z szablonu (snapshot)
  - Oblicza `evening_reminder_time = yesterday(event_time) at user.evening_time`
  - Oblicza `morning_reminder_time = event_time.date at user.morning_time`
  - Scheduje dwa Cloud Tasks: `checklist-evening-{session_id}` i `checklist-morning-{session_id}`
  - `state = "pending_evening"`

**`/internal/trigger-checklist-evening`:**
- Pobierz sesję, jeśli `state != "pending_evening"` → 200 (idempotent)
- Wyślij wiadomość wieczorną:
  ```
  📋 Jutro {event_name}! Oto Twoja lista:

  [ ] Buty sportowe
  [ ] Ręcznik
  [ ] Bidon
  ...

  [✓ Buty sportowe] [✓ Ręcznik] [✓ Bidon]
  [+30 min] [Jutro rano]
  ```
- Zapisz `evening_message_id`, `state = "evening_sent"`

**`/internal/trigger-checklist-morning`:**
- Pobierz sesję. Filtruj: `unchecked_items = [i for i in items if not i.checked]`
- Jeśli wszystkie odznaczone → wyślij *"✅ Już wszystko spakowane! Miłego {event_name} 💪"* → state = "completed"
- Jeśli nieodznaczone → wyślij tylko nieodznaczone z buttonami + snooze
- `state = "morning_sent"`

**Item callback handler:**
- Callback data: `checklist_item:{session_id}:{item_index}`
- `answerCallbackQuery` natychmiast
- Zaznacz item jako checked w sesji (Firestore transaction)
- Edit wiadomości: zaktualizuj listę (odznaczony item = "✓ Buty sportowe" bez przycisku)
- Jeśli wszystkie checked → edit na *"✅ Wszystko gotowe! {event_name} czeka 💪"*, usuń wszystkie przyciski, `state = "completed"`

**Snooze całej listy:**
- Callback `checklist_snooze:30m:{session_id}` → reschedule trigger-checklist-morning za 30 min
- Edit wiadomości: "💤 Przypomnę za 30 min"

**Scenariusze testowe:**
- [Unit] Event z pasującym szablonem → bot proponuje szablon bezpośrednio
- [Unit] Event bez szablonu → bot pyta "czy coś zabrać?"
- [Unit] Sesja tworzona z snapshot'em itemów (edycja szablonu po tym nie wpływa)
- [Unit] trigger-checklist-morning gdy wszystkie zaznaczone → wiadomość gratulacyjna bez listy
- [Unit] trigger-checklist-morning gdy 3/5 zaznaczonych → tylko 2 nieodznaczone z buttonami
- [Unit] Kliknięcie ostatniego itemu → auto-zamknięcie z komunikatem gratulacyjnym
- [Unit] Snooze całej listy → nowy Cloud Task za 30 min

**Weryfikacja:**
- Napisz "jutro siłownia o 7" → bot proponuje listę "Siłownia" → o 21:00 wieczorna wiadomość → o 7:00 tylko nieodznaczone
- Kliknij wszystkie itemy wieczorem → rano gratulacje bez listy

---

- [ ] **Unit 21: RODO — /delete\_my\_data + Polityka Prywatności**

**Cel:** Komenda `/delete_my_data` kasująca wszystkie dane usera. Statyczna strona z polityką prywatności. Compliance z RODO dla polskich userów.

**Wymagania:** R16.

**Zależności:** Unit 3 (wszystkie kolekcje Firestore).

**Pliki:**
- Modyfikuj: `adhd-bot/bot/handlers/command_handlers.py` (dodaj `/delete_my_data`)
- Stwórz: `adhd-bot/templates/privacy_policy.html` (statyczna strona)
- Stwórz: `adhd-bot/tests/test_gdpr.py`

**Podejście:**

**`/delete_my_data` komenda:**
1. Bot wysyła ostrzeżenie: *"⚠️ To usunie WSZYSTKIE Twoje dane: zadania, checklista, historię. Subskrypcja Stripe zostanie anulowana. Nie można cofnąć.\n\n`[✓ TAK, usuń wszystko] [Anuluj]`"*
2. Po potwierdzeniu:
   - Usuń wszystkie dokumenty z Firestore: `tasks`, `token_usage`, `checklist_templates`, `checklist_sessions`, `processed_updates` dla tego user_id
   - Usuń `users/{user_id}`
   - Anuluj wszystkie Cloud Tasks (reminders, nudges, checklists) — best effort
   - Jeśli `stripe_subscription_id` istnieje → `stripe.Subscription.cancel(subscription_id)`
   - Jeśli Google połączone → `google_auth.revoke_token(refresh_token)`
   - Wyślij: *"✅ Wszystkie Twoje dane zostały usunięte. Do zobaczenia!"*

**Polityka prywatności (`GET /privacy`):**
- Statyczna strona HTML serwowana przez FastAPI
- Zawiera: co zbieramy (Telegram user_id, treść zadań, timezone), po co, jak długo (30 dni po ukończeniu), podstawa prawna (zgoda + uzasadniony interes), prawa użytkownika (dostęp, usunięcie przez /delete_my_data), kontakt administratora

**Scenariusze testowe:**
- [Unit] `/delete_my_data` bez potwierdzenia → brak usunięcia
- [Unit] `/delete_my_data` z potwierdzeniem → wszystkie kolekcje usera usunięte z Firestore
- [Unit] `/delete_my_data` anuluje subskrypcję Stripe jeśli istnieje
- [Unit] `/delete_my_data` revoke Google token jeśli połączone
- [Unit] `GET /privacy` zwraca 200 z HTML

**Weryfikacja:**
- Po `/delete_my_data` brak dokumentów usera w żadnej kolekcji Firestore
- `/privacy` dostępne publicznie bez autentykacji

---

## Źródła i referencje

- **Dokument źródłowy:** [docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md](docs/dev-brainstorms/2026-04-09-adhd-reminder-bot-requirements.md)
- Telegram Bot API: https://core.telegram.org/bots/api
- python-telegram-bot v21: https://docs.python-telegram-bot.org/
- Vertex AI Gemini 2.5 Flash: https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash
- Google Cloud Tasks: https://cloud.google.com/tasks/docs
- Firestore TTL: https://firebase.google.com/docs/firestore/ttl
- Stripe Subscriptions API: https://docs.stripe.com/billing/subscriptions/overview
- Cloud Run min-instances: https://cloud.google.com/run/docs/configuring/min-instances
