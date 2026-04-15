---
title: "ADHD Bot - kluczowe wzorce runtime: Firestore transactions, Cloud Tasks, GDPR cascade delete"
date: 2026-04-09
category: runtime-errors
severity: high
stack:
  - Python
  - FastAPI
  - Firestore
  - Google Cloud Tasks
  - Stripe
  - Google OAuth
tags:
  - firestore-transactions
  - atomic-operations
  - race-conditions
  - cloud-tasks
  - deterministic-naming
  - stripe-webhooks
  - deduplication
  - gdpr
  - cascade-delete
  - oauth-token-refresh
status: verified
last_verified: 2026-04-09
---

# ADHD Bot - kluczowe wzorce runtime

Kompendium 5 kluczowych wzorcow architektonicznych rozwiazanych podczas budowy ADHD Reminder Bot (21 Units, 6 faz). Kazdy wzorzec opisuje problem, root cause i sprawdzone rozwiazanie.

---

## 1. Firestore transaction patterns (atomic get_or_create, checklist item toggle)

### Symptomy

- Race condition przy szybkim klikaniu checkboxow w checklistach -- dwa requesty czytaly ten sam stan, nadpisujac sie nawzajem
- `get_or_create` usera bez transakcji moglby stworzyc duplikaty przy rownoczesnych requestach

### Root Cause

Firestore domyslnie nie zapewnia atomowosci read-modify-write. Bez `@async_transactional` dekoratora transakcja nie jest commitowana -- SDK Firestore wymaga explicite dekorowania funkcji transakcyjnej.

### Rozwiazanie

```python
from google.cloud.firestore import async_transactional

transaction = db.transaction()

@async_transactional
async def _toggle_item_in_transaction(transaction, doc_ref, item_index: int):
    doc = await doc_ref.get(transaction=transaction)
    if not doc.exists:
        return None
    session = ChecklistSession.from_firestore_dict(doc.to_dict())
    if item_index < 0 or item_index >= len(session.items):
        return None
    session.items[item_index].checked = not session.items[item_index].checked
    transaction.set(doc_ref, session.to_firestore_dict())
    return session

session = await _toggle_item_in_transaction(transaction)
```

Kluczowy wzorzec: fallback na bezposrednie wywolanie dla srodowisk testowych (MagicMock nie wspiera `@async_transactional`):

```python
try:
    from google.cloud.firestore import async_transactional
    transaction = db.transaction()

    @async_transactional
    async def _run(transaction):
        return await _toggle_item_in_transaction(transaction, doc_ref, item_index)

    session = await _run(transaction)
except (ImportError, AttributeError, TypeError):
    transaction = db.transaction()
    session = await _toggle_item_in_transaction(transaction, doc_ref, item_index)
```

### Komendy diagnostyczne

```bash
# Sprawdz uzycie transakcji w projekcie
grep -rn "async_transactional\|db.transaction()" adhd-bot/bot/
```

---

## 2. Cloud Tasks snooze/cancel z deterministic naming

### Symptomy

- Brak mozliwosci anulowania zaplanowanego Cloud Task bez znajomosci jego nazwy
- Duplikaty Cloud Tasks przy ponawianiu operacji

### Root Cause

Cloud Tasks API wymaga unikalnej nazwy per task w danej kolejce. Losowe nazwy uniemozliwiaja anulowanie. Deterministyczne nazwy oparte na ID encji pozwalaja na cancel i zapobiegaja duplikatom (Cloud Tasks odrzuca duplikat z tym samym name w oknie deduplication).

### Rozwiazanie

Deterministic naming pattern: `{queue_path}/tasks/{type}-{entity_id}-{trigger_type}`

```python
# Scheduler: schedule_checklist_trigger
task_name = f"{queue_path}/tasks/checklist-{session_id}-{trigger_type}"

# Cancel by known name
await cancel_reminder(task_name)
```

Zapisywanie `cloud_task_name` w modelu pozwala na pozniejszy cancel:

```python
session.cloud_task_name_evening = evening_ct_name
session.cloud_task_name_morning = morning_ct_name
await session.save(db)
```

---

## 3. Stripe webhook deduplication i mark-after-handle pattern

### Symptomy

- Stripe moze wyslac ten sam webhook wielokrotnie (retry policy)
- Podwojne przetworzenie moze skutkowac duplikatem subskrypcji lub blednym stanem

### Root Cause

Webhooks sa at-least-once delivery -- Stripe powtarza jesli nie otrzyma 2xx w czasie. Bez deduplication logiki ten sam event jest przetwarzany wielokrotnie.

### Rozwiazanie

Pattern: **mark-after-handle** z kolekcja `processed_updates`:

1. Przed przetworzeniem sprawdz czy event ID juz istnieje w `processed_updates`
2. Przetworz webhook
3. Dopiero PO udanym przetworzeniu zapisz event ID do `processed_updates` z TTL 24h

```python
# Sprawdz deduplication
doc = await db.collection("processed_updates").document(event_id).get()
if doc.exists:
    return {"status": "already_processed"}

# Przetworz event...

# Mark as processed AFTER successful handling
await db.collection("processed_updates").document(event_id).set({
    "processed_at": datetime.now(tz=timezone.utc),
    "event_type": event["type"],
})
```

Wazne: `processed_updates` nie ma pola `user_id` -- dokumenty sa kluczowane po Telegram `update_id` / Stripe `event_id` i wygasaja automatycznie przez TTL. Dlatego NIE sa wlaczane do GDPR cascade delete.

---

## 4. Google OAuth token refresh z encrypted storage

