"""
Prosta warstwa SQLite: przechowuje odfiltrowane rekordy, zeby przy kolejnym
uruchomieniu nie przetwarzac ponownie tego samego zgloszenia/wniosku, i zeby
trzymac wynik wzbogacania (KRS/CEIDG, geokodowanie) obok surowych danych.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id_sprawy TEXT PRIMARY KEY,
    data TEXT,
    gmina TEXT,
    miejscowosc TEXT,
    ulica TEXT,
    numer_domu TEXT,
    adres_pelny TEXT,          -- pelny adres do samodzielnej weryfikacji (patrz main.py step_enrich)
    kategoria_obiektu TEXT,
    inwestor TEXT,
    liczba_budynkow TEXT,
    is_likely_company INTEGER,
    raw_json TEXT,
    krs_ceidg_json TEXT,
    company_has_website INTEGER,
    lat REAL,
    lon REAL,
    distance_km REAL,
    on_portal_found INTEGER,
    on_portal_json TEXT,
    on_portal_checked_at TEXT,
    verify_json TEXT,
    score INTEGER,
    status TEXT DEFAULT 'new',       -- new -> enriched -> scored -> exported
    first_seen TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now'))
);

-- Cache trwaly (przezywa kolejne uruchomienia enrichu, w odroznieniu od cache w
-- pamieci procesu w verify.py) dla zapytan sieciowych keyowanych po numerze
-- dzialki lub adresie: ULDK (geometria/centroid dzialki), KIEG WMS (ewidencja
-- gruntow), Nominatim (geokodowanie po adresie). Bez tego kazde ponowne
-- uruchomienie enrichu na tych samych leadach (np. re-check, powtorne testy)
-- odpytuje te same zewnetrzne API od nowa. `kind` rozroznia rodzaj wpisu,
-- `key` to parcel_id albo znormalizowany adres — patrz src/geo_cache.py.
CREATE TABLE IF NOT EXISTS geo_cache (
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    cached_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (kind, key)
);
"""

# Kolumny dodane po pierwszych produkcyjnych bazach — CREATE TABLE IF NOT EXISTS
# nie zmienia istniejacych tabel, wiec doszywamy je ALTER-em przy kazdym connect
# (idempotentnie: "duplicate column name" ignorujemy).
_MIGRATIONS = [
    "ALTER TABLE leads ADD COLUMN verify_json TEXT",
    "ALTER TABLE leads ADD COLUMN numer_domu TEXT",
    "ALTER TABLE leads ADD COLUMN adres_pelny TEXT",
]


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    for migration in _MIGRATIONS:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError:
            pass  # kolumna juz istnieje
    return conn


def upsert_leads(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Wstawia nowe rekordy, ignoruje juz istniejace (po id_sprawy).
    Zwraca liczbe faktycznie nowych rekordow."""
    cur = conn.cursor()
    new_count = 0
    for row in rows:
        cur.execute("SELECT 1 FROM leads WHERE id_sprawy = ?", (row["id_sprawy"],))
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO leads (id_sprawy, data, gmina, miejscowosc, ulica, numer_domu,
                                   kategoria_obiektu, inwestor, liczba_budynkow, is_likely_company, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id_sprawy"],
                row.get("data"),
                row.get("gmina"),
                row.get("miejscowosc"),
                row.get("ulica"),
                row.get("numer_domu"),
                row.get("kategoria_obiektu"),
                row.get("inwestor"),
                row.get("liczba_budynkow"),
                int(bool(row.get("is_likely_company"))),
                json.dumps(row.get("raw", {}), ensure_ascii=False),
            ),
        )
        new_count += 1
    conn.commit()
    return new_count


def fetch_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute("SELECT * FROM leads WHERE status = ?", (status,)).fetchall()


def update_status(conn: sqlite3.Connection, id_sprawy: str, status: str, **fields) -> None:
    set_clauses = ["status = ?", "last_updated = datetime('now')"]
    values: list = [status]
    for key, value in fields.items():
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(id_sprawy)
    conn.execute(f"UPDATE leads SET {', '.join(set_clauses)} WHERE id_sprawy = ?", values)
    conn.commit()
