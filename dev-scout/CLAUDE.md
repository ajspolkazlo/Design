# Dev Scout — brief dla Claude Code

## Kontekst
Ten projekt wykrywa małych deweloperów (bliźniaki, szeregowce, inwestycje
wielorodzinne) w promieniu 20-30 km od Warszawy, zanim zaczną marketing —
źródłem są publiczne, jawne zgłoszenia/pozwolenia budowlane z rejestru RWDZ
(GUNB), wzbogacane o dane firmy (KRS/CEIDG) i geokodowanie.

Cały szkielet (fetch → parse → filter → dedup/SQLite → enrich → export CSV/GeoJSON)
jest już napisany i **przetestowany end-to-end na syntetycznych danych** —
zobacz `data/raw/sample_test.csv` i uruchom:
```
python -m src.main run --skip-fetch
python -m src.main enrich
python -m src.main export
```
żeby zobaczyć, że to działa.

**Czego NIE dało się przetestować w środowisku, w którym ten kod powstał:**
sandbox miał dostęp do internetu tylko do pypi/npm/github — zero dostępu do
`gunb.gov.pl`, `dane.gov.pl`, `ms.gov.pl`, `biznes.gov.pl`,
`nominatim.openstreetmap.org`. Ty (Claude Code) masz normalny internet —
Twoja robota to domknąć te kawałki na żywych danych.

## Zadania, w kolejności

### 1. Zweryfikuj realny import RWDZ
- Uruchom `python -m src.main run` (bez `--skip-fetch`) — to pobierze
  `wynik_mazowieckie.zip` z `https://wyszukiwarka.gunb.gov.pl/pliki_pobranie/wynik_mazowieckie.zip`
  i spróbuje go rozpakować (`src/rwdz_fetch.py`).
- Jeśli struktura zipa/pliku w środku jest inna niż zakładana (patrz komentarze
  w `rwdz_fetch.py`) — popraw logikę wyszukiwania pliku CSV w zipie.
- Uruchom `python -m src.rwdz_parse <sciezka_do_realnego_csv>` i sprawdź output
  `unresolved_columns()`. Doprecyzuj `COLUMN_HINTS` w `src/rwdz_parse.py`
  względem realnych nazw kolumn.
- Sprawdź realne wartości w kolumnie gmina (np. czy to "Piaseczno" czy
  "gmina Piaseczno" czy "m. Piaseczno") i dopasuj `config.yaml` → `region.gminy`
  jeśli trzeba (obecna logika w `filters.py` robi dopasowanie "zawiera", więc
  powinno być odporne na prefiksy typu "gmina", ale sprawdź na żywo).
- Sprawdź realne wartości w kolumnie kategorii obiektu i dopasuj
  `building_types.include_keywords` w `config.yaml`.

### 2. Domknij wzbogacanie firmowe (`src/company_lookup.py`)
To jest świadomie zostawione jako szkielet z TODO — nie chciałem zgadywać
dokładnych endpointów i ryzykować, że coś nieprawdziwego trafi do produkcji.
- Sprawdź aktualną dokumentację `https://api.biznes.gov.pl/` (CEIDG) —
  czy jest publiczne API do wyszukiwania po nazwie firmy, czy trzeba się
  zarejestrować po klucz.
- Sprawdź `https://api-krs.ms.gov.pl/` — czy jest sposób na wyszukanie po
  nazwie (nie tylko po numerze KRS). Jeśli nie ma publicznego API do
  wyszukiwania po nazwie, rozważ scraping wyszukiwarki KRS (sprawdź ToS)
  albo serwis pośredniczący (np. rejestr.io, aleo.com — sprawdź ich ToS
  i limity przed użyciem).
- Zaimplementuj `lookup_company()` zachowując sygnaturę i strukturę
  `CompanyInfo` — reszta pipeline'u (`main.py`) tego nie dotyka.
- Dodaj sensowny rate-limiting/cache (np. plik SQLite z cache po nazwie
  firmy), żeby nie odpytywać tego samego inwestora wielokrotnie.

