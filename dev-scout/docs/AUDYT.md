# Audyt Dev Scout — co zmienić, żeby mieć najświeższe i najtrafniejsze leady

Stan na 22 lipca 2026, po dwóch rundach pracy: (1) wdrożenie wielosygnałowej
weryfikacji dopasowań (`src/verify.py`) + raportu Excel (`tools/report_xlsx.py`),
(2) domknięcie większości znalezisk z pierwszej rundy audytu — scoring, recheck,
cache, adres pełny, testy, poprawki Excela. Punkty ułożone od największego
wpływu. "✅ zrobione" = już w kodzie na tym branchu, reszta = rekomendacje.

---

## 1. Świeżość danych — jak mieć „najnowsze" informacje

| Co | Status | Uwagi |
|---|---|---|
| **Cykliczne uruchamianie (cron dzienny)** | ❌ nadal do zrobienia (zadanie 4 z CLAUDE.md) | RWDZ/GUNB aktualizuje plik co noc. Tego nie da się zrobić z tej sesji — to wymaga crontaba na TRWAŁEJ maszynie Adama (ten sandbox jest efemeryczny). Gotowa linia crona jest w `CLAUDE.md`. |
| **Filtr „tylko od 2024"** | ✅ zrobione | `date_filter.min_data` w config. |
| **Re-check portali co N dni** | ✅ **zrobione** — `src/main.py::step_recheck` + komenda `python -m src.main recheck` | Cofa `scored`→`new` dla leadów sprawdzonych, ale nie znalezionych (`on_portal_found` 0/NULL), starszych niż `recheck_after_days`. Leady już potwierdzone (`on_portal_found=1`) NIE są cofane — zgodnie z CLAUDE.md ("nie usuwaj leada tylko dlatego, że się pojawił"). Przetestowane na żywo: 9/20 leadów (te "czyste") poprawnie cofnięte, 11/20 (znalezione) poprawnie pozostawione. Wołać PRZED `enrich` w cyklu cron. |
| **CEIDG endpoint `/zmiana`** | do rozważenia | Bez zmian. |

---

## 2. Weryfikacja dopasowań lead↔ogłoszenie

✅ **`src/verify.py`** — geometria działki (ULDK), rynek pierwotny/wtórny, wiek
ogłoszenia vs data wniosku, metraż vs kubatura, działka vs ewidencja gruntów,
kategoria właściciela działki, seryjność inwestora. Werdykt
CONFIRMED/LIKELY/REVIEW/REJECTED + powody w `verify_json` i w kolumnie
"Uzasadnienie werdyktu" w Excelu.

**Naprawione w tej rundzie:**
- ✅ **Martwa strefa dystansu 700 m–2 km** — realny przypadek (Brwinów, 1,82 km)
  nie miał ŻADNEJ gałęzi kodu obsługującej ten zakres, sygnał geograficzny
  znikał całkowicie z powodów werdyktu. Teraz ten zakres jawnie obniża ocenę
  i zawsze zostawia powód w Excelu. Pokryte testem regresji
  (`tests/test_verify.py::test_judge_match_dubious_distance_zone_not_silently_dropped`).

**Wciąż otwarte ograniczenia (nie do rozwiązania bez dalszej pracy):**
- Gratka/Morizon/Domiporta/RynekPierwotny bez odkrytego JSON-a — regexy na
  HTML, niższa pewność niż Otodom/OLX.
- KIEG WMS czasem nie zwraca danych (na próbce 20 leadów ~4 miały
  `parcel_owner_group=None` mimo poprawnego numeru działki) — przyczyna
  nieznana, do zbadania jeśli ten sygnał ma być kluczowy.
- Kalibracja widełek kubatura→metraż (÷4.0…÷5.5) oparta o garść realnych par —
  wystarczające do wykrycia rażących rozjazdów, ale warto przeliczyć po
  zebraniu większej próby potwierdzonych dopasowań.
- Seryjność inwestora to dopasowanie tekstowe (`_investor_key` w `verify.py`)
  po znormalizowanej nazwie — literówki/nietypowe skróty nazwy spółki mogą się
  nie połączyć w jeden licznik.

---

## 3. Scoring — teraz korzysta z weryfikacji (był to największy gap)

✅ **Naprawione.** `src/scoring.py::compute_score` czyta teraz `lead_verdict`,
`investor_serial_count`, `parcel_owner_group` (przekazywane z `verify_json`
w `main.py::step_score`) i trzy nowe wagi w `config.yaml`:
- `kara_potwierdzone_na_portalu` (30 pkt, odejmowane) — werdykt CONFIRMED =
  inwestycja już się reklamuje, czyli przeciwieństwo przewagi "zanim zaczną
  marketing", która jest sensem narzędzia.
