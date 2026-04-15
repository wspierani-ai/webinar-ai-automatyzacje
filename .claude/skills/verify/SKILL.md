---
name: verify
description: Uruchamia pełną weryfikację projektu adhd-bot — linting ruff, testy pytest. Używaj przed oznaczeniem zadania jako gotowe lub przed commitem.
---

Uruchom weryfikację projektu w następującej kolejności:

1. **Linting** — sprawdź błędy stylu i jakości kodu:
   ```bash
   ruff check adhd-bot/
   ```

2. **Testy** — uruchom pełny suite testów:
   ```bash
   pytest adhd-bot/tests/ -v
   ```

Jeśli którykolwiek krok zakończy się błędem:
- Nie kontynuuj do następnego kroku
- Pokaż użytkownikowi błędy
- Zaproponuj konkretne naprawy (naprawiaj kod, nie testy ani konfigurację lintera)

Jeśli wszystko przejdzie pomyślnie, raportuj: "✓ ruff OK, ✓ pytest OK — gotowe do commita".
