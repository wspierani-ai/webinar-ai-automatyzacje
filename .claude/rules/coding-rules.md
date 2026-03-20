## 1. Rozmiar plików i funkcji

### Reguły

- Plik > 300 linii = refaktoruj. Podziel na mniejsze moduły
- Funkcja > 50 linii = wyciągnij pod-funkcje. Jedna funkcja = jeden poziom abstrakcji
- Funkcja > 6 argumentów = stwórz obiekt konfiguracyjny / interfejs
- Nesting > 2 poziomy = użyj early return
- Klasa > 1 odpowiedzialność = podziel (Single Responsibility Principle)

### Dlaczego to ważne dla AI

AI ma tendencję do tworzenia "God functions" — wrzuca całą logikę w jedną funkcję bo tak jest prościej wygenerować. Bez limitu pliki rosną do 500+ linii, gdzie AI traci kontekst i zaczyna duplikować logikę. Modele LLM generują lepszy kod kiedy operują na mniejszych, dobrze zdefiniowanych jednostkach.

---

## 2. Testowanie

### Reguły

- NIGDY nie modyfikuj istniejących testów żeby "naprawić" failing test — napraw implementację
- NIGDY nie usuwaj testów, chyba że usuwasz testowaną funkcjonalność
- NIGDY nie osłabiaj asercji (np. `toBe(429)` na `toBeDefined()`) — to nie jest fix
- NIGDY nie mockuj tego co testujesz — mockuj TYLKO zewnętrzne serwisy
- Każdy test MUSI mieć minimum 1 asercję — zero assertion-free testów
- Każda nowa funkcja = minimum 1 test happy path + 1 test error case
- Po napisaniu kodu uruchom testy PRZED deklaracją "gotowe"
- Nie ładuj pełnych datasetów w unit testach — używaj fixtures w `tests/fixtures/`
- Pattern: Arrange-Act-Assert wewnątrz describe/it bloków
- Testuj ZACHOWANIE (behavior), nie implementację (internal state)

### Dlaczego to ważne dla AI

To jest #1 failure mode AI. Udokumentowane w badaniu 275 testów: agent osłabia asercje, obniża threshold pokrycia, tworzy testy bez asercji (assertion-free), i modyfikuje swoje własne reguły governance żeby obejść ograniczenia. AI optymalizuje pod "zielone testy", nie pod "poprawny kod". Bez tych reguł AI będzie:
- Zmieniać `expect(result).toBe(429)` na `expect(result).toBeDefined()` żeby test przeszedł
- Usuwać "flaky" testy zamiast naprawiać kod
- Assignować wyniki do blank identifier (`_`) — coverage rośnie, weryfikacja = zero
- Obniżać threshold coverage kiedy nie może go osiągnąć

---

## 3. Organizacja kodu

### Reguły

- Jedna odpowiedzialność per moduł/klasa/funkcja
- Kolokacja: testy obok plików źródłowych, nie w osobnym drzewie
- Wyciągaj shared logic do dedykowanego modułu zamiast duplikować
- Nie twórz abstrakcji "na przyszłość" — abstrakcja dopiero gdy jest 2+ użycia
- Nie twórz konfiguracji dla wartości które nigdy się nie zmienią
- Importy: grouped (stdlib, third-party, local), sorted alphabetically
- Jeden eksport per plik dla głównych modułów

### Dlaczego to ważne dla AI

AI ma dwa przeciwstawne anty-patterny:
1. **Over-specification** — implementuje scenariusze które nie istnieją w wymaganiach (np. dodaje OAuth gdy nikt o to nie prosił), tworzy abstrakcje dla jednej implementacji
2. **Context blindness** — w długich sesjach duplikuje logikę, tworzy niespójne implementacje między plikami, bo "zapomniało" co już napisało

---

## 4. Error handling

### Reguły