- `seryjny_inwestor` (15 pkt) — inwestor ma ≥ `verify.serial_investor_min`
  wniosków w RWDZ.
- `dzialka_spolki` (10 pkt) — właściciel działki (ewidencja gruntów) to spółka
  prawa handlowego; działa NIEZALEŻNIE od tego, czy RWDZ ma wypełnioną nazwę
  inwestora (kluczowe dla ~88% leadów bez tej nazwy).

**Uwaga, doprecyzowanie względem poprzedniej wersji audytu:** wcześniejszy
zapis "REJECTED i CONFIRMED dostają identyczny wpływ na scoring" był
nieprecyzyjny — `on_portal_found` w `main.py` już wcześniej filtrował
dopasowania REJECTED (nie liczyły się jako "znaleziono"). Prawdziwą luką był
brak rozróżnienia CONFIRMED/LIKELY/REVIEW między sobą i brak wykorzystania
`investor_serial_count`/`parcel_owner_group` — to jest teraz naprawione.

**Bonus-bug znaleziony przy wdrażaniu:** `kara_potwierdzone_na_portalu` mogła
zejść poniżej 0 (zweryfikowane na żywo: realny lead z werdyktem CONFIRMED
wyszedł ze score -5), łamiąc udokumentowaną skalę 0-100. Naprawione —
`compute_score` ma teraz `max(0, min(score, 100))`.

---

## 4. Adres pełny z RWDZ — NOWA funkcja (na życzenie Adama)

✅ RWDZ dzieli nazwę ulicy na dwie kolumny (`ulica` = człon główny/nazwisko,
`ulica_dalej` = imię/tytuł — zweryfikowane na 30 realnych przykładach, np.
`ulica="Piłsudskiego"` + `ulica_dalej="Józefa "` → pełna nazwa "Józefa
Piłsudskiego"), plus osobną kolumnę `nr_domu`. Wcześniej parser brał tylko
`ulica`, gubiąc zarówno numer domu, jak i pierwszy człon nazwy ulicy.

Teraz: `rwdz_parse.compose_street_name()` składa pełną nazwę, `numer_domu`
trafia do bazy, a `main.py::step_enrich` liczy `adres_pelny` — pełny adres
pocztowy gdy RWDZ ma ulicę+numer, samą ulicę gdy brak numeru, albo ulicę
ODZYSKANĄ z lokalizacji działki (oznaczoną jawnie jako "przybliżony") gdy RWDZ
w ogóle nie ma ulicy. Widoczne w Excelu jako kolumna "Adres (pełny)" + link do
Google Maps (kolumna "Mapa") — Adam może teraz SAM zlokalizować i zweryfikować
każdą inwestycję niezależnie od wyniku portal_check/verify.

---

## 5. Cache trwały dla zapytań sieciowych — NOWE (`src/geo_cache.py`)

✅ Tabela `geo_cache` w tej samej bazie SQLite, keyowana po numerze działki
(ULDK centroid, ULDK+KIEG ewidencja) albo po znormalizowanym adresie
(Nominatim geokodowanie, odwrotne geokodowanie). Bez tego każde ponowne
`enrich` na tych samych leadach (re-check, powtórne testy — co się w tej
sesji zdarzało wielokrotnie) odpytywało te same zewnętrzne API od nowa.
Cache'owane są tylko UDANE odpowiedzi (brak cache'owania negatywnego), żeby
chwilowa awaria/literówka w RWDZ nie blokowała leada na stałe.

---

## 6. Testy automatyczne — NOWE, pierwszy krok domknięty

✅ `tests/test_filters.py` (17 testów: dopasowanie gmin/typu zabudowy/dat,
ekstrakcja liczby budynków, kompozycja adresu, oraz **test end-to-end na
`sample_test.csv`** — parse+normalize+filter na pełnym pliku, nie tylko
pojedynczych funkcjach) + `tests/test_verify.py` (12 testów: kalibracja
kubatury, cross-check inwestora, geometria punkt-w-wielokącie, werdykty
CONFIRMED/REJECTED/REVIEW na zamockowanych `ListingFacts`, w tym regresja na
martwą strefę dystansu z punktu 2). Razem 29 testów, bez sieci, `python -m
pytest tests/ -v`.

