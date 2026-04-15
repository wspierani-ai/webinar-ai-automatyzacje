---
title: "Review Fazy 3 — Monetyzacja (Unit 11)"
phase: 3
date: 2026-04-09
result: "⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI"
p1: 0
p2: 3
p3: 5
rerun_cykl_1_result: "✅ GOTOWE DO KONTYNUACJI"
rerun_cykl_1_date: 2026-04-09
rerun_cykl_1_p1: 0
rerun_cykl_1_p2: 0
rerun_cykl_1_p3: 5
---

# Review Fazy 3 — Monetyzacja (Unit 11)

**Wynik:** ⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI — P1=0, P2=3, P3=5  
**Testy:** 152/152 przechodzą  
**Pliki sprawdzone:** 5 (stripe_service.py, stripe_webhook_handler.py, payment_command_handlers.py, test_stripe_service.py, test_stripe_webhooks.py)

---

## Re-run Review Fazy 3 — cykl 1 (weryfikacja naprawy P2) (2026-04-09)

**Wynik:** ✅ GOTOWE DO KONTYNUACJI — P1=0, P2=0, P3=5

### P2 z cyklu 0 — naprawione ✅

#### P2-1: Mark-before-handle — NAPRAWIONE ✅
**Plik:** `bot/handlers/stripe_webhook_handler.py`
Kolejność odwrócona: handler uruchamiany wewnątrz bloku `try` (linie 89-99), a `mark_event_processed` wywołany dopiero PO sukcesie handlera (linie 107-109). Przy wyjątku z handlera endpoint zwraca 500 bez markowania — Stripe może ponowić. Komentarz w kodzie (linia 107) potwierdza intencję: _"Mark as processed only after successful handler execution so Stripe can retry on failure"_.

#### P2-2: Telegram notification przy payment events — NAPRAWIONE ✅
**Plik:** `bot/services/stripe_service.py`
- Dodana funkcja `_send_telegram_notification(telegram_user_id, text)` (linie 15-31) — no-op w TESTING=1, używa httpx w produkcji
- `handle_invoice_payment_failed` (linie 183-195): wysyła "Płatność nie powiodła się 💳 Masz 3 dni na aktualizację karty: /billing" — ✅ zgodne z planem
- `handle_subscription_deleted` (linie 245-257): wysyła "Subskrypcja anulowana. Wznów przez /subscribe." — ✅ zgodne z planem
- Notification failure logowany jako error (nie propaguje wyjątku) — bezpieczny wzorzec

#### P2-3: Stripe Billing Portal — NAPRAWIONE ✅
**Plik:** `bot/handlers/payment_command_handlers.py`
`handle_billing()` implementuje `stripe.billing_portal.Session.create(customer=user.stripe_customer_id, return_url=return_url)` (linie 121-125) — zgodne z planem (linia 772-773). Użytkownik bez `stripe_customer_id` dostaje komunikat z sugestią `/subscribe`. Link do portalu wysyłany przez `_send_message`.

### Łącznie naprawione P2 (3/3)
- Mark-before-handle w stripe_webhook_handler.py — ✅
- Telegram notification w handle_invoice_payment_failed — ✅
- Telegram notification w handle_subscription_deleted — ✅
- Stripe Billing Portal w payment_command_handlers.py — ✅

### Pozostałe P3 (5 — nieblokujące, do Unit 18 lub Faza 5)
- P3-1: `except Exception` w `_verify_stripe_signature:60` — zawęź do `stripe.error.SignatureVerificationError`
- P3-2: `STRIPE_API_KEY` z `os.environ` zamiast Config singleton — odczyt z Config.from_env()
- P3-3: `except Exception` w routerze eventów (linia 101) — zawęź do konkretnych typów
- P3-4: `except Exception` w `handle_subscribe:72` — ukrywa AuthenticationError Stripe
- P3-5: `TELEGRAM_BASE_URL` zduplikowany w 5 plikach (carryover z Faz 1-2)

---

## Odchylenia od planu technicznego

### Udokumentowane (OK)

- **Lazy Stripe Customer creation**: Plan (linia 759) zakłada tworzenie Customer przy `/start`. Implementacja tworzy Customer lazy przy `/subscribe`. Decyzja udokumentowana w `adhd-telegram-reminder-bot-kontekst.md:423` — akceptowalne.

### Nieudokumentowane odchylenia (wymagają uwagi)

