---
title: "Review Fazy 5 — Admin Dashboard + Security (Units 15-18)"
created: 2026-04-09
updated: 2026-04-09
reviewer: code-review-pipeline
phase: 5
cycle: 2
---

# Review Fazy 5 — Re-run cykl 2 (weryfikacja naprawy P2)

**Data:** 2026-04-09
**Testy:** 249/249 przechodzą (4 nowe testy w cyklu naprawczym)
**Pliki sprawdzone:** 8 (pliki dotknięte poprawkami P2 + powiązane testy)

## Severity Gate

**CZYSTE** — P1=0, P2=0, P3=7

---

## Weryfikacja naprawy P2 z cyklu 1

### P2-1: CSRF protection — NAPRAWIONE

**Plik:** `bot/admin/middleware.py:72-89`
**Weryfikacja:** `require_admin_write` teraz zawiera walidację `X-Requested-With: XMLHttpRequest` header (linie 84-87). Request bez tego headera dostaje 403 "Missing CSRF header". Dashboard fetch calls w `templates/admin/user_detail.html:107` wysylaja ten header. Testy `test_admin_auth.py:244` i `test_admin_queries.py:192` weryfikuja odrzucenie bez headera.

**Ocena:** Poprawne. Custom header check jest skuteczna ochrona CSRF dla AJAX requests - browser nie doda tego headera automatycznie w cross-origin request.

### P2-2: Admin OAuth state token — NAPRAWIONE

**Plik:** `bot/admin/auth.py:114-155, 160-179, 182-202`
**Weryfikacja:**
- `_generate_admin_state()` generuje 32-znakowy URL-safe random token (linia 117)
- `_save_admin_oauth_state()` zapisuje do `admin_oauth_states/{state}` z TTL 10 min (linie 120-128)
- `admin_login()` generuje state i przekazuje w URL (linie 166-178)
- `admin_auth_callback()` weryfikuje state przez `_verify_admin_oauth_state()` przed kontynuacja (linie 195-202)
- `_verify_admin_oauth_state()` sprawdza istnienie, TTL, i konsumuje token (single-use delete, linie 131-155)

**Ocena:** Poprawne. Wzorzec spójny z user OAuth w `google_auth.py`. State jest single-use (delete po weryfikacji) i ma TTL.

### P2-3: Rate limiter aktywny na endpointach — NAPRAWIONE

**Plik:** Dekoratory `@limiter.limit()` zastosowane na:
- `bot/webhook.py:51` — `@limiter.limit("30/minute")` na `/telegram/webhook`
- `bot/handlers/google_oauth_handler.py:107` — `@limiter.limit("10/minute")` na `/auth/google/callback`
- `bot/admin/router.py:50,63,76,97,109,127,142` — `@limiter.limit("100/minute")` na wszystkich `/admin/*` endpoints
- `bot/admin/auth.py:159,183,281` — `@limiter.limit("100/minute")` na login/callback/logout

**Weryfikacja:** Komentarze w `rate_limiter.py:47-49` nadal istnieja jako dokumentacja, ale dekoratory sa aktywnie zastosowane na handlerach. Limity zgodne z planem: webhook 30/min, OAuth 10/min, admin 100/min.

**Ocena:** Poprawne. Wszystkie publiczne endpointy maja rate limiting.

### P2-4: google_auth.py deleguje do security/encryption.py — NAPRAWIONE

**Plik:** `bot/services/google_auth.py:20, 44-51`
**Weryfikacja:**
- Import: `from bot.security.encryption import decrypt, encrypt` (linia 20)
- `_encrypt_token` deleguje do `encrypt()` (linie 44-46)
- `_decrypt_token` deleguje do `decrypt()` (linie 49-51)
- Brak zduplikowanej logiki AES-256-GCM — wszystko przechodzi przez jeden modul
- Zachowane wrapper functions `_encrypt_token`/`_decrypt_token` jako thin delegates — akceptowalne, zero duplikacji logiki krypto

**Ocena:** Poprawne. Pojedynczy modul kryptograficzny (`security/encryption.py`) jest teraz jedynym zrodlem implementacji AES-256-GCM.

