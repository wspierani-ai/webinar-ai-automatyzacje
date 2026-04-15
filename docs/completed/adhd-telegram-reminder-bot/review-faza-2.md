---
title: "Code Review — Faza 2 (Units 9-10)"
date: 2026-04-09
reviewer: dev-docs-review (multi-agent)
status: completed
---

# Code Review — Faza 2 (Polish: Nudge System + Auto-Archival)

**Data:** 2026-04-09  
**Faza:** 2 (Unit 9: Nudge System, Unit 10: Auto-Archival)  
**Testy:** 18/18 passed (124 łącznie)  

---

## Podsumowanie wykonawcze

Faza 2 dostarcza dwa stabilne, idempotentne endpointy `/internal/trigger-nudge` i `/internal/cleanup`. Implementacja jest spójna z architekturą Fazy 1, testy pokrywają happy path + idempotency guards. Nie wykryto żadnych problemów P1 (blocking). Znaleziono 3 problemy P2 (important) i 4 problemy P3 (nit).

**Severity gate:** ⚠️ KONTYNUUJ Z ZASTRZEŻENIAMI — 3 problemy P2 do naprawy

---

## Agent 1: Security Review

### Findings

**🟠 [P2-important] cleanup_handler.py:55 — `except Exception` w `_verify_oidc_token` łapie zbyt szeroko**

```python
except Exception as exc:
    logger.warning("OIDC token verification failed: %s", exc)
    raise HTTPException(status_code=401, detail="Invalid OIDC token") from exc
```

Ten sam wzorzec istnieje w obu plikach (`cleanup_handler.py:55` i `internal_triggers.py:46`). Łapanie generycznego `Exception` maskuje potencjalne błędy programistyczne (np. `AttributeError` od brakującej konfiguracji) jako "Invalid OIDC token 401". Powinno łapać konkretne typy z `google.oauth2.exceptions` — `GoogleAuthError`, `TransportError`.

**Ryzyko:** Błędy konfiguracji środowiska (np. brak `CLOUD_RUN_SERVICE_URL`) będą zwracać 401 zamiast 500, utrudniając diagnozę w produkcji.

**Naprawa:**
```python
from google.auth.exceptions import GoogleAuthError, TransportError
except (GoogleAuthError, TransportError, ValueError) as exc:
    ...
```

---

**🟠 [P2-important] cleanup_handler.py:106-111 — Logika "block immediately" gdy `grace_period_until is None` jest potencjalnie błędna**

```python
if grace_period_until is None:
    # No grace period end date — block immediately
    await doc.reference.update({"subscription_status": "blocked", ...})
    count += 1
    continue
```

Użytkownik z `subscription_status="grace_period"` ale bez `grace_period_until` jest natychmiast blokowany. Ten warunek nie jest udokumentowany w planie (Unit 10) i może powodować niezamierzone blokady użytkowników — np. gdy Stripe event `invoice.payment_failed` (Unit 11) zostanie obsłużony częściowo. To ciche blokowanie bez logu `logger.warning` jest trudne do debugowania.

**Ryzyko:** Użytkownicy mogą być błędnie blokowani przy częściowych błędach w przyszłym Unit 11.

**Naprawa:** Dodaj `logger.warning("Blocking grace_period user %s: no grace_period_until", ...)` i rozważ skip zamiast blokowania gdy `grace_period_until is None`.

---

**🟡 [P3-nit] cloud-scheduler-cleanup.yaml — `${CLOUD_RUN_SERVICE_URL}` jako literal string**

YAML zawiera `"${CLOUD_RUN_SERVICE_URL}"` jako literal — nie jest to plik szablonu z automatycznym podstawianiem. Deploy comment w pliku używa `gcloud scheduler` z `--uri="${CLOUD_RUN_SERVICE_URL}"` co jest poprawne dla shell, ale sam YAML nie zadziała jako-jest przez `gcloud scheduler jobs import`. Nie jest to bloker (deploy przez CLI zadziała), ale warto to udokumentować.

---

## Agent 2: Performance Review

### Findings

**🟠 [P2-important] cleanup_handler.py:140-168 — N+1 Firestore writes w `_cleanup_orphaned_cloud_tasks`**

```python
for state in ("COMPLETED", "REJECTED"):
    query = tasks_ref.where("state", "==", state)
    docs = await query.get()
    for doc in docs:
        if cloud_task_name:
            await cancel_reminder(cloud_task_name)
            await doc.reference.update({"cloud_task_name": None, ...})  # write per doc
        if nudge_task_name:
            await cancel_reminder(nudge_task_name)
            await doc.reference.update({"nudge_task_name": None, ...})  # kolejny write per doc
```