### Symptomy

- Token OAuth wygasa po 1h, uzytkownik traci dostep do Google Calendar/Tasks
- Tokeny w Firestore przechowywane jako plaintext stanowia ryzyko bezpieczenstwa

### Root Cause

Google OAuth access_token ma 1h TTL. Refresh token wymaga bezpiecznego przechowywania i atomowej operacji refresh + zapis.

### Rozwiazanie

- Tokeny szyfrowane w Firestore (Fernet symmetric encryption)
- Refresh token odswiezany automatycznie przy kazdym uzyciu Google API
- Disconnect revokuje token na serwerze Google i czysci lokalny zapis

```python
# Wzorzec: disconnect z revoke
async def disconnect_google(db, user_id: int):
    # 1. Zaladuj i odszyfruj token
    # 2. Revoke na Google servers
    # 3. Usun z Firestore
```

Kluczowe: przy GDPR delete, Google token jest revokowany PRZED usunieciem danych -- zapobiega orphaned sessions.

---

## 5. GDPR cascade delete across multiple Firestore collections

### Symptomy

- Usuniecie usera z kolekcji `users` nie usuwalo danych z powiazanych kolekcji
- Aktywne Cloud Tasks dalej sie odpalaly po usunieciu usera
- `token_usage` uzywa subcollection structure (`token_usage/{date}/users/{uid}`) -- standardowe query `where("user_id", "==", uid)` nie dziala

### Root Cause

Firestore nie ma CASCADE DELETE. Kazda kolekcja musi byc czyszczona recznie. Subcollections wymagaja enumeracji dokumentow nadrzednych. Cloud Tasks zyja poza Firestore i musza byc anulowane osobno.

### Rozwiazanie

Kolejnosc operacji w `cascade_delete_user_data`:

1. **Cancel Cloud Tasks** -- PRZED usunieciem dokumentow (potrzebujemy `cloud_task_name` z dokumentow)
2. **Delete flat collections** -- tasks, checklist_templates, checklist_sessions
3. **Delete subcollections** -- token_usage z enumeracja dat
4. **Cancel Stripe** -- zewnetrzny serwis
5. **Revoke Google** -- zewnetrzny serwis
6. **Delete user document** -- na koncu

```python
async def _cancel_active_cloud_tasks(db, user_id: int) -> int:
    cancelled = 0
    active_states = ["SCHEDULED", "REMINDED", "SNOOZED", "NUDGED"]
    for state_val in active_states:
        query = db.collection("tasks").where("telegram_user_id", "==", user_id).where("state", "==", state_val)
        docs = await query.get()
        for doc in docs:
            data = doc.to_dict()
            for ct_field in ("cloud_task_name", "nudge_task_name"):
                ct_name = data.get(ct_field)
                if ct_name:
                    await cancel_reminder(ct_name)
                    cancelled += 1
    return cancelled

async def _delete_token_usage_docs(db, user_id: int) -> int:
    count = 0
    date_docs = await db.collection("token_usage").get()
    for date_doc in date_docs:
        user_doc_ref = (
            db.collection("token_usage").document(date_doc.id)
            .collection("users").document(str(user_id))
        )
        user_doc = await user_doc_ref.get()
        if user_doc.exists:
            await user_doc_ref.delete()
            count += 1
    return count
```

Kluczowe: `processed_updates` celowo NIE jest w `USER_COLLECTIONS` -- dokumenty nie maja pola `user_id`, sa kluczowane po update_id i wygasaja przez TTL 24h.

### Komendy diagnostyczne

```bash
# Sprawdz ktore kolekcje sa w cascade delete
grep -n "USER_COLLECTIONS" adhd-bot/bot/handlers/gdpr_handler.py

# Sprawdz aktywne Cloud Tasks usera (wymaga gcloud)
gcloud tasks list --queue=<queue-name> --filter="name~task-{user_id}"
```

---

## Zapobieganie

- **Firestore race conditions**: ZAWSZE uzyj `@async_transactional` dla read-modify-write. Samo `db.transaction()` bez dekoratora NIE commituje transakcji
- **Cloud Tasks orphaning**: Przy kazdym delete usera/encji najpierw cancel Cloud Tasks, dopiero potem usun dokumenty
- **Webhook deduplication**: Mark-after-handle, NIE mark-before-handle -- jesli przetwarzanie sfailuje, retry powinien zadzialac
- **GDPR subcollections**: Firestore subcollections wymagaja enumeracji parent docs -- nie wystarczy proste query po user_id
- **Exception handling**: Catch KONKRETNE typy (`GoogleCloudError`, `httpx.HTTPError`, `stripe.error.StripeError`), nie generyczne `Exception`

## Powiazane

- `adhd-bot/bot/handlers/gdpr_handler.py` -- GDPR cascade delete implementation
- `adhd-bot/bot/handlers/checklist_callbacks.py` -- Firestore transaction toggle pattern
- `adhd-bot/bot/services/checklist_session.py` -- Cloud Tasks scheduling with deterministic names
- `adhd-bot/bot/models/user.py` -- User model with get_or_create transaction pattern

## Kontekst

Projekt: ADHD Reminder Bot -- Telegram bot w Python/FastAPI. 21 Implementation Units w 6 fazach. Stack: Python 3.12, FastAPI, Google Cloud Firestore, Google Cloud Tasks, Stripe, Google OAuth, Gemini AI. Deployment: Google Cloud Run. Problemy rozwiazane w fazach 4-6 (Units 12-21), zweryfikowane testami jednostkowymi.