### P2-5: Cursor-based pagination + batched reads — NAPRAWIONE

**Plik:** `bot/admin/queries.py:20-65, 128-199`
**Weryfikacja:**
- `_count_users_by_status()` uzywa batched reads z `_STATS_BATCH_SIZE = 500` i cursor (`start_after`) (linie 20-65)
- `get_users_list()` uzywa server-side `.where()` dla status filter (linia 146), `.limit()` dla pagination (linia 187), i cursor-based skip (linie 181-185)
- `get_user_detail()` uzywa `.limit(20)` dla recent tasks (linia 233)
- Brak nieograniczonego `await users_ref.get()` — kazdy query ma limit

**Ocena:** Poprawne. Queries nie laduja wszystkich userow do pamieci. Uwaga: count query na linia 176 uzywa `.limit(10000)` co jest akceptowalne dla count ale nie idealne — Firestore count aggregation bylby lepszy. To jest P3, nie P2.

---

## Pozostale P3 (z cyklu 1, nadal otwarte)

### P3-1: `except Exception` zbyt szeroki w admin queries
**Plik:** `bot/admin/queries.py:109,244,270`
**Status:** Nienaprawione — nadal `except Exception as exc`

### P3-2: `except Exception` zbyt szeroki w admin auth
**Plik:** `bot/admin/auth.py:211,228,309`
**Status:** Nienaprawione — nadal `except Exception as exc`

### P3-3: `_verify_oidc_token` zduplikowana w 3 plikach (carryover)
**Pliki:** `internal_triggers.py:23`, `cleanup_handler.py:32`, `gtasks_polling_handler.py:34`
**Status:** Nienaprawione — nadal 3 kopie

### P3-4: `TELEGRAM_BASE_URL` zduplikowany (carryover, eskalacja do 8 plikow)
**Status:** Nienaprawione — nadal w 8 plikach

### P3-5: `days` parameter nie walidowany
**Plik:** `bot/admin/router.py:170`
**Status:** Nienaprawione — `days = body.get("days", 7)` bez walidacji typu/zakresu

### P3-6: `int(user_id)` bez explicit error handling
**Plik:** `bot/admin/queries.py:230`
**Status:** Nienaprawione — `ValueError` lapany przez generic `except Exception`

### P3-7: Brak testu negative case dla audit middleware (GET)
**Plik:** `tests/test_admin_auth.py`
**Status:** Nienaprawione — brak testu

---

## Nowe obserwacje (informacyjne, nie blokujace)

### P3-8: Count query z `.limit(10000)` w `get_users_list`
**Plik:** `bot/admin/queries.py:176`
**Typ:** Performance

`count_docs = await count_query.order_by("__name__").limit(10000).get()` laduje do 10000 dokumentow tylko po to by policzyc `len()`. Przy skali Firestore count aggregation (`.count()`) bylby bardziej efektywny. Akceptowalne dla MVP (<10k userow).

### P3-9: Token usage per-day iteration w `get_overview_stats`
**Plik:** `bot/admin/queries.py:93-108`
**Typ:** Performance

Iteracja po dniach miesiaca z osobnym query per dzien (do 31 queries). Kazdy query ma `.limit(500)`. Akceptowalne dla MVP ale pre-aggregowany monthly summary doc bylby lepszy przy skali.

---

## Podsumowanie

Wszystkie 5 P2 z cyklu 1 zostaly poprawnie naprawione:

| P2 | Problem | Status |
|---|---|---|
| P2-1 | CSRF protection (X-Requested-With) | NAPRAWIONE |
| P2-2 | Admin OAuth state token (CSRF) | NAPRAWIONE |
| P2-3 | Rate limiter aktywny na endpointach | NAPRAWIONE |
| P2-4 | google_auth.py deleguje do security/encryption.py | NAPRAWIONE |
| P2-5 | Cursor-based pagination + batched reads | NAPRAWIONE |

249 testow przechodzi. Brak regresji. Brak nowych P1/P2. Faza 5 jest gotowa do kontynuacji z 9 P3 (7 z cyklu 1 + 2 nowe obserwacje), wszystkie nieblokujace.
