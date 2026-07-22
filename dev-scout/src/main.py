"""
Dev Scout — orkiestrator calego pipeline'u.

Uzycie:
    python -m src.main run              # pelny przebieg: fetch + parse + filter + zapis nowych
    python -m src.main enrich           # dociagnij KRS/CEIDG + geokodowanie dla rekordow "new"
    python -m src.main export           # wyeksportuj wynik do CSV + GeoJSON
    python -m src.main run --skip-fetch # jak run, ale uzyj juz pobranego pliku CSV z data/raw

Kazdy krok jest osobny i idempotentny — mozna je odpalac osobno w n8n/cron
albo wszystkie naraz.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import yaml

from src import company_lookup, db, geocode, portal_check, rwdz_fetch, rwdz_parse, scoring
from src.filters import apply_filters

log = logging.getLogger("dev_scout")
ROOT = Path(__file__).parent.parent


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def step_fetch(cfg: dict, skip: bool) -> Path:
    raw_dir = ROOT / cfg["paths"]["raw_dir"]
    if skip:
        candidates = list(raw_dir.glob("*.csv")) + list(raw_dir.glob("*.CSV"))
        if not candidates:
            raise FileNotFoundError(f"Brak pliku CSV w {raw_dir} — najpierw uruchom bez --skip-fetch.")
        # najnowszy plik (mtime), nie alfabetycznie pierwszy — w raw_dir moze
        # lezec zarowno prawdziwy import jak i data/raw/sample_test.csv (fixture
        # do szybkich testow offline), a "sample_test.csv" wygrywa alfabetycznie
        # z realnym plikiem typu "wynik_*.csv"
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return rwdz_fetch.fetch_and_extract(cfg["rwdz"]["wojewodztwo_zip_url"], raw_dir)


def step_parse_and_filter(cfg: dict, csv_path: Path) -> pd.DataFrame:
    raw_df = rwdz_parse.load_raw(
        csv_path,
        separator=cfg["rwdz"]["column_separator"],
        encoding=cfg["rwdz"]["encoding"],
    )
    log.info("Wczytano %d wierszy z %s", len(raw_df), csv_path.name)

    normalized_df = rwdz_parse.normalize_dataframe(raw_df)
    filtered_df = apply_filters(normalized_df, cfg)
    log.info("Po filtrach zostalo %d wierszy", len(filtered_df))
    return filtered_df


def step_store(cfg: dict, filtered_df: pd.DataFrame) -> int:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    rows = []
    for _, r in filtered_df.iterrows():
        rows.append({
            "id_sprawy": r.get("norm_id_sprawy") or f"row-{r.name}",
            "data": r.get("norm_data"),
            "gmina": r.get("norm_gmina"),
            "miejscowosc": r.get("norm_miejscowosc"),
            "ulica": r.get("norm_ulica"),
            "kategoria_obiektu": r.get("norm_kategoria_obiektu"),
            "inwestor": r.get("norm_inwestor"),
            "liczba_budynkow": r.get("norm_liczba_budynkow"),
            "is_likely_company": r.get("is_likely_company"),
            "raw": r.to_dict(),
        })
    new_count = db.upsert_leads(conn, rows)
    conn.close()
    log.info("Zapisano %d nowych leadow do bazy", new_count)
    return new_count


def step_enrich(cfg: dict) -> None:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    new_leads = db.fetch_by_status(conn, "new")
    log.info("Wzbogacam %d leadow", len(new_leads))
    for lead in new_leads:
        try:
            info = company_lookup.lookup_company(lead["inwestor"] or "")
            info_json = json.dumps(info.__dict__, ensure_ascii=False)
        except Exception:
            log.exception("Nie udalo sie wzbogacic %s przez KRS/CEIDG", lead["id_sprawy"])
            info_json = json.dumps({"found": False, "error": "lookup_failed"})

        try:
            coords = geocode.geocode_address(lead["miejscowosc"] or "", lead["gmina"] or "", lead["ulica"] or None)
            lat, lon = coords if coords else (None, None)
        except Exception:
            log.exception("Nie udalo sie zgeokodowac %s", lead["id_sprawy"])
            lat, lon = None, None

        on_portal_found, on_portal_json, on_portal_checked_at = None, None, None
        if lead["ulica"]:
            # Sprawdzamy portale TYLKO gdy mamy ulice. Bez niej zostaje sama
            # miejscowosc — a "brak trafien dla samej miejscowosci" nie jest
            # wiarygodnym sygnalem "czysty": kazde miasto ma cos na sprzedaz.
            # Zweryfikowane na zywo: "Otwock Maly" (sama miejscowosc, dwa
            # slowa) przechodzilo test "min. 2 tokeny" i dawalo falszywe
            # trafienie na WSZYSTKICH 6 portalach. Zamiast zgadywac, zostawiamy
            # on_portal_found=None ("nie sprawdzono"), nie False ("czysty").
            try:
                query = f"{lead['ulica']}, {lead['miejscowosc']}"
                presence = portal_check.check_portals(query, cfg["portal_check"])
                on_portal_found = int(presence.is_present_anywhere)
                on_portal_json = json.dumps(presence.__dict__, ensure_ascii=False)
                on_portal_checked_at = presence.checked_at
            except Exception:
                log.exception("Nie udalo sie sprawdzic portali dla %s", lead["id_sprawy"])

        distance_km = None
        if lat is not None and lon is not None:
            distance_km = scoring.compute_distance_km(lat, lon, cfg)

        db.update_status(
            conn, lead["id_sprawy"], status="enriched",
            krs_ceidg_json=info_json,
            lat=lat, lon=lon,
            on_portal_found=on_portal_found,
            on_portal_json=on_portal_json,
            on_portal_checked_at=on_portal_checked_at,
            distance_km=distance_km,
        )
    portal_check.close_browser()  # zamknij Chromium jesli backend browser byl uzyty
    conn.close()


def step_score(cfg: dict) -> None:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    conn.row_factory = None
    df = pd.read_sql_query("SELECT * FROM leads WHERE status = 'enriched'", conn)
    for _, row in df.iterrows():
        lead = row.to_dict()
        try:
            company_info = json.loads(lead.get("krs_ceidg_json") or "{}")
            # Odrozniamy "sprawdzone, brak strony" od "nie sprawdzone" (np. brak
            # tokenu CEIDG, albo spolka w KRS ktorego dzis nie sprawdzamy) —
            # bez tego kazdy niesprawdzony inwestor dostawalby bonus
            # mala_firma_bez_www, mimo ze w ogole nie wiemy, czy ma strone.
            lead["company_has_website"] = bool(company_info.get("website")) if company_info.get("found") else None
        except (json.JSONDecodeError, TypeError):
            lead["company_has_website"] = None
        # NULL (nie sprawdzono — brak ulicy, patrz step_enrich) -> None, nie
        # False, tym samym wzorem co company_has_website powyzej. UWAGA:
        # pandas czyta SQL NULL jako float('nan'), a bool(nan) jest (myląco)
        # True — poleganie na tym bylo przypadkowo poprawne, ale kruche
        # (pd.NA zamiast nan rzucilby wyjatkiem), wiec robimy to jawnie.
        raw_portal_found = lead.get("on_portal_found")
        lead["on_portal_found"] = None if pd.isna(raw_portal_found) else bool(raw_portal_found)
        score = scoring.compute_score(lead, cfg)
        db.update_status(conn, lead["id_sprawy"], status="scored", score=score)
    conn.close()


def step_export(cfg: dict) -> None:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    conn.row_factory = None
    df = pd.read_sql_query("SELECT * FROM leads ORDER BY score DESC NULLS LAST", conn)
    conn.close()

    out_dir = ROOT / cfg["paths"]["output_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "leady.csv"
    df.to_csv(csv_path, index=False)

    geo_df = df.dropna(subset=["lat", "lon"])
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row.lon, row.lat]},
            "properties": {
                "inwestor": row.inwestor,
                "gmina": row.gmina,
                "miejscowosc": row.miejscowosc,
                "kategoria_obiektu": row.kategoria_obiektu,
            },
        }
        for row in geo_df.itertuples()
    ]
    geojson_path = out_dir / "leady.geojson"
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, indent=2)

    log.info("Wyeksportowano %d wierszy do %s i %s", len(df), csv_path, geojson_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Dev Scout pipeline")
    parser.add_argument("command", choices=["run", "enrich", "score", "export"])
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    cfg = load_config()

    if args.command == "run":
        csv_path = step_fetch(cfg, args.skip_fetch)
        filtered_df = step_parse_and_filter(cfg, csv_path)
        step_store(cfg, filtered_df)
    elif args.command == "enrich":
        step_enrich(cfg)
    elif args.command == "score":
        step_score(cfg)
    elif args.command == "export":
        step_export(cfg)


if __name__ == "__main__":
    main()
