# Audyt Dev Scout — co zmienić, żeby mieć najświeższe i najtrafniejsze leady

Stan na 22 lipca 2026, po weryfikacji całego pipeline'u na żywych danych RWDZ
(woj. mazowieckie, 680 815 wierszy) i po wdrożeniu wielosygnałowej weryfikacji
dopasowań (`src/verify.py`) + raportu Excel (`tools/report_xlsx.py`).
Punkty ułożone od największego wpływu. "✅ zrobione" = już w kodzie na tym
branchu, reszta = rekomendacje.

---

## 1. Świeżość danych — jak mieć „najnowsze" informacje

| Co | Status | Uwagi |
|---|---|---|
| **Cykliczne uruchamianie (cron dzienny)** | ❌ nadal do zrobienia (zadanie 4 z CLAUDE.md) | RWDZ/GUNB aktualizuje plik **co noc**. Bez crona pracujemy na zrzucie z 21 lipca. Rekomendacja: `run → enrich → score → export` raz dziennie o 4:00. |
| **Filtr „tylko od 2024"** | ✅ zrobione | `date_filter.min_data` w config. |
| **Re-check portali co N dni** | ⚠️ **nadal TYLKO deklaracja w configu** | `recheck_after_days: 14` istnieje w `config.yaml`, ale **żaden kod go nie czyta** (sprawdzone: `grep -rn recheck src/` trafia wyłącznie w komentarze/docstringi). `step_enrich` bierze tylko `status='new'` i po ocenieniu leada status idzie `enriched→scored` i **tam zostaje na zawsze** — lead raz oznaczony jako "czysty" nigdy nie zostanie sprawdzony ponownie automatycznie. To wprost sprzeczne z zasadą projektu z CLAUDE.md ("lead czysty dziś może pojawić się na portalu za kilka tygodni"). **Do zrobienia**: krok `recheck`, który cofa `scored`→`new` dla leadów gdzie `on_portal_checked_at` starsze niż `recheck_after_days` I `on_portal_found` było `0`/`NULL`. |
| **CEIDG endpoint `/zmiana`** | do rozważenia | Bez zmian od poprzedniego audytu. |

---

## 2. Weryfikacja dopasowań lead↔ogłoszenie — NOWA WARSTWA (dziś wdrożona)

✅ **`src/verify.py`** — odpowiedź na realny problem znaleziony w praniu danych
(dopasowanie "ta sama ulica" ≠ "ta sama inwestycja"): dwa potwierdzone na żywo
przypadki fałszywych trafień (Kobyłka — odsprzedaż z 2020 przy tej samej
ulicy; Brwinów — inna inwestycja 1,8 km dalej) zostały poprawnie wykryte i
odrzucone przez nowe sygnały geometryczne/strukturalne. Werdykt
CONFIRMED/LIKELY/REVIEW/REJECTED + lista powodów po polsku trafia teraz do
`verify_json` w bazie i do kolumny "Uzasadnienie werdyktu" w Excelu.

**Znane ograniczenia tej warstwy (ważne, żeby nie przeceniać pewności):**
- Otodom i OLX dają dane strukturalne (JSON/API) — wysoka pewność. **Gratka,
  Morizon, Domiporta i RynekPierwotny nie mają odkrytego JSON-a** — dla nich
  metraż/działka pochodzą z regexów na HTML (`fetch_html_facts`), niższa
  pewność, częściej lądują w "do przeglądu" zamiast "potwierdzone".
- **KIEG WMS (ewidencja gruntów) czasem nie zwraca danych** — na próbce 20
  leadów 4 miały `parcel_owner_group=None` (np. Wiązowna, Józefów) mimo
  poprawnego numeru działki z RWDZ. Przyczyna nieznana (możliwe: działka nie
  w tej warstwie WMS, timeout, obręb bez numeracji EGiB) — do zbadania, jeśli
  ten sygnał ma być kluczowy dla scoringu.
- **Kalibracja widełek kubatura→metraż (÷4.0…÷5.5) oparta o 4 realne pary** —
  wystarczające do wykrycia rażących rozjazdów (jak Kobyłka: 100 m² vs
  ~230 m² oczekiwane), ale to mała próbka referencyjna. Warto przeliczyć
  dzielnik ponownie po zebraniu więcej potwierdzonych par.
- **Strefa "wątpliwa" geograficznie (700 m–2 km)** — naprawiony dziś bug:
  wcześniej dystans w tym przedziale (realny przypadek: Brwinów, 1,82 km)
  znikał całkowicie z powodów werdyktu. Teraz jest widoczny i obniża ocenę,
  ale sam próg 2 km jako granica "na pewno inna nieruchomość" jest arbitralny
  (rozsądny, ale niewalidowany na dużej próbie fałszywych/prawdziwych par).
- **Seryjność inwestora liczona z surowego pola `nazwa_inwestor`** — działa
  dobrze (M4: 31 wniosków, TOP INVESTMENT: 23), ale to dopasowanie tekstowe
  (`_investor_key`) więc literówki/skróty nietypowe mogą się nie połączyć.