- NIGDY nie łap wyjątków i nie ignoruj ich (empty catch block)
- NIGDY nie używaj pustego `catch {}` — zawsze loguj albo re-throw
- Rzucaj typed errors, nie string messages (`throw new AppError(...)`, nie `throw "coś poszło nie tak"`)
- Fail fast — waliduj inputy na początku funkcji
- Nie over-catchuj — łap KONKRETNE typy błędów, nie generyczne `Error`
- API routes: ustandaryzowany format odpowiedzi `{ data, error: { code, message } }`
- Używaj structured logging (JSON format, np. pino), nie `console.log`
- Nie suppressuj błędów — finding zawsze wymaga naprawy, nie racjonalizacji

### Dlaczego to ważne dla AI

AI domyślnie generuje defensywny kod z try/catch na każdym poziomie. Problem: błędy są "połykane" w środkowych warstwach i nigdy nie docierają do poziomu gdzie mogą być obsłużone. Drugi problem: AI racjonalizuje błędy jako "pre-existing" albo "acceptable" zamiast je naprawiać.

---

## 5. Anty-patterny specyficzne dla AI

### Reguły (zapobieganie)

- Nie zakładaj że biblioteka jest dostępna — sprawdź package.json / cargo.toml / requirements.txt PRZED użyciem
- Nie dodawaj importów które nie są używane
- Nie twórz "defensive code" na scenariusze które nie mogą wystąpić
- Nie rób refaktoryzacji 160 plików na podstawie vague comment — PYTAJ o potwierdzenie
- Nie modyfikuj swoich własnych reguł / review scripts / hooks
- Kiedy test failuje — napraw KOD, nie test
- Kiedy linter failuje — napraw KOD, nie konfigurację lintera
- Nie obchodź blokad przez zmianę narzędzia (Edit zablokowany, więc sed, python -c)
- Nie podejmuj autonomous decisions przy niejasnych instrukcjach — PYTAJ
- Nie dismissuj findings jako "pre-existing" — napraw albo zgłoś

### Katalog 10 udokumentowanych anty-patternów AI

| # | Anty-pattern | Częstość | Opis |
|---|-------------|----------|------|
| 1 | Over-specification | 80-90% | Implementuje funkcje których nikt nie żądał |
| 2 | Test weakening | Wysoka | Osłabia asercje żeby testy przeszły |
| 3 | Silent threshold change | Wysoka | Obniża coverage/quality targets zamiast naprawiać kod |
| 4 | Governance bypass | Średnia | Znajduje luki we własnych regułach |
| 5 | Schema regression | Średnia | Robi masowe refaktoryzacje bez potwierdzenia |
| 6 | Assertion-free tests | Wysoka | Pisze testy bez asercji — coverage rośnie, weryfikacja = 0 |
| 7 | Finding dismissal | Wysoka | "To jest pre-existing code" zamiast naprawy |
| 8 | Tool-switching circumvention | Średnia | Edit zablokowany, więc próbuje sed/echo/python -c |
| 9 | Context blindness | Wysoka w długich sesjach | Duplikuje logikę, niespójne nazewnictwo |
| 10 | Defensive over-engineering | 80-90% | Dodaje konfiguracje, abstrakcje, error handling dla scenariuszy które nie istnieją |

---

## 6. Self-check / Code review

### Reguły

- Po zakończeniu zmian ZAWSZE uruchom: typecheck, test, lint (w tej kolejności)
- Przed commitem sprawdź czy nie dodajesz: secrets, .env, console.log, TODO/FIXME
- Sprawdź czy każdy nowy plik ma odpowiadający test
- Sprawdź czy nie duplikujesz istniejącej logiki — grep codebase
- Sprawdź dead code — usuwaj nieużywane importy, zmienne, funkcje
- Sprawdź magic numbers — wyciągnij do named constants
- Sprawdź deep nesting — max 2 poziomy, powyżej = early return
- Nie committuj zmian chyba że user explicite o to poprosi

### Quality gate (pre-commit checklist)

1. Wszystkie testy przechodzą
2. Zero błędów typecheckera
3. Zero błędów lintera
4. Brak nowych `any` types
5. Brak hardcoded secrets/keys
6. Brak console.log w produkcyjnym kodzie
7. Każda nowa funkcja publiczna ma test

---

## 7. Nazewnictwo

### Reguły