Każdy task z oboma polami (`cloud_task_name` i `nudge_task_name`) generuje **2 osobne Firestore writes** zamiast 1. Przy 100 zakończonych taskach z oboma polami = 200 writes zamiast 100.

Dodatkowo `cancel_reminder` jest `async` ale wywoływany sekwencyjnie w pętli — N cancel operations, każdy z osobnym gRPC round-trip do Cloud Tasks. 

**Przy skali 1000 taskach COMPLETED:** 1000+ sequential gRPC calls → timeout cleanup jobu.

**Naprawa:** Połącz dwa updates w jedno wywołanie + rozważ `asyncio.gather()` dla parallel cancel calls:
```python
update_data = {}
if cloud_task_name:
    update_data["cloud_task_name"] = None
if nudge_task_name:
    update_data["nudge_task_name"] = None
if update_data:
    update_data["updated_at"] = now
    await doc.reference.update(update_data)
```

---

**🟡 [P3-nit] cleanup_handler.py — Brak limitu na Firestore queries**

```python
query = users_ref.where("subscription_status", "==", "trial")
docs = await query.get()
```

Brak `.limit()` na query. Przy MVP (<100 userów) to nie jest problem. Przy 10,000+ userów trial query pobiera cały zbiór do pamięci. Nie jest to bloker dla Fazy 2, ale warto odnotować dla przyszłego hardening.

---

## Agent 3: Architecture & Code Quality

### Findings

**🟡 [P3-nit] Duplikacja `_verify_oidc_token` w dwóch plikach**

Identyczna funkcja `_verify_oidc_token` (linie 32-57 w `cleanup_handler.py` i linie 23-48 w `internal_triggers.py`) jest copy-paste. Zgodnie z regułą "abstrakcja gdy 2+ użycia" powinna być wyciągnięta do `bot/security/` lub `bot/handlers/_oidc.py`.

**Ryzyko:** Każda zmiana logiki OIDC (np. dodanie audience validation) wymaga edycji w dwóch miejscach — fragment o `_INTERNAL_AUDIENCE or None` musi być zsynchronizowany.

**Naprawa:** Wyciągnij do `bot/handlers/_auth.py` lub poczekaj na Unit 18 (Security Hardening) gdzie będzie naturalne miejsce.

**Uwaga:** To jest 🟡 P3 (nie P2) bo oba pliki mają identyczną implementację — ryzyko desynchronizacji jest niskie przy obecnym rozmiarze projektu. Można odłożyć do Unit 18.

---

**🟡 [P3-nit] internal_triggers.py:18 — `TELEGRAM_BASE_URL` nadal zduplikowany**

Z review Fazy 1 (P3 carry-over): `TELEGRAM_BASE_URL = "https://api.telegram.org"` wciąż w 3 plikach. Faza 2 nie naprawiła tego (jest to P3, więc nieblokujące).

---

**🟡 [P3-nit] cleanup_handler.py — `_cleanup_orphaned_cloud_tasks` ma zbyt dużo odpowiedzialności**

Funkcja wykonuje: 2 Firestore queries + pętla przez docs + 2 Cloud Task cancels + 2 Firestore updates per doc. To 5 różnych operacji w jednej funkcji (>50 linii). Zgodnie z zasadą "jedna funkcja = jeden poziom abstrakcji" warto rozważyć wyciągnięcie logiki czyszczenia jednego tasku do pomocniczej funkcji.

---

## Agent 4: Scenario Exploration & Test Coverage

### Findings — brakujące scenariusze

**🟡 [P3-nit] test_nudge.py — brak testu dla `PENDING_CONFIRMATION` i `SCHEDULED` state**

Plan Unit 9 specyfikuje że nudge jest wysyłany tylko dla `REMINDED`. Testy pokrywają: COMPLETED, SNOOZED, NUDGED, REJECTED — ale nie testują zachowania dla `PENDING_CONFIRMATION` i `SCHEDULED`. Przy obecnej implementacji te stany zwrócą 200 z "not in REMINDED state" (poprawnie), ale nie ma testu to potwierdzającego.

---

**🟡 [P3-nit] test_cleanup.py — brak testu dla task z OBOMA `cloud_task_name` i `nudge_task_name`**

