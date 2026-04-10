---
title: "Review Fazy 5 — Admin Dashboard + Security (Units 15-18)"
created: 2026-04-09
reviewer: code-review-pipeline
phase: 5
---

# Review Fazy 5 — Admin Dashboard + Security (Units 15-18)

**Data:** 2026-04-09
**Testy:** 245/245 przechodzą (47 nowych w fazie 5)
**Pliki sprawdzone:** 18 (11 produkcyjnych + 4 testowe + 3 szablony HTML)

## Severity Gate

**KONTYNUUJ Z ZASTRZEŻENIAMI** — P1=0, P2=5, P3=7

---

## Findings

### P2 — Important (wymagają naprawy)

#### P2-1: Brak CSRF protection na admin PATCH endpoint
**Plik:** `bot/admin/router.py:131-180`
**Typ:** KOD (Security)

Admin `PATCH /admin/api/users/{user_id}/subscription` akceptuje JSON body przez `request.json()` bez żadnej CSRF protection. Cookie `admin_session` ma `SameSite=lax` co chroni przed cross-site POST z formularzy, ale NIE chroni przed PATCH z JavaScript (browser wysyła cookie). Dashboard używa `fetch()` z Alpine.js — atak CSRF mógłby wykorzystać dowolną stronę do wysłania PATCH.

**Naprawa:** Dodaj walidację `Origin` lub `Referer` header w `require_admin_write`, lub dodaj custom header check (np. `X-Requested-With: XMLHttpRequest`) w fetch calls i middleware.

#### P2-2: Brak OAuth state parameter w admin login flow (CSRF na OAuth)
**Plik:** `bot/admin/auth.py:110-125`
**Typ:** KOD (Security)

`admin_login()` nie generuje ani nie weryfikuje `state` parametru w OAuth flow. Plan techniczny (Unit 16) nie wymaga tego explicite, ale user OAuth (Unit 12) używa state token z TTL — brak state w admin OAuth umożliwia atak login CSRF: atakujący może podmienić konto logowania admina na swoje.

**Naprawa:** Dodaj `state` parameter: wygeneruj nonce, zapisz w Firestore/cookie z TTL, zweryfikuj w `admin_auth_callback`. Wzorzec dostępny w `bot/services/google_auth.py` (user OAuth).

#### P2-3: Rate limiter skonfigurowany ale NIE zastosowany na endpointach
**Plik:** `bot/security/rate_limiter.py:46-49`
**Typ:** KOD (Security)

Rate limiter jest prawidłowo zainicjalizowany w `main.py` (`app.state.limiter`) i handler 429 jest podpięty. Jednak dekoratory `@limiter.limit()` NIE są zastosowane na żadnym endpoincie — linie 47-49 to komentarze z instrukcją "Decorators for use on route handlers". Plan definiuje: webhook 30/min, OAuth 10/min, admin 100/min — żadne z tych nie jest aktywne.

**Naprawa:** Zastosuj `@limiter.limit()` dekoratory na odpowiednich route handlerach: webhook, OAuth callback, admin endpoints. Wymaga importu `limiter` w plikach z handlerami.

#### P2-4: `google_auth.py` nie zmigrowane na `security/encryption.py` — duplikacja kryptografii
**Plik:** `bot/services/google_auth.py` vs `bot/security/encryption.py`
**Typ:** KOD (Architecture)

Plan Unit 18 explicite wymaga: "Modyfikacja: `adhd-bot/bot/services/google_auth.py` — użyj encryption.py". Task file też ma to jako unchecked `[ ]`. Aktualnie `google_auth.py` nadal używa własnych `_encrypt_token` / `_decrypt_token` (linie 57-95) z identyczną logiką AES-256-GCM co `security/encryption.py`. Duplikacja kryptograficznego kodu zwiększa surface area na błędy. Jeśli jeden moduł otrzyma poprawkę, drugi nie.

**Naprawa:** Zamień `_encrypt_token` / `_decrypt_token` w `google_auth.py` na wywołania `encrypt()` / `decrypt()` z `bot.security.encryption`.

#### P2-5: `get_overview_stats` ładuje WSZYSTKICH userów do pamięci — brak paginacji
**Plik:** `bot/admin/queries.py:27-29` i `bot/admin/queries.py:104-106`
**Typ:** KOD (Performance)

Zarówno `get_overview_stats` jak i `get_users_list` wykonują `await users_ref.get()` bez limitowania — ładują wszystkie dokumenty z kolekcji `users` do pamięci. Przy 10k+ userów (realna skala po kilku miesiącach) to > 100MB RAM i timeout. Dodatkowo `get_overview_stats` iteruje po dniach miesiąca z osobnym Firestore query per dzień (do 31 queries).

**Naprawa:** Dla overview: użyj Firestore count aggregation lub utrzymuj counter doc. Dla users list: zastosuj server-side query z `.where()` i `.limit()` zamiast klient-side filtrowania. Dla token costs: rozważ pre-aggregowany monthly summary doc.

---

### P3 — Nit (sugestie)

#### P3-1: `except Exception` zbyt szeroki w admin queries
**Plik:** `bot/admin/queries.py:74,172,198`
**Typ:** KOD

