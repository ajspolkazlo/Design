"""
Dev Scout — orkiestrator calego pipeline'u.

Uzycie:
    python -m src.main run              # pelny przebieg: fetch + parse + filter + zapis nowych
    python -m src.main recheck          # cofnij 'scored'->'new' dla leadow starszych niz recheck_after_days
    python -m src.main enrich           # dociagnij KRS/CEIDG + geokodowanie dla rekordow "new"
    python -m src.main score            # policz score dla rekordow "enriched"
    python -m src.main export           # wyeksportuj wynik do CSV + GeoJSON
    python -m src.main run --skip-fetch # jak run, ale uzyj juz pobranego pliku CSV z data/raw

Cykl dzienny (cron): run -> recheck -> enrich -> score -> export. `recheck`
PRZED `enrich`, zeby przekwalifikowane leady (patrz step_recheck) zostaly
wzbogacone w tym samym przebiegu co faktycznie nowe.

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

from src import (cadastral, company_lookup, db, developer_search, geo_cache, geocode, portal_check,
                  rwdz_fetch, rwdz_parse, scoring, verify)
from src.filters import apply_filters, is_private_single_family_home

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

    # Liczniki seryjnosci inwestora na PELNYM (nieodfiltrowanym) zbiorze —
    # "ile wnioskow ma ten inwestor w calym wojewodztwie" to odcisk palca
    # dewelopera (patrz verify.py), liczony tu, bo tylko tu mamy caly zbior.
    verify.build_investor_counts(raw_df, (ROOT / cfg["paths"]["db_path"]).parent)

    filtered_df = apply_filters(normalized_df, cfg)
    log.info("Po filtrach zostalo %d wierszy", len(filtered_df))
    return filtered_df


def step_store(cfg: dict, filtered_df: pd.DataFrame) -> int:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    rows = []
    rejected_private = 0
    for _, r in filtered_df.iterrows():
        liczba_budynkow = r.get("norm_liczba_budynkow")
        row = {
            "id_sprawy": r.get("norm_id_sprawy") or f"row-{r.name}",
            "data": r.get("norm_data"),
            "gmina": r.get("norm_gmina"),
            "miejscowosc": r.get("norm_miejscowosc"),
            "ulica": r.get("norm_ulica"),
            "numer_domu": r.get("norm_numer_domu"),
            "kategoria_obiektu": r.get("norm_kategoria_obiektu"),
            "inwestor": r.get("norm_inwestor"),
            "liczba_budynkow": liczba_budynkow,
            "is_likely_company": r.get("is_likely_company"),
            "raw": r.to_dict(),
        }
        # Twardy filtr (na zyczenie Adama): pojedynczy budynek jednorodzinny
        # WOLNOSTOJACY = niemal zawsze osoba prywatna, zero wartosci jako lead.
        # Zapisujemy do bazy jako status='rejected' (do wgladu/audytu
        # skutecznosci filtra), ale step_export i tools/report_xlsx.py NIGDY
        # nie czytaja tego statusu — patrz db.upsert_leads docstring.
        if is_private_single_family_home(row["kategoria_obiektu"], liczba_budynkow):
            row["status"] = "rejected"
            row["rejection_reason"] = "dom_jednorodzinny_osoba_prywatna"
            rejected_private += 1
        rows.append(row)
    new_count = db.upsert_leads(conn, rows)
    conn.close()
    if rejected_private:
        log.info("Odrzucono twardo %d wnioskow jako 'dom jednorodzinny osoby prywatnej'", rejected_private)
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
            info = None

        # Strona dewelopera (Zadanie 3, patrz src/developer_search.py) — NIP
        # (jesli akurat znany z KRS/CEIDG powyzej) wzmacnia walidacje do
        # statusu "potwierdzona"; bez niego kandydaty z dowodem domenowym
        # ladowane sa jako "prawdopodobna" najwyzej.
        try:
            dev_site = developer_search.find_developer_site(
                lead["inwestor"] or "", nip=(info.nip if info else None), miejscowosc=lead["miejscowosc"])
        except Exception:
            log.exception("Nie udalo sie wyszukac strony dewelopera dla %s", lead["id_sprawy"])
            dev_site = developer_search.DeveloperSite(investor=lead["inwestor"] or "")

        # Geokodowanie: ULDK (numer dzialki) PRZED Nominatim (adres). ULDK
        # zwraca dokladna geometrie dzialki katastralnej — dokladniejsze niz
        # dopasowanie po nazwie ulicy, i dziala NAWET GDY RWDZ nie ma
        # wypelnionej kolumny ulica (~67% realnych leadow — zweryfikowane na
        # zywo), bo numer dzialki jest w RWDZ zawsze (wymagany element kazdego
        # wniosku). Patrz src/cadastral.py.
        raw = json.loads(lead["raw_json"] or "{}")
        parcel_id = cadastral.build_parcel_id(
            raw.get("jednosta_numer_ew"), raw.get("obreb_numer"), raw.get("numer_dzialki")
        )

        # Cache trwaly (SQLite, patrz src/geo_cache.py) przed kazdym zapytaniem
        # sieciowym keyowanym po numerze dzialki/adresie — bez tego kazdy
        # ponowny `enrich` na tych samych leadach (re-check, powtorne testy)
        # odpytuje ULDK/KIEG/Nominatim od nowa dla danych, ktore sie nie zmienily.
        lat, lon = None, None
        if parcel_id:
            cached = geo_cache.get(conn, "parcel_centroid", parcel_id)
            if cached:
                lat, lon = cached["lat"], cached["lon"]
            else:
                try:
                    coords = cadastral.fetch_parcel_centroid(parcel_id)
                    if coords:
                        lat, lon = coords
                        geo_cache.set(conn, "parcel_centroid", parcel_id, {"lat": lat, "lon": lon})
                except Exception:
                    log.exception("ULDK: nie udalo sie zgeokodowac dzialki %s dla %s", parcel_id, lead["id_sprawy"])

        if lat is None:
            # fallback: Nominatim po adresie — gdy brak numeru dzialki albo
            # ULDK go nie rozpoznaje (np. dzialka scalona/podzielona od tego czasu)
            geocode_key = f"{lead['miejscowosc'] or ''}|{lead['gmina'] or ''}|{lead['ulica'] or ''}"
            cached = geo_cache.get(conn, "geocode_address", geocode_key)
            if cached:
                lat, lon = cached["lat"], cached["lon"]
            else:
                try:
                    coords = geocode.geocode_address(lead["miejscowosc"] or "", lead["gmina"] or "", lead["ulica"] or None)
                    lat, lon = coords if coords else (None, None)
                    if coords:
                        geo_cache.set(conn, "geocode_address", geocode_key, {"lat": lat, "lon": lon})
                except Exception:
                    log.exception("Nie udalo sie zgeokodowac %s", lead["id_sprawy"])
                    lat, lon = None, None

        # Ulica do sprawdzenia portali: ta z RWDZ, albo — gdy brak — odzyskana
        # z dokladnych wspolrzednych ULDK przez odwrotne geokodowanie (patrz
        # geocode.reverse_geocode_street). To jedyny sposob na sensowne
        # sprawdzenie portali dla wiekszosci leadow, ktore nie maja ulicy
        # wprost w danych RWDZ.
        recovered_street = False
        query_ulica = lead["ulica"]
        if not query_ulica and lat is not None and parcel_id:
            reverse_key = f"{lat:.5f},{lon:.5f}"
            cached = geo_cache.get(conn, "reverse_geocode", reverse_key)
            if cached:
                query_ulica = cached.get("ulica")
            else:
                try:
                    query_ulica = geocode.reverse_geocode_street(lat, lon)
                    geo_cache.set(conn, "reverse_geocode", reverse_key, {"ulica": query_ulica})
                except Exception:
                    log.exception("Odwrotne geokodowanie nie powiodlo sie dla %s", lead["id_sprawy"])
            recovered_street = bool(query_ulica)

        # Pelny adres do NIEZALEZNEJ, RECZNEJ weryfikacji (na zyczenie Adama) —
        # jesli RWDZ ma ulice+numer domu wprost, to jest to precyzyjny adres
        # pocztowy; jesli ulica byla odzyskana z ULDK (odwrotne geokodowanie),
        # oznaczamy to wprost jako "przyblizony", bo bez numeru domu to
        # najblizsza znaleziona ulica, nie potwierdzony adres wniosku.
        if lead["ulica"] and lead["numer_domu"]:
            adres_pelny = f"{lead['ulica']} {lead['numer_domu']}, {lead['miejscowosc']}"
        elif lead["ulica"]:
            adres_pelny = f"{lead['ulica']}, {lead['miejscowosc']} (bez numeru domu w RWDZ)"
        elif recovered_street and query_ulica:
            adres_pelny = f"{query_ulica}, {lead['miejscowosc']} (przybliżony — RWDZ nie podaje ulicy, odzyskana z lokalizacji działki)"
        else:
            adres_pelny = f"{lead['miejscowosc']} (RWDZ nie podaje ulicy, nie udało się jej odzyskać)"

        # Dane dzialki z ewidencji gruntow (urzedowa powierzchnia + KATEGORIA
        # wlasciciela: osoba fizyczna vs spolka) i seryjnosc inwestora w RWDZ —
        # sygnaly przydatne NIEZALEZNIE od portali (dzialaja tez dla ~88%
        # leadow bez nazwy inwestora). Patrz src/verify.py.
        verify_cfg = {**verify.DEFAULTS, **(cfg.get("verify") or {})}
        data_dir = (ROOT / cfg["paths"]["db_path"]).parent
        parcel_info = {}
        if parcel_id:
            cached = geo_cache.get(conn, "parcel_official", parcel_id)
            if cached:
                parcel_info = cached
            else:
                parcel_info = verify.parcel_official(parcel_id)
                if parcel_info.get("area_m2") is not None or parcel_info.get("owner_group"):
                    geo_cache.set(conn, "parcel_official", parcel_id, parcel_info)
        serial_count = verify.investor_serial_count(lead["inwestor"], data_dir)

        on_portal_found, on_portal_json, on_portal_checked_at = None, None, None
        match_verdicts: list[verify.MatchVerdict] = []
        if query_ulica:
            # Sprawdzamy portale TYLKO gdy mamy (realna albo odzyskana z ULDK)
            # ulice. Bez niej zostaje sama miejscowosc — a "brak trafien dla
            # samej miejscowosci" nie jest wiarygodnym sygnalem "czysty": kazde
            # miasto ma cos na sprzedaz. Zweryfikowane na zywo: "Otwock Maly"
            # (sama miejscowosc, dwa slowa) przechodzilo test "min. 2 tokeny" i
            # dawalo falszywe trafienie na WSZYSTKICH 6 portalach. Zamiast
            # zgadywac, zostawiamy on_portal_found=None ("nie sprawdzono").
            try:
                query = f"{query_ulica}, {lead['miejscowosc']}"
                property_type = portal_check.expected_property_type(lead["kategoria_obiektu"])
                presence, raw_matches = portal_check.check_portals(
                    query, cfg["portal_check"], property_type, lead["inwestor"])

                # ---- weryfikacja kazdego dopasowania (patrz verify.py) ----
                raw = json.loads(lead["raw_json"] or "{}")
                lead_ctx = {
                    "kubatura": raw.get("kubatura"),
                    "data_wniosku": lead["data"],
                    "lat": lat, "lon": lon,
                }
                for portal_name, m in raw_matches.items():
                    lead_ctx["investor_confirmed"] = m.investor_confirmed
                    if portal_name == "otodom":
                        facts = verify.fetch_otodom_facts(m.url)
                    elif portal_name == "olx" and m.olx_offer:
                        facts = verify.olx_facts_from_offer(m.olx_offer)
                    else:
                        facts = verify.fetch_html_facts(portal_name, m.url)
                    match_verdicts.append(
                        verify.judge_match(portal_name, m.url, facts, lead_ctx, parcel_info, verify_cfg))

                # Dopasowania REJECTED (rynek wtorny, pin >2 km itd.) NIE licza
                # sie jako "inwestycja jest na portalu" — to ogloszenia INNYCH
                # nieruchomosci przy tej samej ulicy (zweryfikowane na zywo:
                # Kobylka = odsprzedaz z 2020, Brwinow = inwestycja 1.8 km dalej).
                accepted = [v for v in match_verdicts if v.verdict != "REJECTED"]
                on_portal_found = int(bool(accepted))
                on_portal_json = json.dumps(presence.__dict__, ensure_ascii=False)
                on_portal_checked_at = presence.checked_at
            except Exception:
                log.exception("Nie udalo sie sprawdzic portali dla %s", lead["id_sprawy"])

        verify_payload = {
            "parcel_id": parcel_id,
            "parcel_area_m2": parcel_info.get("area_m2"),
            "parcel_owner_group": parcel_info.get("owner_group"),
            "parcel_owner_desc": parcel_info.get("owner_desc"),
            "investor_serial_count": serial_count,
            "lead_verdict": verify.best_verdict(match_verdicts),
            "matches": [
                {"portal": v.portal, "url": v.url, "verdict": v.verdict,
                 "reasons": v.reasons, "facts": v.facts}
                for v in match_verdicts
            ],
        }

        distance_km = None
        if lat is not None and lon is not None:
            distance_km = scoring.compute_distance_km(lat, lon, cfg)

        db.update_status(
            conn, lead["id_sprawy"], status="enriched",
            krs_ceidg_json=info_json,
            lat=lat, lon=lon,
            adres_pelny=adres_pelny,
            on_portal_found=on_portal_found,
            on_portal_json=on_portal_json,
            on_portal_checked_at=on_portal_checked_at,
            verify_json=json.dumps(verify_payload, ensure_ascii=False),
            distance_km=distance_km,
            dev_site_url=dev_site.url,
            dev_site_status=dev_site.status,
            dev_site_matched_on=dev_site.matched_on,
        )
    portal_check.close_browser()  # zamknij Chromium jesli backend browser byl uzyty
    conn.close()


def step_recheck(cfg: dict) -> int:
    """Cofa `scored` -> `new` dla leadow, ktore byly sprawdzone na portalach
    ale albo nic nie znaleziono, albo w ogole nie dalo sie sprawdzic (brak
    ulicy), i od tego sprawdzenia minelo wiecej niz `portal_check.recheck_after_days`.
    Bez tego kroku `recheck_after_days` w config.yaml byl martwa wartoscia —
    kod nigdzie jej nie czytal (patrz docs/AUDYT.md, sekcja 1) i lead raz
    oznaczony jako "czysty" nigdy wiecej nie byl sprawdzany, mimo ze cala idea
    projektu z CLAUDE.md to wlasnie zlapanie leada, ktory pojawi sie na
    portalu PO pierwszym sprawdzeniu.

    Leadow juz POTWIERDZONYCH (on_portal_found=1, verdykt CONFIRMED/LIKELY/
    REVIEW) NIE cofamy — raz znaleziony lead zostaje oznaczony i widoczny do
    wgladu (patrz CLAUDE.md: "Nie usuwaj leada z bazy tylko dlatego, ze w
    koncu sie pojawil na portalu"), ponowne sprawdzanie nie zmienia tego faktu.

    Wolaj PRZED `enrich` w cyklu cron (run -> recheck -> enrich -> score ->
    export), zeby przekwalifikowane leady zostaly przetworzone w tym samym przebiegu."""
    days = cfg["portal_check"].get("recheck_after_days", 14)
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    cur = conn.execute(
        """SELECT id_sprawy FROM leads
           WHERE status = 'scored'
             AND (on_portal_found IS NULL OR on_portal_found = 0)
             AND (on_portal_checked_at IS NULL
                  OR julianday('now') - julianday(on_portal_checked_at) >= ?)""",
        (days,),
    )
    ids = [row[0] for row in cur.fetchall()]
    for id_sprawy in ids:
        conn.execute("UPDATE leads SET status = 'new' WHERE id_sprawy = ?", (id_sprawy,))
    conn.commit()
    conn.close()
    log.info("Recheck: %d leadow cofnietych do 'new' (starsze niz %d dni od ostatniego sprawdzenia)", len(ids), days)
    return len(ids)


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
        try:
            vj = json.loads(lead.get("verify_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            vj = {}
        lead["lead_verdict"] = vj.get("lead_verdict")
        lead["investor_serial_count"] = vj.get("investor_serial_count") or 0
        lead["parcel_owner_group"] = vj.get("parcel_owner_group")
        score = scoring.compute_score(lead, cfg)
        db.update_status(conn, lead["id_sprawy"], status="scored", score=score)
    conn.close()


def step_export(cfg: dict) -> None:
    conn = db.connect(ROOT / cfg["paths"]["db_path"])
    conn.row_factory = None
    # status != 'rejected': leady odrzucone twardym filtrem (patrz step_store,
    # filters.is_private_single_family_home) zostaja w bazie do wgladu/audytu,
    # ale NIGDY nie maja trafic do eksportu w zadnej formie.
    df = pd.read_sql_query("SELECT * FROM leads WHERE status != 'rejected' ORDER BY score DESC NULLS LAST", conn)
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
    parser.add_argument("command", choices=["run", "recheck", "enrich", "score", "export"])
    parser.add_argument("--skip-fetch", action="store_true")
    args = parser.parse_args()

    cfg = load_config()

    if args.command == "run":
        csv_path = step_fetch(cfg, args.skip_fetch)
        filtered_df = step_parse_and_filter(cfg, csv_path)
        step_store(cfg, filtered_df)
    elif args.command == "recheck":
        step_recheck(cfg)
    elif args.command == "enrich":
        step_enrich(cfg)
    elif args.command == "score":
        step_score(cfg)
    elif args.command == "export":
        step_export(cfg)


if __name__ == "__main__":
    main()