Testy sprawdzają case: tylko `cloud_task_name` (COMPLETED) i tylko `nudge_task_name` (REJECTED). Brak testu dla task z oboma ustawionymi — w tym przypadku `cancel_reminder` powinna być wywołana dwukrotnie i count powinno być nadal 1 (nie 2). Ten brak potwierdza też N+1 finding z Agent 2.

---

**🟡 [P3-nit] test_cleanup.py — test `test_nudge_missing_task_id_returns_400` w złym miejscu**

W pliku `test_nudge.py` (linia 299) test `test_nudge_missing_task_id_returns_400` jest w klasie `TestTriggerNudgeMissingTask` podczas gdy dotyczy braku `task_id` w body (nie brakującego task dokumentu). Naming jest mylące.

---

**Weryfikacja pokrycia planu — ✅ ZGODNA**

Plan Unit 9 wymagał testów:
- `trigger-nudge` z `REMINDED` → nudge + `NUDGED` ✅ (test_nudge.py:60, :87)
- `trigger-nudge` z `COMPLETED` → 200, brak nudge ✅ (test_nudge.py:160)
- `trigger-nudge` z `SNOOZED` → 200, brak nudge ✅ (test_nudge.py:185)
- Idempotency (NUDGED → brak 2. nudge) ✅ (test_nudge.py:211)
- Nudge message zawiera task.content ✅ (test_nudge.py:127)

Plan Unit 10 wymagał testów:
- Blocked expired trial ✅ (test_cleanup.py:110)
- Blocked expired grace_period ✅ (test_cleanup.py:161)
- Orphaned Cloud Tasks deleted ✅ (test_cleanup.py:211)
- Empty data → 200 ✅ (test_cleanup.py:261)
- 401 bez auth ✅ (test_cleanup.py:284)

**Wszystkie wymagane testy z planu zaimplementowane.**

---

## Agent 5: E2E Browser Verification

Faza 2 nie zawiera komponentów UI. Checkboxy `Weryfikacja:` w pliku zadań dla Fazy 2 wymagają staging environment (Cloud Run + Cloud Tasks + Firestore):

```
- [ ] Weryfikacja: Task w `REMINDED` przez 1h → nudge wysłany (test staging z `fire_at=now+65s`)
- [ ] Weryfikacja: Task `COMPLETED` przed upływem 1h → nudge nie wysłany
- [ ] Weryfikacja: Task z `expires_at = now() - 31 days` znika z Firestore w ciągu 25h
- [ ] Weryfikacja: Cleanup job w Cloud Scheduler widoczny jako SUCCESS
```

**Wynik:** Brak E2E weryfikacji możliwej bez staging. Wszystkie checkboxy pozostają niezaznaczone — wymagają ręcznej weryfikacji po deployu na Cloud Run.

---

## Odchylenia od planu

| Plan | Implementacja | Status |
|------|---------------|--------|
| Unit 9: Modyfikacja `internal_triggers.py` — implementacja `/internal/trigger-nudge` | ✅ Zaimplementowane | Zgodne |
| Unit 9: `tests/test_nudge.py` | ✅ 9 testów | Zgodne |
| Unit 10: `infra/firestore-indexes.json` — TTL fieldOverride | ✅ Dodany | Zgodne |
| Unit 10: `bot/handlers/cleanup_handler.py` | ✅ Stworzony | Zgodne |
| Unit 10: `infra/cloud-scheduler-cleanup.yaml` | ✅ Stworzony | Zgodne |
| Unit 10: `tests/test_cleanup.py` — 9 testów | ✅ 9 testów | Zgodne |
| Unit 10: Modyfikacja `main.py` — podpięcie cleanup_router | ✅ Podpięty | Zgodne |

Brak odchyleń od planu. Wszystkie pliki zdefiniowane w Units 9-10 zostały stworzone.

---

## Skonsolidowana lista findingów

| # | Severity | Plik:linia | Opis |
|---|----------|------------|------|
| 1 | 🟠 P2 | cleanup_handler.py:55, internal_triggers.py:46 | `except Exception` w OIDC verify — maskuje błędy konfiguracji jako 401 |
| 2 | 🟠 P2 | cleanup_handler.py:106-111 | Natychmiastowe blokowanie gdy `grace_period_until is None` bez logu warning |
| 3 | 🟠 P2 | cleanup_handler.py:148-167 | N+1 Firestore writes: 2 oddzielne `.update()` zamiast 1 per task |
| 4 | 🟡 P3 | cleanup_handler.py, internal_triggers.py | Duplikacja `_verify_oidc_token` — wyciągnąć do Unit 18 |
| 5 | 🟡 P3 | internal_triggers.py:18 | `TELEGRAM_BASE_URL` carry-over z Fazy 1 |
| 6 | 🟡 P3 | test_nudge.py | Brak testów dla stanów PENDING_CONFIRMATION i SCHEDULED |
| 7 | 🟡 P3 | test_cleanup.py | Brak testu dla task z oboma cloud_task_name + nudge_task_name |

