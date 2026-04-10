---
title: "Review Fazy 4 — Google Integration (Units 12-14)"
phase: 4
date: 2026-04-09
result: "⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI"
p1: 1
p2: 4
p3: 6
---

# Review Fazy 4 — Google Integration (Units 12-14)

**Wynik:** ⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI — P1=1, P2=4, P3=6
**Testy:** 198/198 przechodzą (46 nowych w Fazie 4)
**Pliki sprawdzone:** 8 (google_auth.py, google_oauth_handler.py, google_calendar.py, google_tasks.py, gtasks_polling_handler.py, test_google_auth.py, test_google_calendar.py, test_google_tasks.py)

---

## Findings — P1 (Blocking)

### P1-1: `cryptography` brak w requirements.txt — szyfrowanie AES-256 nie zadziała w produkcji
**Plik:** `bot/services/google_auth.py:62-63` + `requirements.txt`
**Opis:** `_encrypt_token` i `_decrypt_token` importują `from cryptography.hazmat.primitives.ciphers.aead import AESGCM`, ale pakiet `cryptography` **nie jest wymieniony w `requirements.txt`**. W produkcji (Cloud Run) `pip install -r requirements.txt` nie zainstaluje tego pakietu. Skutek: fallback do base64 encoding (linia 78-79: `logger.warning("cryptography package not available; storing token unencrypted")`). Tokeny Google (access_token i refresh_token) będą przechowywane w Firestore jako plain base64 — ktokolwiek z dostępem do Firestore zobaczy tokeny w plaintext.
**Rekomendacja:** Dodaj `cryptography==44.0.0` (lub aktualną stabilną) do `requirements.txt`. Jest to wymaganie bezpieczeństwa z planu (linia 831: "szyfruj tokeny przez AES-256").

---

## Findings — P2 (Important)

### P2-1: `_sync_completed_task` zawiera `SCHEDULED` w completable_states — InvalidStateTransitionError w runtime
**Plik:** `bot/handlers/gtasks_polling_handler.py:192`
**Opis:** `completable_states = {TaskState.SCHEDULED, TaskState.REMINDED, TaskState.NUDGED, TaskState.SNOOZED}`. Ale state machine (`bot/models/task.py:24`) definiuje `ALLOWED_TRANSITIONS[SCHEDULED] = {REMINDED}` — przejście `SCHEDULED -> COMPLETED` jest **zabronione**. Gdy Google Task jest ukończony a odpowiadający bot task jest w stanie `SCHEDULED`, wywołanie `task.transition(TaskState.COMPLETED)` na linii 200 rzuci `InvalidStateTransitionError`. Wyjątek jest łapany przez `except Exception` na linii 155 i swallowany — task nie zostanie ukończony, user nie dostanie notyfikacji. Silently-failing code path.
**Rekomendacja:** Usuń `TaskState.SCHEDULED` z `completable_states` (task w SCHEDULED nie powinien być kompletowany z Google Tasks — jeszcze nie został reminded), lub dodaj `COMPLETED` do `ALLOWED_TRANSITIONS[SCHEDULED]` z uzasadnieniem (zmiana state machine wymaga analizy downstream effects).

### P2-2: `except Exception` w `_refresh_access_token` (linia 300) — zbyt szeroki catch
**Plik:** `bot/services/google_auth.py:300`
**Opis:** `_refresh_access_token` łapie `except Exception as exc:` obok bloku httpx. Ten catch obejmuje **wszystkie** błędy — w tym `TypeError`, `AttributeError` z logiki szyfrowania/zapisu, nie tylko błędy sieciowe. Przy buchu w `_encrypt_token` (np. złamany klucz) user zostanie oznaczony jako disconnected (linia 306: `_mark_google_disconnected`) choć sam refresh mógł się udać — token Google został pobrany ale nie zapisany, a user stracił połączenie. Spójny z P2 z Fazy 2 (naprawiony tam — zawężenie do konkretnych typów).
**Rekomendacja:** Zawęź do `except (httpx.HTTPError, httpx.TimeoutException, ValueError):`. Pozwoli to wyłapać błędy sieciowe i parsowania odpowiedzi, ale nie zamaskuje bugów w logice szyfrowania/zapisu.

