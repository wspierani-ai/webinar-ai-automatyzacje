---
name: skill-rules-manager
description: "Audyt i synchronizacja skill-rules.json z istniejącymi skillami. Wykrywa brakujące wpisy, martwe referencje, problemy z keywords. Uruchamiaj po dodaniu/usunięciu skilli."
disable-model-invocation: true
---

# Skill Rules Manager

Po załadowaniu tego skilla wykonaj poniższy audyt automatycznie, bez pytania użytkownika.

## Procedura audytu

### Krok 1: Inwentaryzacja skilli

Przeskanuj `.claude/skills/*/SKILL.md` — to są istniejące skille w projekcie.
Przeczytaj `.claude/skills/skill-rules.json` — to jest konfiguracja auto-aktywacji.

Porównaj oba źródła i zidentyfikuj:

1. **Skille bez wpisu w skill-rules.json** — istnieją w katalogu `skills/`, ale nie mają triggera w `skill-rules.json`. Mogą potrzebować auto-aktywacji.
2. **Martwe wpisy w skill-rules.json** — referencje do skilli, które nie istnieją jako pliki.
3. **Skille meta/narzędziowe** — np. ten skill (`skill-rules-manager`). Te NIE powinny być w `skill-rules.json` — są wywoływane ręcznie.

### Krok 2: Analiza keywords

Dla każdego skilla w `skill-rules.json` sprawdź:

1. **Zbyt ogólne keywords** — słowa jak `"error"`, `"form"`, `"hook"`, `"modal"`, `"menu"`, `"style"`, `"component"` triggerują się na zbyt wielu promptach. Zasugeruj bardziej specyficzne zamienniki.
2. **Brakujące keywords** — przeczytaj `SKILL.md` danego skilla i sprawdź, czy kluczowe terminy z jego treści są pokryte w keywords/intentPatterns.
3. **Duplikaty między skillami** — ten sam keyword w wielu skillach powoduje, że wszystkie się aktywują jednocześnie.

### Krok 3: Walidacja techniczna

1. Sprawdź czy `skill-rules.json` jest poprawnym JSON-em: `jq . .claude/skills/skill-rules.json`
2. Sprawdź czy hook istnieje: `.claude/hooks/skill-activation-prompt.sh`
3. Sprawdź czy hook jest zarejestrowany w `.claude/settings.json` pod `UserPromptSubmit`

### Krok 4: Raport i akcje

Wyświetl raport w formacie:

```
## Audyt skill-rules.json

### Skille bez auto-aktywacji
- nazwa-skilla — [sugestia: dodać / pominąć (meta-skill)]

### Martwe wpisy
- nazwa-wpisu — skill nie istnieje, usunąć

### Problemy z keywords
- skill-x: "error" zbyt ogólne → zasugeruj zamiennik
- skill-y: brakuje keyword "termin-z"

### Duplikaty keywords
- "keyword" → skill-a, skill-b

### Walidacja techniczna
- JSON: OK/BŁĄD
- Hook: OK/BRAK
- Rejestracja: OK/BRAK
```

Po wyświetleniu raportu **zapytaj użytkownika**: "Czy chcesz, żebym naprawił znalezione problemy?"

Jeśli tak — napraw automatycznie:
- Dodaj brakujące wpisy do `skill-rules.json` (z rozsądnymi keywords z SKILL.md)
- Usuń martwe wpisy
- Popraw zbyt ogólne keywords

## Zasady doboru keywords

**Dobre keywords:**
- Specyficzne terminy: `"supabase"`, `"shadcn"`, `"captureException"`
- Frazy wielowyrazowe: `"error tracking"`, `"baza danych"`, `"edge function"`
- Unikalne dla domeny: `"polityka rls"`, `"framer motion"`

**Złe keywords:**
- Jednowyrazowe ogólne: `"error"`, `"form"`, `"hook"`, `"modal"`, `"style"`
- Triggerują fałszywe dopasowania

## Schemat wpisu w skill-rules.json

```json
"nazwa-skilla": {
  "type": "domain",
  "enforcement": "suggest",
  "priority": "high",
  "description": "Krótki opis",
  "promptTriggers": {
    "keywords": ["specyficzny keyword", "fraza wielowyrazowa"],
    "intentPatterns": ["(create|dodaj).*?(komponent|component)"]
  }
}
```

## Konwencje

- Hook `skill-activation-prompt.sh` to czysty bash + jq
- stdout z exit 0 → kontekst dla Claude (specyfika UserPromptSubmit)
- Restart sesji wymagany po zmianach w hookach
- Meta-skille (jak ten) NIE wchodzą do skill-rules.json