---

## Statystyki

- Pliki sprawdzone: 7 (cleanup_handler.py, internal_triggers.py, test_nudge.py, test_cleanup.py, scheduler.py, firestore-indexes.json, cloud-scheduler-cleanup.yaml)
- 🔴 P1 [blocking]: 0
- 🟠 P2 [important]: 3
- 🟡 P3 [nit]: 4
- 🌐 E2E: 0/4 (brak staging)

---

## Rekomendacje

### Napraw przed Fazą 3:
1. **P2 #1** — Zawęź `except Exception` do konkretnych typów Google Auth errors
2. **P2 #2** — Dodaj `logger.warning` dla case `grace_period_until is None`, rozważ skip zamiast blokowania  
3. **P2 #3** — Scal dwa `.update()` calls w `_cleanup_orphaned_cloud_tasks` w jedno wywołanie

### Odłóż na Unit 18 (Security Hardening):
- Wyciągnięcie `_verify_oidc_token` do wspólnego modułu
- `TELEGRAM_BASE_URL` → `config.py`

### Dobry wzorzec do kontynuacji:
- Idempotency guards w obu endpointach (state-based guard) — wzorzec spójny z Fazą 1
- Niezależne try/except dla każdej fazy cleanup — poprawna izolacja błędów
- Cleanup jest idempotentny — bezpieczne do wielokrotnego wywołania
- YAML z komentarzem deploy command — dobra dokumentacja infra

---

## Severity Gate

⚠️ **KONTYNUUJ Z ZASTRZEŻENIAMI** — 3 problemy P2 do naprawy przed Fazą 3 lub na początku Fazy 3.

---

## Re-run cykl 1 — Weryfikacja naprawy P2 (2026-04-10)

**Wynik re-run:** ✅ GOTOWE DO KONTYNUACJI — P1=0, P2=0, P3=4

### Status naprawionych P2

| # | P2 | Plik:linia po naprawie | Status |
|---|----|------------------------|--------|
| 1 | `except Exception` → `except (GoogleAuthError, TransportError, ValueError)` | `cleanup_handler.py:56`, `internal_triggers.py:47` | ✅ Naprawione |
| 2 | `grace_period_until is None` → `logger.warning` + `continue` (skip) | `cleanup_handler.py:106-112` | ✅ Naprawione |
| 3 | N+1 Firestore writes → scalony `update_data` dict + 1 `doc.reference.update()` | `cleanup_handler.py:149-160` | ✅ Naprawione |

### Szczegóły weryfikacji

**P2 #1 — OIDC except zawężony:**
Oba pliki używają teraz `except (GoogleAuthError, TransportError, ValueError)`. Import przeniesiony lazy wewnątrz bloku try — wzorzec identyczny z oryginalnym kodem Fazy 1.

**P2 #2 — grace_period_until is None guard:**
Kod `cleanup_handler.py:106-112` zawiera `logger.warning("Skipping grace_period user %s: grace_period_until is None", ...)` + `continue`. Użytkownik nie jest już natychmiast blokowany przy braku pola — odpowiednie zachowanie defensywne przed wdrożeniem Unit 11.

**P2 #3 — N+1 Firestore writes scalony:**
Wzorzec `update_data: dict = {}` builder akumuluje klucze dla `cloud_task_name` i `nudge_task_name`, następnie wykonuje pojedyncze `doc.reference.update(update_data)`. Count inkrementowany raz per task (nie per pole).

### Pozostałe otwarte P3 (bez zmian)

| # | P3 | Status |
|---|----|--------|
| 4 | Duplikacja `_verify_oidc_token` | Odłożone do Unit 18 |
| 5 | `TELEGRAM_BASE_URL` w 3 plikach | Odłożone do Unit 18 |
| 6 | Brak testów PENDING_CONFIRMATION/SCHEDULED w test_nudge.py | Odłożone |
| 7 | Brak testu dla task z oboma task names w test_cleanup.py | Odłożone |

### Severity Gate po re-run

✅ **GOTOWE DO KONTYNUACJI** — wszystkie P2 naprawione. P3 odłożone do Unit 18.