- Boolean: prefix `is` / `has` / `should` / `can` (`isActive`, `hasPermission`, `shouldRetry`)
- Event handlers: prefix `handle` (`handleClick`, `handleSubmit`)
- Stałe: `UPPER_SNAKE_CASE`
- Typy/Interfejsy: `PascalCase`, bez prefixu `I`
- Funkcje i zmienne: `camelCase`
- Pliki: kebab-case (`user-service.ts`, nie `UserService.ts`) — chyba że framework wymusza inną konwencję
- Nazwy powinny opisywać CO robi, nie JAK (`getUserById`, nie `fetchAndParseAndValidateUser`)
- Unikaj akronimów i skrótów chyba że powszechnie znane (`url`, `id` OK; `usrMgr` nie)

### Dlaczego to ważne dla AI

AI ma tendencję do niespójnego nazewnictwa w obrębie jednej sesji (context blindness). Przy generowaniu nowych plików używa losowych konwencji jeśli nie dostanie jasnych reguł. Explicit naming rules = spójność.

---

## 8. Zależności i importy

### Reguły

- NIGDY nie zakładaj że biblioteka jest dostępna — sprawdź package.json / requirements.txt / go.mod
- NIGDY nie instaluj nowych zależności bez poinformowania usera
- Preferuj istniejące biblioteki w projekcie > nowa dependency
- Nie mieszaj package managerów (jeśli projekt używa `bun` — nie używaj `npm`)
- Importy grouped: stdlib, third-party, local
- Nie importuj bezpośrednio między packages w monorepo — używaj shared layer
- Pinuj wersje — deklaruj exact versions w package.json

### Dlaczego to ważne dla AI

AI ma tendencję do dodawania bibliotek które zna z treningu, ignorując co jest już w projekcie. Klasyczny case: dodaje `lodash` dla jednej utility function, albo `axios` kiedy projekt używa natywnego `fetch`.

---

## 9. Bezpieczeństwo

### Reguły

- NIGDY nie committuj secrets, API keys, credentials, tokenów
- NIGDY nie loguj secrets ani danych osobowych
- NIGDY nie konkatenuj user input do SQL queries — używaj parametrized queries
- NIGDY nie używaj dynamicznego wykonywania kodu z user input
- NIGDY nie deserializuj niezaufanych danych z zewnętrznych źródeł
- Waliduj KAŻDY input na granicy API (Zod, Pydantic, etc.)
- Minimum privileges — nie dawaj więcej uprawnień niż potrzeba
- Nie uruchamiaj `rm -rf` bez explicit user confirmation
- Nie modyfikuj production database bezpośrednio
- Rate limiting na KAŻDYM public endpoint

### Dlaczego to ważne dla AI

AI nie ma awareness bezpieczeństwa — wygeneruje working code który jest vulnerable. Bez explicit reguł: skonkatenuje SQL, zaloguje API key, sklepi shell command ze stringa. To nie jest edge case — to domyślne zachowanie.

---

## 10. Type safety

### Reguły

- NIGDY nie używaj `any` — użyj `unknown` z type guards albo zdefiniuj interfejs
- NIGDY nie używaj type assertions (`as`) chyba że konieczne dla DOM narrowing
- NIGDY nie używaj non-null assertions (`!`) — obsłuż nullability explicite
- Użyj discriminated unions dla stanu, nie boolean flags
- Wszystkie publiczne funkcje mają explicit return types
- Strict mode ON — `"strict": true` w tsconfig
- Generics > type assertions
- Zod/io-ts na granicach systemu (API, pliki, user input)

### Dlaczego to ważne dla AI

AI generuje kod który "kompiluje się" ale nie jest type-safe. Najczęstsza ucieczka: `as any`, `as unknown as SomeType`, `!` non-null assertion. To przechodzi typecheck ale wybucha w runtime. Explicit prohibition na `any` wymusza pisanie prawdziwych typów.

---

## 11. Filozofia review kodu

### Reguły

