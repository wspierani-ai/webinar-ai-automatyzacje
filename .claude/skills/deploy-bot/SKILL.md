---
name: deploy-bot
description: Deployuje adhd-bot na GCP Cloud Run (europe-central2). Tylko użytkownik może wywołać ten skill — ma efekty uboczne w środowisku produkcyjnym.
disable-model-invocation: true
---

Wdraża adhd-bot na GCP Cloud Run.

Przed deployem upewnij się, że:
1. Testy i linting przeszły (`/verify`)
2. Jesteś na właściwym branchu
3. Masz uprawnienia `gcloud` do projektu

Komenda deploymentu:
```bash
gcloud run deploy adhd-bot \
  --source adhd-bot/ \
  --region europe-central2 \
  --min-instances 1 \
  --platform managed
```

Po udanym deploymencie:
- Sprawdź health check: `GET https://<cloud-run-url>/health`
- Zweryfikuj webhook Telegrama jest zarejestrowany na nowym URL

Jeśli `$ARGUMENTS` zawiera `--dry-run`, tylko wyświetl komendę bez wykonania.