- **`/billing` komenda** — plan (linia 772-773) definiuje: `stripe.billing_portal.Session.create(customer=customer_id) → wyślij URL`. Implementacja wyświetla tylko tekstowy status subskrypcji bez przekierowania do Stripe Billing Portal. Brak informacji w kontekście, że to świadoma zmiana.
- **Brak Telegram notification przy payment_failed / subscription.deleted** — plan (linia 783-785) wymaga wysłania wiadomości Telegram: _"Płatność nie powiodła się 💳 Masz 3 dni..."_ i _"Subskrypcja anulowana..."_. Handlery w `stripe_service.py` aktualizują tylko Firestore — brak wysyłki Telegram.

---

## Findings — P2 (Important)

### P2-1: Mark-before-handle TOCTOU — utrata eventu przy 500
**Plik:** `bot/handlers/stripe_webhook_handler.py:89,105-108`  
**Opis:** Wzorzec mark-before-handle (linia 89: `mark_event_processed` przed handlerem) powoduje, że gdy handler rzuci wyjątek (linia 105-108: `except Exception → return 500`), event jest już oznaczony jako processed. Stripe ponowi próbę na 500 → `is_event_duplicate` zwróci True → event **trwale pominięty**. Dotknięte eventy: `checkout.session.completed`, `invoice.payment_failed`, `customer.subscription.deleted`. Użytkownik może nigdy nie dostać aktywacji subskrypcji lub grace period.  
**Rekomendacja:** Zmień kolejność: handler uruchom PRZED `mark_event_processed`. Jeśli handler powiedzie się → mark → return 200. Jeśli handler rzuci → return 500 bez mark (Stripe ponowi). Ewentualnie: przy wyjątkach z handlera usuń dedup record przed zwrotem 500.

### P2-2: Brak Telegram notification przy kluczowych płatniczych eventach
**Plik:** `bot/services/stripe_service.py:137-217`  
**Opis:** Zgodnie z planem technicznym (linia 783-785) obsługa `invoice.payment_failed` ma wysyłać: _"Płatność nie powiodła się 💳 Masz 3 dni na aktualizację karty: /billing"_, a `customer.subscription.deleted` ma wysyłać: _"Subskrypcja anulowana. Wznów przez /subscribe."_. Obu tych notyfikacji brakuje w implementacji. Użytkownicy nie będą informowani o problemach z płatnością przez bota — dowiedzą się jedynie przy następnym zadaniu gdy dostaną komunikat blokady.  
**Rekomendacja:** Dodaj wywołanie Telegram `sendMessage` w `handle_invoice_payment_failed` i `handle_subscription_deleted`. Handlery mają `telegram_user_id` z `user_doc` (przez `_find_user_by_customer_id`).

### P2-3: `/billing` nie otwiera Stripe Billing Portal (odchylenie od planu bez dokumentacji)
**Plik:** `bot/handlers/payment_command_handlers.py:98-153`  
**Opis:** Plan techniczny (linia 772-773) definiuje `/billing` jako: `stripe.billing_portal.Session.create(customer=customer_id) → wyślij URL`. Implementacja `handle_billing()` wyświetla jedynie tekstowy status subskrypcji (active/trial/grace_period/blocked) bez przekierowania do Stripe Billing Portal. Użytkownicy z `active` statusem nie mają możliwości zarządzania kartą ani anulowania subskrypcji przez bota. Komentarz w kodzie (`# Aby anulować, skontaktuj się z pomocą techniczną`) potwierdza świadomą zmianę, ale nie jest udokumentowana w kontekście.  
**Rekomendacja:** Zaimplementuj Stripe Billing Portal albo zaktualizuj dokumentację jako świadome odejście od planu z uzasadnieniem.

---

## Findings — P3 (Nit)

### P3-1: `except Exception` w `_verify_stripe_signature` (linia 60)
**Plik:** `bot/handlers/stripe_webhook_handler.py:54-62`  
**Opis:** Łapie `Exception` zamiast `stripe.error.SignatureVerificationError` (specifyczny typ z SDK). Może maskować np. błędy importu stripe jako "Invalid Stripe signature". Spójny wzorzec z Fazą 2 P2-1 (naprawiony tam). Tu też warto zawęzić.  
**Rekomendacja:** Zawęź do `except (stripe.error.SignatureVerificationError, ValueError):`.

### P3-2: `_get_stripe()` i STRIPE_API_KEY z `os.environ` zamiast Config singleton
**Plik:** `bot/services/stripe_service.py:15-19` + `stripe_webhook_handler.py:57`  
**Opis:** `_get_stripe()` ustawia `api_key` przy każdym wywołaniu z `os.environ`, omijając Config singleton (`bot/config.py`). Duplikacja wzorca odczytu konfiguracji, niespójna z resztą kodu. Przy testach: potencjalny problem gdy `STRIPE_API_KEY` nie jest ustawiony (pusty string → Stripe AuthenticationError zamiast czytelnego błędu).  
**Rekomendacja:** Odczytaj klucz z `Config.from_env()` lub przynajmniej waliduj że nie jest pusty przed wysłaniem do Stripe.