### P2-3: OAuth state token — brak walidacji `telegram_user_id` przy verify
**Plik:** `bot/services/google_auth.py:115-137`
**Opis:** `verify_oauth_state` zwraca `data.get("telegram_user_id")` bez walidacji typu. Jeśli dokument w Firestore ma `telegram_user_id` jako None lub jako string (race condition, manual edit, corruption), downstream code w callback (linia 128-136 w `google_oauth_handler.py`) traktuje wynik jako int i wysyła tokeny do błędnego usera. `verify_oauth_state` powinien zwrócić `None` gdy `telegram_user_id` nie jest intem.
**Rekomendacja:** Dodaj walidację: `user_id = data.get("telegram_user_id"); return user_id if isinstance(user_id, int) else None`.

### P2-4: Synchronous Google API calls w async functions — thread blocking
**Plik:** `bot/services/google_calendar.py:83`, `bot/services/google_tasks.py:67-70`
**Opis:** `_build_google_service` zwraca sync `googleapiclient.discovery.build` service. Wywołania `service.events().insert(...).execute()` i `service.tasks().insert(...).execute()` to **synchroniczne HTTP calls** (blokujące event loop). W kontekście `async def create_calendar_event(...)` te wywołania zablokują cały async event loop FastAPI na czas trwania HTTP request do Google API (typowo 200-500ms per call). Przy wielu użytkownikach degradacja performance.
**Rekomendacja:** Użyj `asyncio.to_thread()` do owinięcia synchronicznych wywołań Google API, lub użyj `aiohttp`/`httpx` bezpośrednio z Google API endpoints (bez `googleapiclient`). Minimum: `await asyncio.to_thread(service.events().insert(...).execute)`.

---

## Findings — P3 (Nit)

### P3-1: `_verify_oidc_token` zduplikowany teraz w 3 plikach
**Plik:** `gtasks_polling_handler.py:34`, `cleanup_handler.py:32`, `internal_triggers.py:23`
**Opis:** Identyczna funkcja `_verify_oidc_token` skopiowana do trzeciego pliku. Carry-over z Fazy 2 P3 — teraz 3 kopie. Unit 18 Security Hardening jest naturalnym miejscem do wyciągnięcia do wspólnego modułu.

### P3-2: `_TELEGRAM_BASE_URL` zduplikowany w 8 plikach
**Plik:** `google_oauth_handler.py:37`, `gtasks_polling_handler.py:29`, + 6 wcześniejszych plików
**Opis:** Carry-over z Faz 1-3 P3, teraz w 8 plikach (2 nowe w Fazie 4). `google_auth.py:340` konstruuje URL bezpośrednio z inlinowaną bazą. Faza 5 powinna to skonsolidować.

### P3-3: `httplib2` import unused w google_calendar.py
**Plik:** `bot/services/google_calendar.py:32`
**Opis:** `import httplib2` w `_build_google_service` ale httplib2 nie jest bezpośrednio używany. `google-api-python-client` wymaga go jako dependency ale explicit import jest zbędny.
**Rekomendacja:** Usuń `import httplib2`.

### P3-4: `_html_response` bez HTML escaping — fragile
**Plik:** `bot/handlers/google_oauth_handler.py:228-244`
**Opis:** `_html_response(title, message)` interpoluje parametry bezpośrednio do HTML f-stringa bez `html.escape()`. Aktualnie bezpieczne (wszystkie wywołania używają hardcoded strings, nie user input), ale fragile — przyszła zmiana mogłaby wprowadzić XSS. Google OAuth error parameter jest logowany, nie renderowany — OK.
**Rekomendacja:** Dodaj `from html import escape` i użyj `escape(title)`, `escape(message)` w szablonie.

