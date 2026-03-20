# Przegląd Planu — Materiały referencyjne

Materiały uzupełniające dla agenta koordynatora skilla plan-review.

## Perspektywy VP

| Rola VP | Obszary fokusowe | Kluczowe pytania |
|---------|-----------------|------------------|
| **VP Product** | Wpływ na użytkownika, pełzanie zakresu, zależności, harmonogramy | Czy to dostarcza wartość? Czy wymagania są jasne? |
| **VP Engineering** | Dług techniczny, anty-wzorce, konflikty architektoniczne, regresje | Czy to jest utrzymywalne? Co może się zepsuć? |
| **VP Design** | Spójność UX, dostępność, zgodność z design systemem | Czy pasuje do naszych wzorców? Czy jest intuicyjne? |

## Kategorie problemów

### Blokery
Problemy uniemożliwiające kontynuację planu:
- Brakujące zależności lub warunki wstępne
- Nierozwiązane konflikty architektoniczne
- Luki bezpieczeństwa
- Breaking changes bez ścieżki migracji

### Anty-wzorce
Podejścia projektowe lub implementacyjne powodujące długoterminowe problemy:
- Ścisłe sprzężenie między modułami
- God objects lub nadmiernie złożone klasy
- Przedwczesna optymalizacja
- Brakujące abstrakcje

### Potencjalne konflikty
Obszary, w których plan może kolidować z istniejącymi pracami:
- Nakładający się zakres funkcjonalności z innymi inicjatywami
- Konflikty schematów bazy danych
- Zmiany kontraktów API wpływające na konsumentów
- Rywalizacja o współdzielone zasoby

### Regresje
Zmiany mogące zepsuć istniejącą funkcjonalność:
- Zmiany zachowania w publicznych API
- Degradacja wydajności
- Usunięte lub zdeprecjonowane funkcje nadal w użyciu
- Luki w pokryciu testami

## Przewodnik ważności

| Ważność | Kryteria | Wymagane działanie |
|---------|----------|-------------------|
| **Krytyczny** | Blokuje wykonanie, ryzyko bezpieczeństwa, utrata danych | Musi być rozwiązany przed kontynuacją |
| **Wysoki** | Duży wpływ, psuje istniejącą funkcjonalność | Powinien być rozwiązany przed kontynuacją |
| **Średni** | Problem jakościowy, dług techniczny | Rozwiąż w tej iteracji |
| **Niski** | Drobne ulepszenie, nice-to-have | Rozwiąż jeśli czas pozwoli |

## Szablony promptów agentów VP

### VP Product

```
Jako VP Product, przejrzyj ten plan pod kątem:
- Jasności wartości i wpływu na użytkownika
- Ryzyka pełzania zakresu
- Brakujących wymagań lub edge case'ów
- Wykonalności harmonogramu
- Ryzyka zależności

Plan:
[TREŚĆ_PLANU]

Zwróć wyniki jako ustrukturyzowaną listę:
- Ważność: [Krytyczny|Wysoki|Średni|Niski]
  Kategoria: [Bloker|Zakres|Konflikt]
  Opis: [<240 znaków]
  Kompromisy: [Opcja A vs Opcja B]
  Rekomendacja: [działanie]
```

### VP Engineering

```
Jako VP Engineering, przejrzyj ten plan pod kątem:
- Wprowadzania długu technicznego
- Anty-wzorców i code smells
- Konfliktów architektonicznych z istniejącymi systemami
- Ryzyka regresji
- Implikacji wydajnościowych
- Problemów bezpieczeństwa

Plan:
[TREŚĆ_PLANU]

Zwróć wyniki jako ustrukturyzowaną listę:
- Ważność: [Krytyczny|Wysoki|Średni|Niski]
  Kategoria: [Bloker|Anty-wzorzec|Konflikt|Regresja]
  Opis: [<240 znaków]
  Kompromisy: [Opcja A vs Opcja B]
  Rekomendacja: [działanie]
```

### VP Design

```
Jako VP Design, przejrzyj ten plan pod kątem:
- Spójności UX z istniejącymi wzorcami
- Problemów dostępności (WCAG 2.2)
- Zgodności z design systemem
- Jasności flow użytkownika
- Problemów hierarchii wizualnej

Plan:
[TREŚĆ_PLANU]

Zwróć wyniki jako ustrukturyzowaną listę:
- Ważność: [Krytyczny|Wysoki|Średni|Niski]
  Kategoria: [Wzorzec|UX|Konflikt]
  Opis: [<240 znaków]
  Kompromisy: [Opcja A vs Opcja B]
  Rekomendacja: [działanie]
```

## Przykładowy output

### Problemy krytyczne (2)

| # | VP | Kategoria | Problem | Kompromisy | Rekomendacja |
|---|----|-----------|---------|-----------:|--------------|
| 1 | Eng | Bezpieczeństwo | Brak rate limitingu na odświeżaniu tokenów | A: Dodaj rate limit (2h) vs B: Ryzyko nadużyć | Dodaj rate limit (Opcja A) |
| 2 | Product | Bloker | Zależność od serwisu v2.1 jeszcze niewdrożonego | A: Czekaj vs B: Mockuj | Skoordynuj timing wdrożenia |

### Wszystkie problemy (7 łącznie)

| # | VP | Ważność | Kategoria | Problem (<240 znaków) |
|---|----|---------|-----------|----------------------|
| 1 | Eng | Krytyczny | Bezpieczeństwo | Endpoint odświeżania tokenów nie ma rate limitingu |
| 2 | Product | Krytyczny | Bloker | Zależność od serwisu v2.1 niewdrożona, blokuje testy |
| 3 | Eng | Wysoki | Anty-wzorzec | Sekret JWT w kodzie, powinien być w zmiennej środowiskowej z rotacją |
| 4 | Design | Wysoki | Wzorzec | Stany błędów logowania nie pasują do design systemu |
| 5 | Product | Średni | Zakres | Flow resetowania hasła wspomniany, ale nieokreślony |
| 6 | Eng | Średni | Regresja | Inwalidacja sesji może zepsuć aplikację mobilną |
| 7 | Design | Niski | UX | Spinner ładowania mógłby mieć wskaźnik postępu |

### Sugerowane modyfikacje planu

```
1. [Sekcja X, linia Y]: Dodaj wymaganie rate limitingu dla endpointu odświeżania tokenów
2. [Sekcja Z]: Dodaj notatkę o zależności — wymaga wdrożenia serwisu v2.1
3. [Sekcja W]: Przenieś sekret JWT do zmiennej środowiskowej, dodaj politykę rotacji
...
```