### P3-3: `except Exception` w handlerze webhooka (linia 105)
**Plik:** `bot/handlers/stripe_webhook_handler.py:105`  
**Opis:** Broad exception catch dla bloków obsługi eventów. Ukrywa konkretny typ błędu (Firestore `DeadlineExceeded`, `PermissionDenied` itp.) — diagnoza wolniejsza. Wzorzec z Fazy 2 sugeruje zawężenie do konkretnych typów.

### P3-4: `except Exception` w `handle_subscribe` (linia 71)
**Plik:** `bot/handlers/payment_command_handlers.py:71`  
**Opis:** Łapie wszystkie wyjątki przy tworzeniu Checkout Session. Ukrywa np. `AuthenticationError` (błędny klucz API) — user dostaje generyczny komunikat zamiast alertu dla devops.

### P3-5: `TELEGRAM_BASE_URL` zduplikowany w 5 plikach (carryover z Fazy 1 i 2)
**Plik:** `bot/handlers/payment_command_handlers.py:16`, `command_handlers.py:14`, `message_handlers.py:17`, `callback_handlers.py:17`, `internal_triggers.py:18`  
**Opis:** Nowy plik `payment_command_handlers.py` kontynuuje duplikację. Otwarty P3 z Fazy 1 i 2 — naturalne miejsce do naprawy przed Fazą 5.

---

## Security Review

### Weryfikacja sygnatury Stripe
- `stripe.Webhook.construct_event()` używany poprawnie (linia 58) — OK
- TESTING=1 bypass dla testów — w kodzie produkcyjnym bezpieczny (env var kontrolowana)
- `STRIPE_WEBHOOK_SECRET` czytany z `os.environ` per request — brak cachowania ale nie jest to problem wydajnościowy

### Deduplication
- Wzorzec `stripe_events/{event_id}` — poprawna architektura
- Brak TTL w `stripe_events` (zgodnie z decyzją w kontekście) — OK dla MVP
- TOCTOU race condition (P2-1): przy skalowaniu do multi-instance Cloud Run może dojść do double processing przy równoczesnych requestach zanim `mark_event_processed` się zakończy — ryzyko akceptowalne przy MVP (<5 instancji Cloud Run min-instances=1)

### Race condition: concurrent /subscribe
- `create_or_get_stripe_customer`: sprawdzenie `user.stripe_customer_id` na obiekcie in-memory, nie z Firestore transaction. Przy dwóch równoczesnych `/subscribe` (teoretycznie) mogą powstać dwa Stripe Customers dla jednego usera — Stripe to akceptuje, ale cleanup jest trudny.
- W praktyce ryzyko minimalne (user raczej nie wyśle `/subscribe` dwukrotnie równocześnie).

---

## Coverage Analysis

### Pokryte scenariusze (z planu Unit 11)
- [x] `/subscribe` tworzy Checkout Session z currency=PLN — POKRYTE (test_stripe_service)
- [x] `checkout.session.completed` → active + subscription_id — POKRYTE
- [x] `invoice.payment_failed` → grace_period + 3d — POKRYTE
- [x] `invoice.payment_succeeded` → active, grace=None — POKRYTE
- [x] `customer.subscription.deleted` → blocked — POKRYTE
- [x] Duplicate event.id → 200 skip — POKRYTE
- [x] Webhook z błędnym secret → 400 — POKRYTE
- [x] Blocked user → komunikat blokady + /subscribe — POKRYTE

### Brakujące testy (niewymagane przez plan ale luki)
- [ ] `handle_subscribe` handler level test (testowane tylko na poziomie serwisu, nie na poziomie komendy)
- [ ] `handle_billing` handler level test
- [ ] Test: handler failure po mark_event_processed → event lost scenario

---

## Ocena ogólna

Implementacja jest funkcjonalnie kompletna dla happy path. Security webhook veryfikacji jest poprawna. Deduplication działa. Główne problemy to:

1. Mark-before-handle pattern tworzy ryzyko utraty eventów (P2-1) — wymaga zamiany kolejności operacji
2. Brak Telegram notyfikacji przy payment events (P2-2) — feature gap wobec planu
3. `/billing` bez Stripe Portal (P2-3) — odchylenie od planu bez dokumentacji

Faza 4 (Google Integration) może być kontynuowana po naprawieniu P2-1 i P2-2. P2-3 jest ważny dla UX ale nie blokuje technicznie.
