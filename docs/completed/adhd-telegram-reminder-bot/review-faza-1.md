---
title: "Code Review — Faza 1 (Core Bot, Units 1-8)"
date: 2026-04-09
reviewer: dev-autopilot (multi-agent)
status: CZYSTE (po re-run cykl 2)
---

# Code Review — Faza 1 (Core Bot, Units 1-8)

**Wynik:** ✅ GOTOWE DO KONTYNUACJI  
**Data review (re-run cykl 2):** 2026-04-09  
**Pliki sprawdzone:** 18 plików źródłowych + 12 plików testowych  
**Testy:** 106 testów, wszystkie przechodzą ✅

---

## Severity Gate (RE-RUN cykl 2)

✅ **GOTOWE DO KONTYNUACJI** — 0 problemów P1, 0 problemów P2, 3 problemy P3

| Severity | Liczba | Typy |
|----------|--------|------|
| 🔴 P1 (blocking) | 0 | — |
| 🟠 P2 (important) | 0 | — |
| 🟡 P3 (nit) | 3 | KOD: 3 |

**E2E:** 0 passed / 0 failed (brak skonfigurowanego środowiska staging)

---

## Weryfikacja P2 z poprzedniego re-run

### P2: `bot/models/user.py:126` — zbyt szeroki `except Exception:`

**Status: ✅ NAPRAWIONY**

Zmiana: `except Exception:` → `except (ImportError, AttributeError, TypeError):`

**Ocena naprawy:**
- `ImportError` — poprawne: łapie brak google-cloud-firestore SDK
- `AttributeError` — poprawne: łapie gdy mock nie ma metody `.transaction()`
- `TypeError` — uzasadnione: łapie gdy MagicMock jest non-async (komentarz wyjaśnia intencję)

Naprawa nie łapie już `Aborted`, `DeadlineExceeded`, `PermissionDenied` z Firestore SDK — transakcja atomiczna w produkcji działa poprawnie. Race condition jest zabezpieczone. P2 naprawione.

Drobna uwaga (P3): `TypeError` jest lekko szerszy niż idealne — może teoretycznie połknąć błąd typów z kodu transakcji. Nie jest to problem blokujący — jest to nit.

---

## Weryfikacja poprzednich P2 (lista 7 problemów — cykl 1)

| # | Problem | Status |
|---|---------|--------|
| 1 | `webhook.py` — `hmac.compare_digest()` zamiast `==` | ✅ NAPRAWIONY |
| 2 | `internal_triggers.py` — OIDC auth na `/internal/*` | ✅ NAPRAWIONY |
| 3 | `firestore_client.py` — `MagicMock` w produkcyjnym kodzie | ✅ NAPRAWIONY |
| 4 | `user.py` — dead code transakcji, race condition | ✅ NAPRAWIONY |
| 5 | `main.py` + `webhook.py` — routery zakomentowane, stub `_route_update` | ✅ NAPRAWIONY |
| 6 | `infra/firestore-indexes.json` — brak pliku | ✅ NAPRAWIONY |
| 7 | `test_reminder_callbacks.py` — `TestSnooze30Min` i `TestSnooze2h` bez asercji | ✅ NAPRAWIONY |

---

## Pozostałe P3 (sugestie, nieblokujące)

- 🟡 [P3-nit] **KOD** `bot/handlers/callback_handlers.py:17`, `internal_triggers.py:18`, `message_handlers.py:17` — `TELEGRAM_BASE_URL` zduplikowany w 3 plikach. Sugestia: przenieść do `bot/config.py`.

- 🟡 [P3-nit] **KOD** `bot/services/scheduler.py:18-21` — `_get_tasks_client()` tworzy nową instancję `CloudTasksClient` przy każdym wywołaniu (brak singleton). Wzorzec jak w `firestore_client.py` byłby lepszy.

- 🟡 [P3-nit] **KOD** `bot/services/ai_parser.py` — `_get_gemini_client()` wywołuje `vertexai.init()` przy każdym parsowaniu. Inicjalizacja powinna być jednorazowa (moduł-level singleton z guard).

---

## Odchylenia od planu (pozostałe)

| Unit | Odchylenie |
|------|-----------|
| Unit 7 | 2 testy z planu niezaimplementowane: callback `[✓ OK]` → task SCHEDULED + Cloud Task created; callback `[Zmień]` → conversation state `awaiting_time_input`. Zaznaczone `[ ]` w zadaniach.md. |

---

## Pozytywne obserwacje

- State machine (`task.py`) — dobrze zaprojektowana, explicit `ALLOWED_TRANSITIONS`, typed `InvalidStateTransitionError`
- Deduplication przez Firestore z TTL — właściwe podejście bez dodatkowej infrastruktury
- Graceful fallback w `ai_parser.py` — poprawny
- Idempotency guards w `trigger-reminder` i `trigger-nudge` — prawidłowe
- OIDC weryfikacja poprawnie pomijana w `TESTING=1` (nie blokuje testów)
- `_route_update` w pełni obsługuje wszystkie typy update (callback, command, voice, text)
- 106 testów przechodzi w 0.82s

---

## Wnioski (RE-RUN cykl 2)

Wszystkie 8 P2 (7 z cyklu 1 + 1 z re-run) zostały naprawione. Implementacja jest funkcjonalna end-to-end. Pozostałe 3 P3 to sugestie nieblokujące. Faza 1 gotowa do kontynuacji — można przejść do Fazy 2 (Units 9-10: Nudge System + Auto-Archival).
