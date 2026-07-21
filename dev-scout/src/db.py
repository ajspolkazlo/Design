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
    score INTEGER,
    status TEXT DEFAULT 'new',       -- new -> enriched -> scored -> exported
    first_seen TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now'))
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
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
            """INSERT INTO leads (id_sprawy, data, gmina, miejscowosc, kategoria_obiektu,
                                   inwestor, liczba_budynkow, is_likely_company, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["id_sprawy"],
                row.get("data"),
                row.get("gmina"),
                row.get("miejscowosc"),
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
