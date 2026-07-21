# Dev Scout

Wykrywa małych deweloperów (bliźniaki, szeregowce, inwestycje wielorodzinne)
w promieniu 20-30 km od Warszawy, zanim zaczną marketing — na podstawie
publicznego rejestru zgłoszeń/pozwoleń budowlanych RWDZ (GUNB), wzbogaconego
o dane firmy (KRS/CEIDG) i lokalizację.

## Status
Szkielet napisany i przetestowany end-to-end na syntetycznych danych
(`data/raw/sample_test.csv`). Realny import z GUNB i wzbogacanie KRS/CEIDG
wymagają dokończenia z maszyny z pełnym dostępem do internetu — patrz
`CLAUDE.md` po dokładną listę zadań.

## Szybki start
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# test na przykładowych danych (bez pobierania z sieci)
python -m src.main run --skip-fetch
python -m src.main enrich
python -m src.main export
cat output/leady.csv
```

Realny przebieg (wymaga internetu):
```bash
python -m src.main run       # pobiera świeży plik z GUNB, filtruje, zapisuje nowe leady
python -m src.main enrich    # dociąga KRS/CEIDG + współrzędne + obecność na portalach
python -m src.main score     # liczy score 0-100 (brak na portalach, mała firma, świeży wpis, skala, odległość)
python -m src.main export    # CSV + GeoJSON w output/, posortowane po score malejąco
```

## Struktura
```
config.yaml           # gminy, słowa kluczowe, blocklista dużych deweloperów, wagi scoringu
src/rwdz_fetch.py      # pobranie + rozpakowanie pliku RWDZ dla woj. mazowieckiego
src/rwdz_parse.py      # parsowanie CSV, elastyczne wykrywanie kolumn
src/filters.py         # gmina / typ zabudowy / blocklist dużych graczy / skala inwestycji
src/db.py              # SQLite: dedup + status pipeline'u
src/company_lookup.py  # wzbogacanie KRS/CEIDG — SZKIELET, do dokończenia (patrz CLAUDE.md)
src/geocode.py         # geokodowanie przez Nominatim (OSM)
src/portal_check.py    # sprawdzanie obecności na Otodom/OLX/RynekPierwotny — SZKIELET (patrz CLAUDE.md)
src/distance.py        # odległość od centrum Warszawy (haversine)
src/scoring.py         # score 0-100 zamiast twardego filtra — sortowanie zamiast odrzucania
src/main.py            # orkiestrator CLI
CLAUDE.md              # brief z konkretnymi zadaniami do dokończenia w Claude Code
```

## Filozofia: score, nie twardy filtr
Zamiast odrzucać leada, który nie spełnia jednego kryterium na 100%, każdy
lead dostaje punktację 0-100 i wyniki są posortowane malejąco. Znani, duzi
deweloperzy (blocklist w `config.yaml`) i inwestycje poza zakresem skali
(1 budynek albo >40) są odrzucane na twardo — to oczywiste szumy. Reszta
kryteriów (obecność na portalach, wiek/wielkość firmy, świeżość wpisu,
odległość od Warszawy) wpływa na ranking, nie na binarne włącz/wyłącz.

## Dlaczego RWDZ
Każdy inwestor — nawet firma bez budżetu na marketing — musi zgłosić budowę
albo dostać pozwolenie. To trafia do jawnego, darmowego rejestru GUNB
zanim ktokolwiek wystawi ogłoszenie. Rejestr jest do pobrania hurtowo
(CSV, per województwo), więc nie ma potrzeby scrapowania portali.