---

## 3. Scoring NIE korzysta jeszcze z weryfikacji — największa dziura dziś

❌ **`src/scoring.py` nie ma żadnego odwołania do `verify_json`.** Sprawdzone:
`grep -n "verify\|CONFIRMED\|verdict" src/scoring.py` → zero wyników. Skutek:
lead z ogłoszeniem **REJECTED** (czyli: portal pokazał coś, ale to najpewniej
INNA nieruchomość) i lead **CONFIRMED** (na 100% ta sama inwestycja już się
reklamuje) dostają **dokładnie taki sam wpływ na `brak_na_portalach`** — obu
liczy się jako "coś znaleziono", bo scoring patrzy tylko na
`on_portal_found`. To marnuje właśnie zbudowaną precyzję.

**Rekomendacja (najwyższy priorytet do zrobienia dalej):** dodać do
`config.yaml → scoring.weights` coś w stylu `dopasowanie_potwierdzone: -40`
(mocna kara — inwestycja już na rynku, konkurencja już tam jest) i
rozróżnić `REJECTED`/`brak dopasowań` (traktować jak "czysto") od
`CONFIRMED`/`LIKELY` (traktować jak realną obecność na portalu). Dodatkowo
`investor_serial_count ≥ 3` i `parcel_owner_group == "15"` (spółka) to gotowe,
przetestowane sygnały czekające na wagę w scoringu.

---

## 4. Trafność filtrów — bez zmian od poprzedniego audytu

- ✅ Odcięcie instalacji/sieci/przyłączy, tylko budowa nowego budynku, liczba
  budynków z tekstu — wszystko nadal działa.
- ⚠️ Domy wolnostojące (~397/884) nadal największe źródło szumu — przełącznik
  `min_budynkow: 2` czeka na decyzję.
- **Deduplikacja "miękka" po (inwestor + ulica + numer_działki)** — nadal do
  zrobienia, wciąż aktualne.
- 🆕 **`data/raw/sample_test.csv` (fixture syntetyczna, 4 wiersze) jest
  martwa** — używa separatora `#`, a `config.yaml` od naprawy realnego
  importu ma `column_separator: ";"`. Uruchomienie `run --skip-fetch` na tym
  pliku dziś **daje 0 wierszy po filtrach** (sprawdzone na żywo), nie 4 jak
  udokumentowano w CLAUDE.md. To był kiedyś kanarek regresji — dziś jest
  cichym false-negative. Albo przerobić fixture na `;`, albo dodać osobny
  test wprost wywołujący `load_raw(..., separator="#")`.

---

## 5. Sprawdzanie portali — Search API już główny backend (zmiana od poprzedniego audytu)

- ✅ **Brave Search API wdrożony i jest teraz backendem priorytetowym**
  (zmienna `BRAVE_SEARCH_API_KEY`) — poprzedni audyt rekomendował to jako
  "kierunek długoterminowy"; dziś to już produkcyjna ścieżka, pokrywa
  wszystkie 6 portali jednym zapytaniem.
- ✅ OLX HTTP (darmowy, zawsze włączony) i typ nieruchomości/URL
  konkretnego ogłoszenia (nie strony kategorii) — zweryfikowane na żywo.
- ⚠️ **Backend browser (Playwright) nadal niezweryfikowany na żywym ruchu** —
  proxy w tym środowisku blokuje Chromium nawet dla dozwolonych hostów.
  Działa tylko jako fallback bez klucza Brave, więc w praktyce dziś się nie
  uruchamia (klucz jest ustawiony). Do potwierdzenia z maszyny Adama, jeśli
  klucz Brave kiedyś wygaśnie/się skończy.
- **Budżet Brave** — pełne 884 leady zużyje ~88% miesięcznego darmowego
  limitu. Decyzja wciąż nierozstrzygnięta z Adamem.

---

## 6. Geokodowanie — ULDK już wdrożony (zmiana od poprzedniego audytu)

- ✅ **ULDK (numer działki → geometria) jest już głównym źródłem
  współrzędnych**, z fallbackiem do Nominatim — poprzedni audyt to
  rekomendował, dziś jest zrobione i rozwiązuje problem "67% leadów bez
  ulicy w RWDZ".
- ✅ Fallback ulica→miejscowość + wybór kandydata najbliżej Warszawy.
- **Cache współrzędnych** — nadal brak. Przy 884 leadach ULDK+Nominatim+KIEG
  WMS to teraz **trzy** zapytania sieciowe na leada zamiast jednego; cache
  per numer działki (podobny do `_parcel_cache` w `verify.py`, ale trwały —
  SQLite, nie w pamięci procesu) skróciłby powtórne uruchomienia.

---

## 7. Testy i niezawodność — NOWA sekcja, realna luka

