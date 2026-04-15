---
date: 2026-04-09
topic: adhd-reminder-bot
---

# ADHD Reminder Bot — Telegram

## Problem

ADHD-owcy płacą „podatek od ADHD" w czasie i pieniądzach: zapominają o zadaniach, nie mogą zainicjować działania i tracą kontekst przy przerwaniu. Istniejące narzędzia zawodzą z dwóch powodów: wymagają za dużo kroków przy capture i wymagają regularnego utrzymania systemu — czego ADHD-owcy nie robią.

## Wymagania

- R1. Użytkownik wysyła wiadomość tekstową lub głosową do bota w Telegram — to jedyna wymagana akcja do zapisania zadania.
- R2. Bot parsuje wiadomość i wyciąga: treść zadania oraz czas remindera (jeśli podany, np. „jutro o 17", „za 2 godziny").
- R3. Jeśli użytkownik nie podał czasu, bot proponuje czas automatycznie i pokazuje inline przyciski: `[✓ OK] [Zmień]` — user potwierdza jednym tapem.
- R4. Bot wysyła reminder w ustalonym czasie — wiadomość zawiera oryginalny kontekst zadania.
- R5. Z poziomu remindera użytkownik może jednym tapem: `[+30 min] [+2h] [Jutro rano]` (snooze) lub `[✓ Zrobione] [✗ Odrzuć]`.
- R6. System nie wymaga żadnego utrzymania — zadania ukończone i przeterminowane są archiwizowane przez 30 dni, potem kasowane automatycznie.
- R7. Wiadomości głosowe są transkrybowane i przetwarzane identycznie jak tekstowe.
- R8. Jeśli user nie zareaguje na reminder przez 1h, bot wysyła jeden gentle nudge z treścią zadania.
- R9. Przy pierwszym użyciu opcji „Jutro rano" bot pyta o preferowaną godzinę poranną i zapamiętuje ją.
- R10. Po 7-dniowym free trial wymagana subskrypcja 29.99 PLN/mies. przez Stripe. Przy nieudanej płatności 3-dniowy grace period z przypomnieniem w bocie, potem blokada.
- R11. Integracja z Google Calendar — jednostronna sync (bot → Calendar): bot tworzy event w kalendarzu gdy reminder jest ustawiany; snooze aktualizuje czas eventu; ukończenie/odrzucenie w bocie aktualizuje event w kalendarzu. Integracja opcjonalna (user łączy konto przez /connect-google). Dwukierunkowa sync (GCal → bot) odłożona do v2.
- R12. Integracja z Google Tasks — bot tworzy task w Google Tasks gdy reminder jest ustawiany; ukończenie taska w bocie oznacza Google Task jako done; zmiany w Google Tasks (ukończenie) synchronizowane do bota przez polling co 5 minut.
- R13. Admin dashboard (web) dostępny przez przeglądarkę: lista wszystkich klientów z ich statusem subskrypcji (trial/active/grace_period/blocked), datą końca subskrypcji, zużyciem tokenów Gemini (koszt w PLN), aktywnością (liczba tasków, ostatnia aktywność), przychodami (MRR, ARR, churn rate, trial conversions).
- R14. Multi-user admin access: dostęp przez Google SSO (email whitelist), role admin (pełny dostęp) i read-only (podgląd bez edycji). Audit log każdej akcji admina.
- R15. Security hardening: szyfrowanie wrażliwych danych w Firestore (Google refresh tokens, dane osobowe) przez Cloud KMS; wszystkie sekrety w Secret Manager; rate limiting na wszystkich endpointach; security headers (HSTS, CSP, X-Frame-Options); CORS restriction; input validation na granicy API.
- R16. RODO/GDPR compliance: komenda `/delete_my_data` kasująca wszystkie dane usera z Firestore (user document, tasks, token_usage, checklist_templates, checklist_sessions); statyczna strona z polityką prywatności dostępna pod publicznym URL; podstawa prawna przetwarzania danych opisana w polityce.
- R17. Checklista — szablony wielokrotnego użytku: user tworzy szablon przez `/new_checklist` lub gdy bot wykryje event wymagający przygotowania; AI (Gemini) sugeruje itemy przy tworzeniu; max 12 itemów per szablon; szablon edytowalny przez `/checklists`; bot pyta o zapisanie szablonu po pierwszym użyciu.
- R18. Checklista — flow reminderów: dwa przypomnienia — wieczorne (domyślnie 21:00, konfigurowalne przez `/evening`) dnia poprzedniego i poranne (godzina z `/morning`) w dniu eventu; poranne pokazuje tylko nieodznaczone itemy; każdy item to osobny inline button `[✓ Item]`; odznaczenie ostatniego → auto-zamknięcie z komunikatem gratulacyjnym; snooze całej listy identyczny jak przy zwykłym reminderze.
- R19. Checklista — wykrywanie: Gemini klasyfikuje typ taska; przy eventach wymagających przygotowania (wyjście, podróż, trening, spotkanie) bot pyta "czy coś zabrać?"; gdy istnieje pasujący szablon — bot bezpośrednio proponuje jego użycie; godzina wieczornego remindera globalna dla wszystkich szablonów (`/evening`).

