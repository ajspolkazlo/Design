"""
Cache trwaly (SQLite, przezywa kolejne uruchomienia) dla wynikow zapytan
sieciowych keyowanych po numerze dzialki albo adresie: ULDK (geometria dzialki),
KIEG WMS (ewidencja gruntow), Nominatim (geokodowanie po adresie).

Bez tego kazde ponowne uruchomienie `enrich` na tych samych leadach (np.
re-check po recheck_after_days, powtorny test) odpytuje te same zewnetrzne
API od nowa — a Nominatim ma limit 1 zapytanie/s, wiec przy powtarzajacych
sie leadach to bezposrednia strata czasu bez zadnej nowej informacji (adres
z RWDZ i numer dzialki dla juz istniejacego leada sie nie zmieniaja).

Rozroznienie od cache w pamieci procesu w verify.py (_parcel_cache): ten tu
jest per-proces TYLKO w ramach jednego wywolania Pythona; ten w geo_cache.py
jest w bazie SQLite i przezywa miedzy uruchomieniami `python -m src.main enrich`.
"""

from __future__ import annotations

import json
import sqlite3


def get(conn: sqlite3.Connection, kind: str, key: str) -> dict | None:
    row = conn.execute(
        "SELECT value_json FROM geo_cache WHERE kind = ? AND key = ?", (kind, key)
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return None


def set(conn: sqlite3.Connection, kind: str, key: str, value: dict) -> None:
    conn.execute(
        """INSERT INTO geo_cache (kind, key, value_json, cached_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(kind, key) DO UPDATE SET value_json = excluded.value_json,
                                                 cached_at = excluded.cached_at""",
        (kind, key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()