### 2b. Domknij sprawdzanie obecności na portalach (`src/portal_check.py`)
Ten sam wzorzec co `company_lookup.py` — świadomy szkielet, nie zgaduję endpointów.
- Żaden z portali (Otodom, OLX, RynekPierwotny, Morizon, Gratka, Domiporta) nie ma
  oficjalnego API. Otodom i RynekPierwotny są na Next.js/React — sprawdź w
  devtoolsach (zakładka Network, filtr XHR/Fetch) przy wpisywaniu frazy w
  wyszukiwarkę, czy jest wewnętrzny endpoint JSON. To dużo stabilniejsze niż
  parsowanie HTML.
- Sprawdź robots.txt i ToS każdego portalu przed implementacją.
- **Nie dopasowuj po nazwie firmy z KRS jako głównym sygnale** — deweloper
  sprzedaje pod nazwą projektu/osiedla, nie nazwą spółki. Kolejność sygnałów:
  (a) ulica + miejscowość z RWDZ jako fraza wyszukiwania, (b) promień od
  geokodowanych współrzędnych jeśli portal ma wyszukiwanie po mapie,
  (c) nazwa inwestora jako dodatkowy, słabszy sygnał.
- Zaimplementuj funkcje `_check_otodom`, `_check_olx`, itd. zachowując
  sygnaturę `(query: str) -> bool`.
- Dodaj re-check co `portal_check.recheck_after_days` (z config.yaml) —
  lead "czysty" dziś może pojawić się na portalu za kilka tygodni, a to
  okno czasu jest wartością samą w sobie. Nie usuwaj leada z bazy tylko
  dlatego, że w końcu się pojawił na portalu — oznacz status i zostaw do wglądu.

### 2c. Doprecyzuj scoring (`src/scoring.py`, `config.yaml` → `scoring.weights`)
Wagi w config.yaml (`brak_na_portalach: 40`, `mala_firma_bez_www: 20`, itd.)
to punkt startowy, nie objawiona prawda — po pierwszych realnych wynikach
przejrzyj z Adamem, czy ranking faktycznie wyrzuca na górę sensowne leady,
i dostosuj wagi.

### 3. Geokodowanie
`src/geocode.py` używa Nominatim (OSM) — powinno działać od razu z Twoim
internetem. Zweryfikuj tylko, czy jakość dopasowania adresów (miejscowość +
gmina, bez dokładnej ulicy w wielu przypadkach) jest wystarczająca — jeśli
nie, rozważ geokodowanie na poziomie gminy/miejscowości zamiast dokładnego
adresu.

### 4. Harmonogram
Dodaj uruchamianie cykliczne — najprościej cron (Linux/Mac) albo
Harmonogram zadań (Windows), np. raz dziennie w nocy:
```
0 4 * * * cd /sciezka/do/dev-scout && python -m src.main run && python -m src.main enrich && python -m src.main export
```
Rozważ też wersję w n8n, jeśli Adam wolałby mieć to w swoim istniejącym
stacku n8n zamiast czystego crona — logika w `src/` jest niezależna od tego,
co ją odpala.

### 5. Digest / powiadomienia
Dodaj krok, który po `export` wysyła krótkie podsumowanie nowych leadów
(tygodniowo) — mailem albo webhookiem do Slacka. Najprościej: nowy moduł
`src/digest.py` czytający `output/leady.csv`, filtrujący po `first_seen`
z ostatnich 7 dni, i wysyłający przez SMTP albo webhook.

### 6. (opcjonalnie) Prosty dashboard
`output/leady.geojson` da się od razu wrzucić do prostej mapy — albo
Foliom (Python, statyczny HTML), albo istniejący wzorzec Adama z mapy
partnerów CSI (D3 + SVG). Nie inwestuj w to, dopóki punkty 1-3 nie działają
na żywych danych — to najmniej wartościowa część na start.

## Zasady projektu
- Każdy krok pipeline'u (`run`, `enrich`, `export`) jest idempotentny i
  osobno uruchamialny — nie łącz ich w jedną wielką funkcję.
- Dedup działa po `id_sprawy` w SQLite (`data/dev_scout.sqlite3`) —
  nie czyść tej bazy bez potrzeby, to ona pilnuje żeby nie przetwarzać
  tych samych zgłoszeń wielokrotnie.
- `config.yaml` to jedyne miejsce z listą gmin/słów kluczowych — nie
  hardkoduj tego w kodzie.