- ❌ **Zero automatycznych testów w repo.** Cały pipeline (parsowanie,
  filtry, scoring, weryfikacja) był walidowany ręcznie/na żywo w trakcie tej
  sesji — nie ma `pytest`, nie ma CI (`.github/workflows` nie istnieje).
  Każda przyszła zmiana w `filters.py`/`rwdz_parse.py`/`verify.py` może cicho
  zepsuć coś, co dziś działa, i nikt się nie dowie bez ręcznego re-testu.
- ❌ Kanarek regresji (`sample_test.csv`) jest złamany (patrz punkt 4) — czyli
  nawet ten jeden ręczny test bezpieczeństwa dziś nie działa.
- **Rekomendacja:** minimalny `tests/test_filters.py` +
  `tests/test_verify.py` (bez sieci — na zamockowanych danych) jako
  pierwszy krok. Nie blokuje niczego pilnego, ale ryzyko rośnie z każdą
  kolejną zmianą w coraz bardziej rozgałęzionym `verify.py` (531 linii).

---

## 8. Warstwa raportowania (Excel) — co jest, czego brakuje

✅ **Dziś zrobione** (`tools/report_xlsx.py`, na stałe w repo zamiast
jednorazowego skryptu w scratchpadzie): zakładka Dashboard (KPI + 4 wykresy:
werdykty, portale, gminy, właściciel działki), zakładka Leady (autofiltr,
kolorowanie po werdykcie, klikalne linki do ogłoszeń, kolumna "Uzasadnienie
werdyktu"), zakładka Legenda z metodologią.

**Czego nadal brakuje do pełnego "podglądu danych":**
- **Brak widoku "co nowego od ostatniego uruchomienia".** Baza ma
  `first_seen`, ale raport to statyczny zrzut całości — nie ma zakładki
  "nowe w tym tygodniu", która realizowałaby ideę digestu z zadania 5
  CLAUDE.md.
- **Brak mapy/widoku geo.** `lat`/`lon` są w bazie i w `leady.geojson`, ale
  raport Excel ich nie pokazuje — nawet prosta kolumna z linkiem do Google
  Maps (`https://maps.google.com/?q=lat,lon`) ułatwiłaby szybkie
  zlokalizowanie leada bez przełączania narzędzi.
- **Brak rozbicia per-portal w osobnych kolumnach.** Dziś "Linki do
  ogłoszeń" to jeden blok tekstu wielu portali naraz — dla 884 leadów
  wygodniejsze byłoby: `Link Otodom`, `Link OLX`, ... (puste gdy brak).
- **Brak śledzenia działań (CRM-lite).** Raport jest czysto informacyjny —
  nie ma kolumny "kontakt wykonany / status rozmowy", więc przy kolejnym
  uruchomieniu nie widać, które leady Adam już obsłużył. Nawet prosta
  kolumna do ręcznego wypełnienia (bez logiki) rozwiązałaby to na start.
- **Brak źródła sygnału jako kolumny.** `verify_json.matches[].facts.source`
  (np. `otodom_json` vs `html_regex`) mówi, jak bardzo ufać danemu
  dopasowaniu, ale nie jest wprost widoczne w arkuszu — dziś trzeba
  wnioskować z tego, który portal to znalazł.
- **Wykres "Leady per gmina" nieinformacyjny przy małej próbce** (20
  leadów) — przy pełnych 884 nabierze sensu; warto o tym pamiętać przy
  odbiorze tego raportu jako reprezentatywnego (to wciąż próbka, nie cały
  zbiór).
- **Brak eksportu uproszczonego do CRM** (osobny płaski CSV: nazwa, telefon,
  adres, score — bez kolumn analitycznych) jeśli Adam ma docelowe narzędzie
  do kontaktu z leadami.

---

## 9. Nowe źródła danych — jeszcze wcześniejszy sygnał (bez zmian)

- Decyzje WZ/MPZP z gmin, GUS REGON (PKD 41.10/41.20), Monitor Sądowy i
  Gospodarczy (nowe SPV deweloperów), przetargi na media/drogi — wszystko
  jak w poprzednim audycie, nic z tego nie ruszone w tej sesji.

---

## Podsumowanie: 4 rzeczy o największym wpływie, gdybyś miał zrobić tylko tyle

1. **Wpiąć werdykty weryfikacji do scoringu** (punkt 3) — dziś to zbudowana,
   ale nieużywana precyzja. Najmniejszy koszt, największy zwrot z tego, co
   już istnieje.
2. **Domknąć re-check portali** (punkt 1) — kod dziś sprawdza portal raz na
   zawsze; sama idea "okno czasowe = przewaga" z CLAUDE.md nie działa bez tego.
3. **Cron dzienny** — bez tego wciąż pracujemy na zrzucie sprzed dnia.
4. **Minimalny test regresji** (punkt 7) — `verify.py` ma już 531 linii i
   rośnie; jeden złamany kanarek (sample_test.csv) już się zdarzył raz w tej
   sesji.