### P3-5: `_get_encryption_key` zwraca zeroed key w dev — brak ochrony przed przypadkowym deploy
**Plik:** `bot/services/google_auth.py:50-54`
**Opis:** Gdy `GOOGLE_ENCRYPTION_KEY` nie jest ustawiony, zwraca `b"\x00" * 32`. To jest akceptowalne dla testów, ale nie ma żadnej ochrony (assert, log.error) która ostrzeże gdy produkcja uruchomi się bez klucza. Powiązane z P1-1 (cryptography brak w deps) — gdy klucz jest, ale biblioteka nie, i tak fallback do base64.
**Rekomendacja:** Dodaj `if not os.environ.get("TESTING"): logger.error("GOOGLE_ENCRYPTION_KEY not set — tokens will NOT be encrypted")` w fallback branch.

### P3-6: Brak test for `delete_google_task`
**Plik:** `tests/test_google_tasks.py`
**Opis:** Plan techniczny definiuje test dla `delete_google_task` (linia 960: `[Unit] delete_google_task wywołuje tasks.delete`). W pliku testowym brak takiego testu. `create_google_task` i `complete_google_task` mają testy; `delete_google_task` nie. Pokrycie niekompletne.
**Rekomendacja:** Dodaj test `test_calls_tasks_delete` wzorowany na `test_calls_events_delete` z `test_google_calendar.py`.

---

## Odchylenia od planu technicznego

### Udokumentowane (OK)

- **AES-256 zamiast Cloud KMS**: Plan (linia 831) mówi "szyfruj tokeny przez AES-256 (klucz z Secret Manager)". Implementacja używa AES-256 GCM z kluczem z env var `GOOGLE_ENCRYPTION_KEY`. Secret Manager integracja przewidziana na Unit 18. Decyzja udokumentowana w kontekście — OK.
- **`nextSyncToken` dla delta queries**: Implementacja zgodna z planem (linia 946) — używa `nextSyncToken` zamiast `updatedMin` po pierwszym pollu.

### Nieudokumentowane odchylenia (wymagają uwagi)

- **Plan definiuje pobranie calendar_id i tasks_list_id w callback** (linia 832-833). Implementacja to realizuje (`_fetch_google_resource_ids` w `google_oauth_handler.py:192-225`) — zgodne.
- **Plan nie wspomina o `SNOOZED` w polling completable_states** (linia 948: "REMINDED/NUDGED/SCHEDULED"). Implementacja dodaje `SNOOZED` — sensowne rozszerzenie (task po snooze wraca do REMINDED, ale mogą być w SNOOZED w momencie pollu). OK.
- **Plan mówi `SCHEDULED` w completable_states** ale state machine zabrania `SCHEDULED -> COMPLETED`. To P2-1 — niespójność planu ze state machine wymaga decyzji.
- **Brak integracji Calendar/Tasks w message_handlers/callback_handlers**: Zadania unchecked w pliku zadań (linie 326-328). Spodziewane — to osobne integration items, nie tworzone w tej fazie.

---

## Security Review

### OAuth Flow
- **CSRF protection:** State token (nanoid 32 chars) → Firestore TTL 10 min → single-use (delete after verify) — poprawne
- **State TTL:** 10 minut — wystarczające, zgodne z planem
- **State consumption:** Single-use (usuwany po weryfikacji na linii 136) — poprawne, brak replay attack
- **access_type=offline + prompt=consent:** Zapewnia refresh_token — poprawne

### Token Management
- **Encryption:** AES-256 GCM z losowym 12-byte nonce — kryptograficznie poprawne (gdy cryptography jest zainstalowane — P1-1)
- **Refresh buffer:** 5 min przed wygaśnięciem — sensowne
- **Refresh failure handling:** Disconnect + Telegram notification — poprawne
- **Token storage:** Encrypted access + refresh w user doc — jedno miejsce, brak leaku

### Rate Limiting
- **Google Tasks polling:** `_MAX_USERS_PER_INVOCATION = 100` — ogranicza batch size per invocation. Przy >100 userach nie są przetwarzani wszyscy. Plan sugeruje zwiększenie interval do 15 min przy >200 userach — implementacja tego nie robi automatycznie. Akceptowalne dla MVP.
- **Google API quota:** Polling co 5 min × 100 userów = 28,800 requests/day. Poniżej limitu 50,000. OK.