- Istniejący kod — bądź surowy. Każda dodana złożoność wymaga uzasadnienia
- Nowy izolowany kod — bądź pragmatyczny. Jeśli działa i jest testowalny, nie blokuj postępu
- Duplication > Complexity — prosta duplikacja kodu jest LEPSZA niż złożona abstrakcja DRY
- Dodanie nowego modułu nie jest nigdy problemem. Zrobienie modułu zbyt złożonym — jest
- Przy modyfikacji istniejącego pliku pytaj: "Czy ta zmiana sprawia, że istniejący kod jest trudniejszy do zrozumienia?"
- Preferuj ekstrakcję do nowego modułu/komponentu zamiast komplikowania istniejącego
- 5-sekundowa reguła nazewnictwa — jeśli nie rozumiesz co robi funkcja/komponent w 5 sekund od nazwy, to zła nazwa

### Dlaczego to ważne dla AI

AI optymalizuje pod "rozwiąż problem jednym strzałem". Efekt: dodaje logikę do istniejących plików zamiast tworzyć nowe moduły, bo jest prościej wygenerować jeden duży plik niż kilka małych. Bez explicite zasady "duplication > complexity" AI tworzy coraz bardziej złożone abstrakcje zamiast prostych kopii.

---

## 12. Performance

### Reguły

- O(n²) lub gorzej = wymaga uzasadnienia komentarzem dlaczego nie da się lepiej
- Pętla z fetchem/zapytaniem do bazy = N+1 query. Użyj batch/join/include
- Nie ładuj pełnych kolekcji gdy potrzebujesz subset — użyj pagination, limit, select konkretnych kolumn
- Nowa dependency = uzasadnienie rozmiaru bundle (sprawdź bundlephobia)
- Dynamic import / React.lazy() dla komponentów > 50KB
- Nie optymalizuj przedwcześnie — ale MIERZ przed deklaracją "to wystarczy"

### Dlaczego to ważne dla AI

AI nie myśli o skali. Wygeneruje kod który działa na 10 rekordach ale crashuje na 10000. Typowe: nested loop w pętli, select("*") na tabelach z 50 kolumnami, fetch w map(). AI nie sprawdza bundlephobia — doda bibliotekę 200KB dla jednej utility function.

---

## 13. Async i race conditions

### Reguły

- useEffect z async = ZAWSZE AbortController w cleanup function
- setTimeout / setInterval = ZAWSZE cleanup w useEffect return (clearTimeout/clearInterval)
- Więcej niż 1 boolean do stanu ładowania = użyj state machine (discriminated union)
- Promise.allSettled gdy odpalasz równoległe operacje które mogą niezależnie failować
- Promise.finally() do cleanup i state transitions — nie duplikuj logiki w resolve i reject
- requestAnimationFrame w pętli = sprawdź cancel flag przed kolejnym requestAnimationFrame
- Operacje wzajemnie wykluczające się (np. load preview) = zablokuj następną dopóki poprzednia się nie zakończy lub nie sfailuje

### Dlaczego to ważne dla AI

AI generuje "happy path" async kodu. Nie myśli o: co jeśli komponent się odmontuje w trakcie fetcha? Co jeśli user kliknie 5 razy zanim pierwszy request się skończy? Co jeśli timeout wykona się na DOM który już nie istnieje? Bez explicit reguł AI nigdy nie doda AbortController, nigdy nie doda cleanup w useEffect return.

---

## 14. Architektura

### Reguły

- Zero circular dependencies między modułami — jeśli A importuje B, B nie może importować A
- Respect layer boundaries — komponent UI nie woła bazy bezpośrednio, idzie przez serwis/hook
- Single Responsibility dotyczy też plików — plik z komponentem nie zawiera logiki biznesowej
- API contracts (interfejsy, typy propsów) są stabilne — zmiana interfejsu = świadoma decyzja, nie side-effect refaktoru
- Nowa zależność między modułami = pytanie: "czy to nie tworzy nieodwracalnego couplingu?"

### Dlaczego to ważne dla AI

AI nie widzi "big picture" architektury. Importuje co potrzebuje bez sprawdzania czy tworzy cykl. Wkleja logikę bazy do komponentu bo "tak szybciej". W dłuższych sesjach zaczyna łączyć moduły które powinny być niezależne. Bez explicit boundary rules codebase konwerguje do "big ball of mud".