Trzy `except Exception as exc` w queries.py łapią wszystko — zawęź do `google.cloud.exceptions.GoogleCloudError` i `ValueError`.

#### P3-2: `except Exception` zbyt szeroki w admin auth
**Plik:** `bot/admin/auth.py:146,163,244`
**Typ:** KOD

`_exchange_code_for_token` i `_get_google_userinfo` errors łapane przez `except Exception` — zawęź do `httpx.HTTPError`, `httpx.TimeoutException`, `ValueError`.

#### P3-3: `_verify_oidc_token` nadal zduplikowana w 3 plikach (carryover)
**Pliki:** `bot/handlers/internal_triggers.py`, `bot/handlers/cleanup_handler.py`, `bot/handlers/gtasks_polling_handler.py`
**Typ:** KOD (Architecture)

Plan Unit 18 definiuje security hardening pass — ta duplikacja powinna być wyciągnięta do `bot/security/` (np. `oidc.py`). Carryover z Faz 1-4, nadal nienaprawiony.

#### P3-4: `TELEGRAM_BASE_URL` zduplikowany w 8 plikach (carryover)
**Pliki:** 8 handler/service files
**Typ:** KOD

Carryover z Fazy 1, eskalacja z 3 do 8 plików. Wyciągnij do `bot/config.py` jako stała.

#### P3-5: `days` parameter w `extend_trial_days` nie walidowany
**Plik:** `bot/admin/router.py:159`
**Typ:** KOD (Validation)

`days = body.get("days", 7)` nie waliduje typu ani zakresu — string, float, lub negatywna wartość zostanie przekazana do `timedelta(days=...)` co może dać nieoczekiwane rezultaty. Dodaj `isinstance(days, int) and 1 <= days <= 365`.

#### P3-6: `int(user_id)` w `queries.py:158` może rzucić `ValueError`
**Plik:** `bot/admin/queries.py:158`
**Typ:** KOD

`.where("telegram_user_id", "==", int(user_id))` — `user_id` pochodzi z URL path parameter (string). Jeśli admin poda nie-numeryczny ID, `int()` rzuci `ValueError` który jest łapany przez generyczny `except Exception` i logowany jako warning zamiast zwrócić 400.

#### P3-7: Brak testu dla admin audit middleware na `/admin/*` GET (negative case)
**Plik:** `tests/test_admin_auth.py`
**Typ:** TEST

Brak testu weryfikującego że GET request na `/admin/*` NIE tworzy audit log entry (middleware powinno ignorować GET). Dobra praktyka dla boundary case.

---

## Odchylenia od planu

| Element planu | Status | Komentarz |
|---|---|---|
| `google_auth.py` migracja na `encryption.py` | Nie zrobione (P2-4) | Task unchecked `[ ]`, duplikacja krypto kodu |
| Rate limit dekoratory na endpointach | Nie zrobione (P2-3) | Limiter zarejestrowany ale dekoratory zakomentowane |
| Admin OAuth state parameter | Brak | Plan nie wymaga explicite, ale user OAuth ma to — niespójność (P2-2) |
| Validators w handlerach | Częściowe | `validators.py` stworzony, ale tylko `validate_timezone` i `validate_time_format` z `command_handlers.py` importują; `validate_text_length` nie użyty |

---

## Poprawnie zaimplementowane elementy

- **Token tracker** — fire-and-forget przez `asyncio.create_task()`, graceful fail, atomic Firestore increment
- **JWT session** — HS256, 8h expiry, HttpOnly + Secure + SameSite=lax, proper expired/invalid handling
- **Admin role-based access** — `require_admin` / `require_admin_write` Depends, read-only vs admin enforcement
- **Audit log** — middleware dla POST/PATCH/DELETE, email + action + IP + user-agent
- **Security headers** — HSTS, CSP (z wyjątkami dla CDN), X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy
- **Encryption** — AES-256-GCM z random nonce, KMS w produkcji, local fallback w dev
- **Firestore rules** — deny all direct access (Server SDK only)
- **Input validators** — typed ValidationError, timezone walidacja, time format, text length, sanitize_for_logging
- **Dashboard UI** — Jinja2 + Tailwind CDN + Alpine.js + Chart.js, responsywny, role-aware
- **Test coverage** — 47 nowych testów pokrywających JWT, OAuth callback, role enforcement, audit log, encryption round-trip, rate limit 429, validators

---

## Podsumowanie

Faza 5 implementuje solidne fundamenty admin auth i security. JWT session management jest poprawny, role enforcement działa, audit log jest kompletny. Encryption round-trip AES-256-GCM jest kryptograficznie poprawny. Security headers pokrywają OWASP recommendations.

Główne gaps:
1. Rate limiting zdefiniowane ale nieaktywne (infrastruktura bez dekoratorów)
2. Brak CSRF protection na admin write endpoints (SameSite=lax nie wystarczy dla PATCH)
3. Admin OAuth bez state parameter (login CSRF)
4. Duplikacja encryption code zamiast migracji na security/encryption.py
5. Full table scan w queries (skalowalnosc)
