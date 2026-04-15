---
title: "Review Fazy 4 — Google Integration (Units 12-14) — Re-run cykl 2"
phase: 4
date: 2026-04-09
result: "✅ GOTOWE DO KONTYNUACJI"
p1: 0
p2: 0
p3: 6
---

# Review Fazy 4 — Google Integration (Units 12-14) — Re-run cykl 2

**Wynik:** ✅ GOTOWE DO KONTYNUACJI — P1=0, P2=0, P3=6
**Testy:** 198/198 przechodzą (brak regresji po naprawach)
**Pliki sprawdzone:** 5 (requirements.txt, google_auth.py, gtasks_polling_handler.py, google_calendar.py, google_tasks.py)

---

## Weryfikacja napraw z cyklu 1

### P1-1: `cryptography==44.0.0` dodany do requirements.txt -- NAPRAWIONE
**Plik:** `requirements.txt:22`
**Weryfikacja:** `cryptography==44.0.0` obecne w requirements.txt. AES-256 GCM encryption bedzie dzialac w produkcji (Cloud Run `pip install -r requirements.txt` zainstaluje pakiet). Fallback do plain base64 nie bedzie aktywowany.

### P2-1: `SCHEDULED` usuniety z `completable_states` -- NAPRAWIONE
**Plik:** `bot/handlers/gtasks_polling_handler.py:192`
**Weryfikacja:** `completable_states = {TaskState.REMINDED, TaskState.NUDGED, TaskState.SNOOZED}` -- `TaskState.SCHEDULED` nie jest obecny. Task w stanie SCHEDULED nie bedzie probowal przejsc do COMPLETED (co state machine zabrania). Poprawne zachowanie: task SCHEDULED czeka na Cloud Task trigger ktory go przesunie do REMINDED.

### P2-2: `_refresh_access_token` restrukturyzowany -- NAPRAWIONE
**Plik:** `bot/services/google_auth.py:256-311`
**Weryfikacja:** Funkcja podzielona na 2 fazy:
- **Phase 1 (linie 266-285):** HTTP request do Google w try/except -- lapi tylko bledy sieciowe z httpx. Na failure: disconnect + notification. Poprawne.
- **Phase 2 (linie 295-311):** Parse response, encrypt, persist -- BEZ try/except. Bledy szyfrowania/zapisu propaguja sie do callera zamiast byc maskowane jako network failure. Poprawne.
Kluczowa zmiana: user NIE zostanie blednie oznaczony jako disconnected gdy refresh HTTP sie udal ale szyfrowanie/zapis sfailowal.

### P2-3: `verify_oauth_state` waliduje typ `telegram_user_id` -- NAPRAWIONE
**Plik:** `bot/services/google_auth.py:138-139`
**Weryfikacja:** `user_id = data.get("telegram_user_id"); return user_id if isinstance(user_id, int) else None`. Jesli pole jest None, string, float lub inny typ niz int -- zwraca None. Downstream code w callback handler nie otrzyma blednego user_id.

### P2-4: `asyncio.to_thread()` dla synchronicznych Google API calls -- NAPRAWIONE
**Plik:** `bot/services/google_calendar.py` + `bot/services/google_tasks.py`
**Weryfikacja:**
- `google_calendar.py`: Wszystkie 4 wywolania `.execute()` owinięte w `await asyncio.to_thread(...)` (linie 84, 134, 179, 213)
- `google_tasks.py`: Wszystkie 4 wywolania `.execute()` owinięte w `await asyncio.to_thread(...)` (linie 68, 110, 141, 186)
- Import `asyncio` dodany w obu plikach
- Event loop FastAPI nie bedzie blokowany przez synchroniczne HTTP calls do Google API

---

## Nowe problemy -- brak

Naprawki nie wprowadzily nowych problemow. Testy 198/198 przechodzą bez regresji.

---

## Remaining P3 (Nit) -- carry-over, nie blokują

### P3-1: `_verify_oidc_token` zduplikowany w 3 plikach
**Pliki:** `gtasks_polling_handler.py:34`, `cleanup_handler.py:32`, `internal_triggers.py:23`
**Status:** Do konsolidacji w Unit 18 (Security Hardening)

### P3-2: `_TELEGRAM_BASE_URL` zduplikowany w 8 plikach
**Status:** Do konsolidacji przed Faza 5

### P3-3: `httplib2` import unused w google_calendar.py
**Plik:** `bot/services/google_calendar.py:33`

### P3-4: `_html_response` bez HTML escaping
**Plik:** `bot/handlers/google_oauth_handler.py:228-244`
**Status:** Aktualnie bezpieczne (hardcoded strings), fragile

### P3-5: `_get_encryption_key` brak logger.error w produkcji
**Plik:** `bot/services/google_auth.py:50-54`

### P3-6: Brak testu dla `delete_google_task`
**Plik:** `tests/test_google_tasks.py`

---

## Podsumowanie

Wszystkie 5 napraw z cyklu 1 zostaly poprawnie zaimplementowane i zweryfikowane:
- 1x P1 (blocking) -- naprawiony, zweryfikowany
- 4x P2 (important) -- wszystkie naprawione, zweryfikowane
- 198/198 testow przechodzi
- Brak nowych problemow

Faza 4 jest gotowa do kontynuacji do Fazy 5.