**Naprawiony przy okazji:** `data/raw/sample_test.csv` był martwym kanarkiem —
używał separatora `#` i starych, zmyślonych nazw kolumn sprzed odkrycia
realnego formatu RWDZ, więc `run --skip-fetch` dawał 0 wierszy zamiast
udokumentowanych 4. Przepisany na realny format (`;`, prawdziwe nazwy
kolumn z `wynik_mazowieckie.csv`, w tym `ulica_dalej`/`nr_domu`), teraz 9
wierszy wejściowych → dokładnie 4 przechodzą filtry, każde z jawnym, opisanym
powodem odrzucenia pozostałych 5 (Warszawa/instalacja/rozbiórka/data
sprzed 2024/znany duży deweloper).

**Wciąż brak:** CI (`.github/workflows`) — testy trzeba uruchamiać ręcznie.
Pokrycie nie obejmuje `portal_check.py` (wymagałoby mockowania
requests/Playwright) ani `main.py::step_enrich` jako całości (integracyjne,
wymaga sieci) — to świadomy kompromis czasowy, nie przeoczenie.

---

## 7. Sprawdzanie portali — Search API główny backend

- ✅ Brave Search API priorytetowy, OLX HTTP zawsze włączony, filtr
  typu/URL konkretnego ogłoszenia.
- ⚠️ Backend browser (Playwright) nadal niezweryfikowany na żywym ruchu w tym
  środowisku (proxy blokuje Chromium) — fallback bez klucza Brave.
- **Budżet Brave** — pełne 884 leady zużyje ~88% miesięcznego limitu. Decyzja
  wciąż nierozstrzygnięta z Adamem.

---

## 8. Geokodowanie — ULDK główne źródło, teraz z cache

- ✅ ULDK przed Nominatim, fallback ulica→miejscowość, wybór kandydata
  najbliżej Warszawy.
- ✅ Cache trwały (punkt 5) — rozwiązuje wcześniejszy brak.

---

## 9. Warstwa raportowania (Excel) — poprawki i nowe kolumny

**Naprawiony bug zgłoszony przez Adama:** wykresy na Dashboardzie renderowały
się jako puste. Przyczyna: openpyxl/Excel domyślnie rysuje wykres tylko z
WIDOCZNYCH komórek (`chart.visible_cells_only = True` domyślnie), a dane pod
wykresy celowo siedziały w ukrytych kolumnach. Naprawione — wszystkie 4
wykresy mają teraz `visible_cells_only = False`.

**Nowe kolumny (domykają większość braków z poprzedniej wersji audytu):**
- ✅ "Adres (pełny)" + "Mapa" (link Google Maps) — patrz punkt 4.
- ✅ Osobne, klikalne kolumny per portal (Otodom/OLX/Gratka/Morizon/
  Domiporta/RynekPierwotny) zamiast jednego bloku tekstu — kolorowane wg
  werdyktu TEGO KONKRETNEGO dopasowania.
- ✅ "Status kontaktu" — rozwijana lista (Nie kontaktowano/W trakcie/
  Skontaktowano/Odrzucone), czysto do ręcznego użytku, narzędzie tego nie
  czyta ani nie nadpisuje.
- ✅ Źródło dopasowania (`otodom_json`/`olx_api`/`html_regex`) dopisane do
  każdej linii w "Uzasadnienie werdyktu".

**Wciąż brakuje (świadomie odłożone, większy zakres niż "clean up"):**
- Widok "co nowego od ostatniego uruchomienia" — wymaga śledzenia poprzedniego
  snapshotu eksportu, nie tylko `first_seen` w bazie.
- Prawdziwy eksport do zewnętrznego CRM (płaski CSV bez kolumn analitycznych).
- Wykres "Leady per gmina" nabierze sensu dopiero przy pełnych 884 leadach —
  przy próbce 20 to ciekawostka, nie sygnał.

---

## 10. Nowe źródła danych — jeszcze wcześniejszy sygnał (bez zmian)

- Decyzje WZ/MPZP z gmin, GUS REGON (PKD 41.10/41.20), Monitor Sądowy i
  Gospodarczy (nowe SPV deweloperów), przetargi na media/drogi — nic z tego
  nie ruszone.

---

## Podsumowanie: co zostało z poprzedniej listy "4 rzeczy"

1. ~~Wpiąć werdykty weryfikacji do scoringu~~ — ✅ zrobione (punkt 3).
2. ~~Domknąć re-check portali~~ — ✅ zrobione (punkt 1).
3. **Cron dzienny** — nadal do zrobienia, wymaga trwałej maszyny Adama (nie
   da się zrobić z tej sesji).
4. ~~Minimalny test regresji~~ — ✅ zrobione (punkt 6), 29 testów.

**Nowa lista priorytetów, gdyby był czas tylko na jedną rzecz:** cron dzienny —
to jedyny pozostały punkt z pierwotnej listy, i jedyny, którego nie da się
zrobić bez dostępu do trwałej infrastruktury Adama.