## Onboarding

- Jeden link `t.me/nazwabot` — user wysyła pierwszą wiadomość, bot auto-konfiguruje.
- Bot pyta o strefę czasową w pierwszej wiadomości; domyślnie Europe/Warsaw.
- Komenda `/timezone` do zmiany strefy czasowej w dowolnym momencie.
- Komenda `/morning` do zmiany godziny „Jutro rano" (ustawiana też automatycznie przy pierwszym użyciu).

## Stack techniczny

- **Platforma:** Telegram Bot API
- **AI:** Gemini 2.5 Flash (parsowanie tekstu + transkrypcja głosu w jednym request; GA od kwietnia 2026)
- **Infrastruktura:** GCP — Cloud Run (bot), Cloud Tasks (scheduler reminderów), Vertex AI (Gemini)
- **Baza danych:** Firestore
- **Region:** europe-central2 (Warsaw)
- **Płatności:** Stripe (PLN, subskrypcja miesięczna)
- **Język bota:** Polski

## Kryteria sukcesu

- Capture trwa mniej niż 5 sekund od pojawienia się myśli.
- Użytkownik nie musi otwierać żadnej osobnej aplikacji — wszystko dzieje się w Telegram.
- Po tygodniu użytkowania system nie wymaga żadnego ręcznego porządkowania ani kategoryzowania.

## Granice scope'u

- Brak natywnej aplikacji mobilnej/desktopowej.
- Brak integracji z mailem ani innymi zewnętrznymi źródłami (poza Google Calendar i Google Tasks).
- Brak webowego dashboardu.
- Brak WhatsApp — tylko Telegram.
- Brak funkcji społecznościowych (accountability partner, body double).
- Brak wykrywania „implied commitments" — user musi aktywnie wysłać zadanie.
- Tylko język polski w MVP.
- Brak limitu liczby zadań (płatność jest bramką, nie limit funkcji).

## Kluczowe decyzje

- **Gemini 2.0 Flash zamiast GPT-4o-mini**: 3x tańszy, głos wbudowany bez osobnego API, natywna integracja z GCP.
- **GCP zamiast AWS**: natywna integracja z Gemini/Vertex AI, region Warsaw, jeden ekosystem.
- **Firestore**: zero administracji, serverless, idealny dla dokumentowej struktury zadań.
- **Płatny od dnia 1 (7-dniowy trial)**: ADHD-owcy płacą za narzędzia które działają — trial daje czas na poczucie wartości.
- **29.99 PLN/mies.**: sweet spot dla polskiego rynku — poniżej progu "muszę się zastanowić".
- **Stripe**: najlepsze API do subskrypcji, obsługuje PLN, łatwa integracja z Cloud Run.
- **Grace period 3 dni**: ADHD-owiec mógł zapomnieć zaktualizować kartę — twarde odcięcie to antywzorzec dla tej grupy.

## Następne kroki

→ `/dev-plan` do planowania technicznego implementacji