### OIDC Auth na /internal/poll-google-tasks
- OIDC verification obecna (`_verify_oidc_token` na linii 87) — poprawne
- TESTING=1 bypass — spójne z innymi /internal/* endpointami
- Zawężenie `except` do `(GoogleAuthError, TransportError, ValueError)` — poprawne (lekcja z Fazy 2)

---

## Performance Review

### Synchronous Google API calls (P2-4)
- `googleapiclient.discovery.build` + `.execute()` blokuje event loop
- W polling: kolejne iteracje userów są sekwencyjne (`for user_doc in user_docs:`)
- Worst case: 100 userów × 2 API calls (poll + update sync token) × 300ms = 60s

### Firestore reads per Google API call
- `create_calendar_event`: 2 Firestore reads (get_valid_token + user_doc) + 1 write
- Każda funkcja Calendar/Tasks robi osobny `user_doc.get()` nawet gdy jest kolejne wywołanie — brak cachowania user_data w ramach jednego request cycle
- Akceptowalne dla MVP, do optymalizacji w scale

### N+1 w polling
- Polling: dla każdego usera osobne `poll_user_tasks` → osobne `_build_tasks_service` → osobne HTTP connection
- Brak connection reuse między userami
- Akceptowalne do 100 userów

---

## Coverage Analysis

### Pokryte scenariusze (z planu)

**Unit 12 — Google OAuth:**
- [x] `/connect-google` generuje OAuth URL z wymaganymi scope'ami — POKRYTE
- [x] Callback ze złym state → 400 — POKRYTE
- [x] Callback z wygasłym state (TTL) → 400 — POKRYTE
- [x] `get_valid_token` wywołuje refresh gdy token wygasł — POKRYTE
- [x] `get_valid_token` nie wywołuje refresh gdy token ważny — POKRYTE
- [x] Refresh fail → user disconnected + Telegram notification — POKRYTE

**Unit 13 — Google Calendar:**
- [x] `create_calendar_event` z poprawnym scheduled_time — POKRYTE
- [x] `create_calendar_event` skip gdy brak Google — POKRYTE
- [x] `update_calendar_event_time` patch z nowym czasem — POKRYTE
- [x] `complete_calendar_event` patch z zielonym kolorem — POKRYTE
- [x] `delete_calendar_event` events.delete — POKRYTE

**Unit 14 — Google Tasks:**
- [x] `create_google_task` z poprawnym title i due — POKRYTE
- [x] `create_google_task` skip gdy brak Google — POKRYTE
- [x] `complete_google_task` tasks.patch completed — POKRYTE
- [x] Polling: completed → bot task COMPLETED + Telegram — POKRYTE
- [x] Polling: unchanged → no action — POKRYTE
- [x] Polling 0 userów → 200 — POKRYTE

### Brakujące testy (zdefiniowane w planie lub luki)
- [ ] `delete_google_task` — brak testu (P3-6)
- [ ] Polling: `syncToken` invalid → Google zwraca 410 → pełny re-sync — brak testu
- [ ] `_refresh_access_token` z 401 od Google (nie network error) — brak testu (pokryte tylko Exception path)
- [ ] `/internal/poll-google-tasks` bez OIDC → 401 — brak testu (choć endpoint ma guard)

---

## Ocena ogólna

Implementacja jest architektonicznie poprawna i kompletna funkcjonalnie. OAuth flow z state CSRF protection, AES-256 encryption, auto-refresh tokenów — wszystko zaimplementowane zgodnie z planem. Polling z `nextSyncToken` oszczędza quota.

**Krytyczny problem:** `cryptography` package brak w `requirements.txt` (P1-1) — w produkcji tokeny NIE będą szyfrowane, co jest sprzeczne z wymaganiami bezpieczeństwa. To blokuje deploy.

**Dobre wzorce potwierdzone:**
- Graceful no-op pattern: każda funkcja Calendar/Tasks zwraca None/early-return gdy brak Google — opcjonalna integracja bez error propagation
- State token single-use: delete po verify — poprawne
- `nextSyncToken` delta queries — oszczędność API quota
- Separation of concerns: google_auth → tokens, google_calendar → events, google_tasks → tasks
- OIDC na /internal/* — spójne z Fazami 1-3
