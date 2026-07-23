# -*- coding: utf-8 -*-
"""
Generator raportu Excel dla Dev Scout — na stale w repo (czesc pipeline'u,
nie jednorazowy skrypt).

Uzycie:
    python tools/report_xlsx.py [sciezka_wyjsciowa.xlsx] [--status scored]

Arkusze:
  1. Leady   — pelna tabela z autofiltrem, werdyktem i POWODAMI werdyktu,
               klikalnymi linkami do ogloszen per portal, kolorowaniem po werdykcie
  2. Legenda — metodologia, definicje, znane ograniczenia

(Wczesniejsza wersja miala tez arkusz Dashboard z KPI/wykresami — usuniety na
zyczenie, wygladal fatalnie w renderowaniu Excela.)

Zrodlem jest baza SQLite (nie CSV) — raport siega po verify_json/on_portal_json,
ktorych nie ma w uproszczonym eksporcie CSV.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # zeby "from src import portal_check" dzialalo przy uruchomieniu jako skrypt
FONT = "Calibri"

PORTAL_ORDER = ["otodom", "olx", "gratka", "morizon", "domiporta", "rynekpierwotny"]
PORTAL_LABELS = {
    "otodom": "Otodom", "olx": "OLX", "gratka": "Gratka",
    "morizon": "Morizon", "domiporta": "Domiporta", "rynekpierwotny": "RynekPierwotny",
}
CONTACT_STATUSES = ["", "Nie kontaktowano", "W trakcie", "Skontaktowano", "Odrzucone"]

# Status strony dewelopera (Zadanie 3, patrz src/developer_search.py) —
# klikalny link TYLKO dla potwierdzona/prawdopodobna (patrz rendering nizej),
# zeby nigdy nie sugerowac pewnosci, ktorej nie ma.
DEV_SITE_STYLE = {
    "potwierdzona":                       ("C6EFCE", "006100", "✔ potwierdzona"),
    "prawdopodobna":                      ("DDEBF7", "1F4E79", "≈ prawdopodobna"),
    "kandydat_niepewny":                  ("FFEB9C", "9C6500", "? niepewna — sprawdź ręcznie"),
    "brak_do_wyszukania_osoba_fizyczna":  ("F2F2F2", "7F7F7F", "— osoba fizyczna"),
    "nie_znaleziono":                     ("F2F2F2", "7F7F7F", "— nie znaleziono"),
    "nie_sprawdzono":                     ("F2F2F2", "7F7F7F", "— nie sprawdzono"),
}

# ---- paleta ----
C_HEAD = "1F3864"      # granat naglowka
C_HEAD_TXT = "FFFFFF"
C_BORDER = "D6DCE5"
VERDICT_STYLE = {
    "CONFIRMED": ("C6EFCE", "006100", "✔ potwierdzone"),
    "LIKELY":    ("DDEBF7", "1F4E79", "≈ prawdopodobne"),
    "REVIEW":    ("FFEB9C", "9C6500", "? do przeglądu"),
    "REJECTED":  ("FFC7CE", "9C0006", "✖ odrzucone"),
    "CLEAN":     ("E2EFDA", "375623", "— czysty (brak ogłoszeń)"),
    "UNCHECKED": ("F2F2F2", "7F7F7F", "n/d (nie sprawdzono)"),
}


def load_rows(db_path: Path, status: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(
        "SELECT * FROM leads WHERE status = ? ORDER BY score DESC", conn, params=(status,))
    conn.close()
    return df


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _final_liveness_check(portal: str, url: str, timeout: int = 10) -> bool:
    """Ostatni, NIEZALEŻNY krok weryfikujący TUŻ PRZED wygenerowaniem
    klikalnego linku w raporcie (na życzenie: ogłoszenie mogło wygasnąć w
    czasie między enrichem a wygenerowaniem tego pliku — dane w bazie mogą
    mieć kilka dni). Tania kontrola (tylko status HTTP + wzorzec URL-a, bez
    ponownej pełnej ekstrakcji danych) — przy niepewności (błąd sieci, i tak
    dalej) zwraca False: WOLIMY nie pokazać klikalnego linku, który może być
    martwy, niż pokazać pewny link, który faktycznie prowadzi donikąd."""
    import requests
    from src import portal_check
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
    except requests.RequestException:
        return False
    if resp.status_code >= 400:
        return False
    if not portal_check._is_individual_listing(portal, resp.url):
        return False
    if portal_check._is_rental(resp.url):
        return False
    return True


def effective_matches(row, recheck_live: bool = True) -> list[dict]:
    """Dopasowania z verify_json, z DODATKOWĄ świeżą weryfikacją żywotności
    tuż przed generowaniem raportu (patrz _final_liveness_check). Każde
    dopasowanie, które w bazie było nie-REJECTED, ale w tej chwili okazuje
    się martwe/przekierowane/wynajmem, zostaje tu przepisane na REJECTED z
    dopisanym powodem — jeden, spójny punkt prawdy używany zarówno przez
    lead_verdict_and_reasons, jak i per_portal_matches."""
    try:
        vj = json.loads(row.get("verify_json") or "{}")
    except (TypeError, ValueError):
        vj = {}
    matches = [dict(m) for m in (vj.get("matches") or [])]
    if not recheck_live:
        return matches
    for m in matches:
        if m["verdict"] == "REJECTED" or not m.get("url"):
            continue
        if not _final_liveness_check(m["portal"], m["url"]):
            m["verdict"] = "REJECTED"
            m["reasons"] = list(m.get("reasons") or []) + [
                "ogłoszenie zweryfikowane ponownie TUŻ PRZED wygenerowaniem raportu — już nieaktualne"
            ]
    return matches


def lead_verdict_and_reasons(matches: list[dict], checked: bool) -> tuple[str, str, str, str]:
    """(werdykt, powody, linki_tekst, pierwszy_url). Werdykt leada:
    - najlepszy werdykt WIARYGODNYCH dopasowan (nie-REJECTED) z matches
    - CLEAN gdy sprawdzono i nie ma zadnego wiarygodnego dopasowania — TAKZE
      gdy cos znaleziono, ale wszystko odrzucono (wynajem/nieaktualne/inna
      nieruchomosc): z punktu widzenia leada nadal NIC wiarygodnego nie jest
      na portalu = wciaz dobry, wczesny lead. Powody wymieniaja, co odrzucono.
    - UNCHECKED gdy nie bylo jak sprawdzic (brak ulicy)"""
    order = ["CONFIRMED", "LIKELY", "REVIEW", "REJECTED"]
    accepted = [m for m in matches if m["verdict"] != "REJECTED"]

    if not accepted:
        if not checked:
            return "UNCHECKED", "brak ulicy w RWDZ i nie dało się jej odzyskać z działki — portali nie sprawdzano", "", ""
        if not matches:
            return "CLEAN", "sprawdzono 6 portali — zero dopasowań dla tej lokalizacji", "", ""
        # cos znaleziono, ale wszystko odrzucono — pokazujemy dlaczego
        rejected_lines = [
            f"[{m['portal']}] odrzucone: {'; '.join(m.get('reasons') or ['(bez powodów)'])}"
            for m in matches
        ]
        return ("CLEAN",
                "brak wiarygodnego ogłoszenia — znalezione dopasowania odrzucono:\n" + "\n".join(rejected_lines),
                "", "")

    best = min((m["verdict"] for m in accepted), key=order.index)
    lines, links = [], []
    for m in sorted(matches, key=lambda m: order.index(m["verdict"])):
        reasons = "; ".join(m.get("reasons") or ["(bez powodów)"])
        source = (m.get("facts") or {}).get("source", "")
        source_txt = f" [źródło danych: {source}]" if source else ""
        lines.append(f"[{m['portal']} → {m['verdict']}] {reasons}{source_txt}")
        if m["verdict"] != "REJECTED" and m.get("url"):
            links.append(m["url"])
    first_url = links[0] if links else ""
    return best, "\n".join(lines), "\n".join(links), first_url


def per_portal_matches(matches: list[dict]) -> dict[str, tuple[str, str]]:
    """{portal: (werdykt, url)} z JUZ przetworzonej listy matches (patrz
    effective_matches — swieza weryfikacja zywotnosci juz zastosowana).
    Link jest klikalny TYLKO dla dopasowan nie-REJECTED z niepustym URL-em
    (patrz rendering nizej) — dla REJECTED (wynajem/nieaktualne/inna
    nieruchomosc) i pustych URL-i pokazujemy sam werdykt bez hiperlacza."""
    return {m["portal"]: (m["verdict"], m.get("url") or "") for m in matches}


def gmaps_link(row) -> str | None:
    """Link do Google Maps do SAMODZIELNEJ weryfikacji lokalizacji — wspolrzedne
    (centroid dzialki z ULDK, najdokladniejsze) gdy dostepne, inaczej
    wyszukiwanie po pelnym adresie z RWDZ (patrz main.py::step_enrich,
    adres_pelny)."""
    lat, lon = row.get("lat"), row.get("lon")
    if pd.notna(lat) and pd.notna(lon):
        return f"https://www.google.com/maps?q={lat},{lon}"
    adres = row.get("adres_pelny")
    if pd.notna(adres) and adres:
        import urllib.parse
        return f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote(str(adres))}"
    return None


def parcel_summary(row) -> tuple[str, str, int | None]:
    try:
        vj = json.loads(row.get("verify_json") or "{}")
    except (TypeError, ValueError):
        vj = {}
    owner = vj.get("parcel_owner_desc") or "b/d"
    area = vj.get("parcel_area_m2")
    area_txt = f"{area} m²" if area else "b/d"
    serial = vj.get("investor_serial_count")
    return owner, area_txt, serial


def build(out_path: Path, status: str = "scored", recheck_live: bool = True) -> None:
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    df = load_rows(ROOT / cfg["paths"]["db_path"], status)
    if df.empty:
        raise SystemExit(f"Brak leadow o statusie {status!r} w bazie")

    rows = []
    if recheck_live:
        print(f"Weryfikuję żywotność linków tuż przed wygenerowaniem raportu ({len(df)} leadów)...")
    for _, r in df.iterrows():
        checked = not pd.isna(r.get("on_portal_found"))
        matches = effective_matches(r, recheck_live=recheck_live)
        verdict, reasons, links, first_url = lead_verdict_and_reasons(matches, checked)
        owner, parcel_area, serial = parcel_summary(r)
        inwestor = r["inwestor"] if pd.notna(r["inwestor"]) else "(brak w RWDZ)"
        serial_txt = ""
        if serial and serial >= 2:
            serial_txt = f"{serial} wniosków w RWDZ (seryjny)" if serial >= 3 else f"{serial} wnioski w RWDZ"
        elif pd.notna(r["inwestor"]):
            serial_txt = "1 wniosek"
        portal_matches = per_portal_matches(matches)
        row = {
            "Score": int(r["score"]) if pd.notna(r["score"]) else None,
            "Werdykt": verdict,
            "Data zgłoszenia": str(r["data"])[:10] if pd.notna(r["data"]) else "",
            "Gmina": r["gmina"] if pd.notna(r["gmina"]) else "",
            "Miejscowość": r["miejscowosc"] if pd.notna(r["miejscowosc"]) else "",
            # Adres pelny (ulica+numer domu z RWDZ, albo ulica odzyskana z ULDK,
            # oznaczona jako przybliżona) — zeby Adam mogl SAM zweryfikowac
            # lokalizacje niezaleznie od tego, co znalazl portal_check/verify.
            "Adres (pełny)": r["adres_pelny"] if pd.notna(r.get("adres_pelny")) else "",
            "Rodzaj inwestycji": r["kategoria_obiektu"] if pd.notna(r["kategoria_obiektu"]) else "",
            "Inwestor": inwestor,
            "Seryjność inwestora": serial_txt,
            # Strona dewelopera (Zadanie 3) — status i URL osobno w dwoch
            # kolumnach, zeby dalo sie kolorowac/filtrowac po statusie
            # niezaleznie od tego, czy link jest klikalny (patrz DEV_SITE_STYLE
            # i rendering nizej: klikalny TYLKO dla potwierdzona/prawdopodobna).
            "Strona dewelopera": r["dev_site_url"] if pd.notna(r.get("dev_site_url")) else "",
            "Status strony": r["dev_site_status"] if pd.notna(r.get("dev_site_status")) else "nie_sprawdzono",
            "Właściciel działki (ewidencja)": owner,
            "Pow. działki (ewidencja)": parcel_area,
            "Uzasadnienie werdyktu": reasons,
        }
        for portal in PORTAL_ORDER:
            row[PORTAL_LABELS[portal]] = portal_matches.get(portal, (None, None))
        row.update({
            "Mapa": "Zobacz na mapie" if gmaps_link(r) else "",
            "Status kontaktu": "",
            "Odległość (km)": round(r["distance_km"], 1) if pd.notna(r["distance_km"]) else None,
            "Nr sprawy (GUNB)": r["id_sprawy"],
            "_first_url": first_url,
            "_gmaps_url": gmaps_link(r),
        })
        rows.append(row)
    data = pd.DataFrame(rows)

    wb = Workbook()

    # ============================ LEADY ============================
    ws = wb.active
    ws.title = "Leady"
    headers = [c for c in data.columns if not c.startswith("_")]
    ws.append(headers)

    thin = Side(style="thin", color=C_BORDER)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for i, _ in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i)
        c.font = Font(name=FONT, bold=True, size=10, color=C_HEAD_TXT)
        c.fill = PatternFill("solid", fgColor=C_HEAD)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = border
    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(data) + 1}"

    verdict_col = headers.index("Werdykt") + 1
    portal_cols = {PORTAL_LABELS[p]: headers.index(PORTAL_LABELS[p]) + 1 for p in PORTAL_ORDER}
    map_col = headers.index("Mapa") + 1
    contact_col = headers.index("Status kontaktu") + 1
    dev_site_col = headers.index("Strona dewelopera") + 1
    dev_status_col = headers.index("Status strony") + 1

    for ridx, (_, row) in enumerate(data.iterrows(), start=2):
        for cidx, h in enumerate(headers, start=1):
            value = row[h]
            if h in PORTAL_LABELS.values() or h in ("Strona dewelopera", "Status strony"):
                continue  # pisane osobno nizej (hiperlacz + kolor per werdykt/status)
            cell = ws.cell(row=ridx, column=cidx, value=value)
            cell.font = Font(name=FONT, size=10)
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        # kolorowanie werdyktu (cala komorka + czytelna etykieta)
        vcell = ws.cell(row=ridx, column=verdict_col)
        fill, txt_color, label = VERDICT_STYLE.get(row["Werdykt"], ("FFFFFF", "000000", row["Werdykt"]))
        vcell.value = label
        vcell.fill = PatternFill("solid", fgColor=fill)
        vcell.font = Font(name=FONT, size=10, bold=True, color=txt_color)

        # kolumny per portal: puste gdy brak dopasowania, inaczej klikalny link
        # z kolorem tla wg werdyktu TEGO KONKRETNEGO dopasowania (nie ogolnego
        # werdyktu leada) — pozwala od razu zobaczyc, KTORY portal dal jaki wynik.
        for portal in PORTAL_ORDER:
            label_name = PORTAL_LABELS[portal]
            verdict, url = row[label_name]
            pcell = ws.cell(row=ridx, column=portal_cols[label_name])
            pcell.border = border
            pcell.alignment = Alignment(vertical="top", horizontal="center")
            if verdict is None:
                pcell.value = "—"
                pcell.font = Font(name=FONT, size=10, color="BFBFBF")
            elif verdict == "REJECTED" or not url:
                # NIE robimy klikalnego linku dla odrzuconych (wynajem/
                # nieaktualne/inna nieruchomosc) ani przy pustym URL — sam
                # znacznik "odrzucone", zeby nie bylo martwych/mylacych linkow
                # (dokladnie to, na co skarzyl sie Adam)
                p_fill, p_color, _ = VERDICT_STYLE.get(verdict or "REJECTED", ("FFC7CE", "9C0006", ""))
                pcell.value = "✖ odrzucone" if verdict == "REJECTED" else "(brak linku)"
                pcell.fill = PatternFill("solid", fgColor=p_fill)
                pcell.font = Font(name=FONT, size=9, color=p_color)
            else:
                p_fill, p_color, _ = VERDICT_STYLE.get(verdict, ("FFFFFF", "000000", verdict))
                pcell.value = "ogłoszenie"
                pcell.fill = PatternFill("solid", fgColor=p_fill)
                pcell.font = Font(name=FONT, size=10, color=p_color, underline="single")
                pcell.hyperlink = url

        # Strona dewelopera + Status strony (Zadanie 3, patrz src/developer_search.py):
        # klikalny link TYLKO dla potwierdzona/prawdopodobna (dowod domenowy,
        # ew. + NIP) — dla kandydat_niepewny pokazujemy sam URL jako zwykly
        # tekst (przydatny do recznej weryfikacji, ale bez sugerowania
        # pewnosci) i NIGDY nie robimy hiperlacza; dla braku/nie_znaleziono
        # sam znacznik statusu.
        dev_status = row["Status strony"] or "nie_sprawdzono"
        dev_url = row["Strona dewelopera"]
        d_fill, d_color, d_label = DEV_SITE_STYLE.get(dev_status, ("FFFFFF", "000000", dev_status))
        scell = ws.cell(row=ridx, column=dev_status_col, value=d_label)
        scell.fill = PatternFill("solid", fgColor=d_fill)
        scell.font = Font(name=FONT, size=10, bold=True, color=d_color)
        scell.border = border
        scell.alignment = Alignment(vertical="top", horizontal="center", wrap_text=True)

        ucell = ws.cell(row=ridx, column=dev_site_col)
        ucell.border = border
        ucell.alignment = Alignment(vertical="top", wrap_text=True)
        if dev_url and dev_status in ("potwierdzona", "prawdopodobna"):
            ucell.value = dev_url
            ucell.hyperlink = dev_url
            ucell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
        elif dev_url:
            ucell.value = dev_url
            ucell.font = Font(name=FONT, size=9, color="7F7F7F")
        else:
            ucell.value = "—"
            ucell.font = Font(name=FONT, size=10, color="BFBFBF")

        # link do mapy (patrz gmaps_link) — geometria dzialki z ULDK gdy jest,
        # inaczej wyszukiwanie po pelnym adresie z RWDZ
        if row["_gmaps_url"]:
            mcell = ws.cell(row=ridx, column=map_col)
            mcell.value = "Zobacz na mapie"
            mcell.hyperlink = row["_gmaps_url"]
            mcell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
            mcell.border = border
            mcell.alignment = Alignment(horizontal="center")

        ccell = ws.cell(row=ridx, column=contact_col)
        ccell.border = border
        ccell.font = Font(name=FONT, size=10)

    # rozwijana lista w "Status kontaktu" — proste sledzenie kontaktu bez CRM
    dv = DataValidation(type="list", formula1='"' + ",".join(s or "(puste)" for s in CONTACT_STATUSES[1:]) + '"',
                         allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"{get_column_letter(contact_col)}2:{get_column_letter(contact_col)}{len(data) + 1}")

    widths = {
        "Score": 7, "Werdykt": 17, "Data zgłoszenia": 11, "Gmina": 14, "Miejscowość": 14,
        "Adres (pełny)": 34, "Rodzaj inwestycji": 34, "Inwestor": 24, "Seryjność inwestora": 15,
        "Właściciel działki (ewidencja)": 10, "Pow. działki (ewidencja)": 10,
        "Uzasadnienie werdyktu": 70, "Mapa": 14, "Status kontaktu": 16,
        "Odległość (km)": 9, "Nr sprawy (GUNB)": 24,
        "Strona dewelopera": 30, "Status strony": 16,
    }
    for i, h in enumerate(headers, start=1):
        if h in PORTAL_LABELS.values():
            widths[h] = 12
        ws.column_dimensions[get_column_letter(i)].width = widths.get(h, 16)

    # ============================ LEGENDA ============================
    lg = wb.create_sheet("Legenda")
    lg.sheet_view.showGridLines = False
    L = [
        ("Dev Scout — metodologia werdyktów", 14, True),
        ("", 10, False),
        ("WERDYKTY (kolumna 'Werdykt' w arkuszu Leady):", 11, True),
        ("✔ potwierdzone — ogłoszenie tej inwestycji NA PEWNO jest na portalu: pin ogłoszenia w/przy działce", 10, False),
        ("   z wniosku (≤150 m) + co najmniej jeden sygnał dodatkowy (rynek pierwotny, metraż w widełkach", 10, False),
        ("   z kubatury, zgodna działka, spójny czas, nazwa inwestora).", 10, False),
        ("≈ prawdopodobne — mocne poszlaki, ale bez twardego domknięcia geometrycznego.", 10, False),
        ("? do przeglądu — sygnały sprzeczne albo brak danych strukturalnych ogłoszenia; 5 s ręcznego rzutu okiem.", 10, False),
        ("✖ odrzucone — znalezione ogłoszenie dotyczy INNEJ nieruchomości (rynek wtórny, pin >2 km,", 10, False),
        ("   ogłoszenie starsze od wniosku). NIE liczy się jako 'inwestycja jest na portalu'.", 10, False),
        ("— czysty — sprawdzono 6 portali, zero dopasowań: inwestycja jeszcze nie jest reklamowana = PRZEWAGA.", 10, False),
        ("n/d — brak ulicy w RWDZ i nie dało się jej odzyskać z numeru działki; portali nie sprawdzano.", 10, False),
        ("", 10, False),
        ("SYGNAŁY WERYFIKACJI (wszystkie darmowe, wszystkie z oficjalnych/publicznych źródeł):", 11, True),
        ("1. Geometria: dokładne współrzędne ogłoszenia (Otodom osadza je w kodzie strony) vs poligon działki", 10, False),
        ("   ewidencyjnej z państwowego ULDK (GUGiK). Pin ≤150 m = potwierdzenie; >2 km = odrzucenie.", 10, False),
        ("2. Rynek pierwotny/wtórny — z danych strukturalnych Otodom/OLX. Wtórny = nie nasza nowa inwestycja.", 10, False),
        ("3. Czas: data utworzenia ogłoszenia vs data wniosku (ogłoszenie starsze o >4 mies. = podejrzane).", 10, False),
        ("4. Metraż: kubatura z wniosku RWDZ (m³) → widełki powierzchni użytkowej (÷5.5…÷4.0, kalibracja na", 10, False),
        ("   realnych parach) vs metraż z ogłoszenia.", 10, False),
        ("5. Ewidencja gruntów (KIEG WMS): urzędowa powierzchnia działki + KATEGORIA właściciela (osoba", 10, False),
        ("   fizyczna / spółka — bez danych osobowych). Spółka = sygnał dewelopera nawet bez nazwy w RWDZ.", 10, False),
        ("6. Seryjność: liczba wniosków tego samego inwestora w całym mazowieckim RWDZ (lokalny zrzut).", 10, False),
        ("   ≥3 wnioski = seryjny inwestor (deweloper). Np. 'M4 Sp. z o.o.': 31 wniosków.", 10, False),
        ("", 10, False),
        ("ZNANE OGRANICZENIA:", 11, True),
        ("• Gratka/Morizon/Domiporta nie publikują dokładnych współrzędnych w HTML — dla nich metraż/działka", 10, False),
        ("  z regexów (niższa pewność) i werdykt częściej 'do przeglądu'.", 10, False),
        ("• OLX celowo rozmywa pin do ~1 km — używany tylko wspierająco, nigdy do odrzucenia.", 10, False),
        ("• Kubatura bywa podana dla CAŁEGO zamierzenia (kilka budynków) — widełki wtedy zawyżone;", 10, False),
        ("  umiarkowane rozjazdy metrażu celowo nie karzą werdyktu.", 10, False),
        ("• 'czysty' oznacza stan w dniu sprawdzenia — krok `recheck` (uruchamiany PRZED `enrich` w cyklu", 10, False),
        ("  dziennym) automatycznie cofa taki lead do ponownego sprawdzenia po recheck_after_days.", 10, False),
        ("", 10, False),
        ("KOLUMNY DODATKOWE", 11, True),
        ("Adres (pełny) — ulica + numer domu wprost z RWDZ, gdy są wypełnione; gdy RWDZ nie ma ulicy,", 10, False),
        ("  pokazana jest ulica ODZYSKANA z lokalizacji działki (ULDK + geokodowanie odwrotne), oznaczona", 10, False),
        ("  jawnie jako 'przybliżony' — to NIE jest potwierdzony adres z wniosku, tylko najbliższa ulica.", 10, False),
        ("  Cel: Adam może sam zlokalizować i zweryfikować inwestycję niezależnie od wyniku portal_check.", 10, False),
        ("Kolumny portali (Otodom/OLX/Gratka/Morizon/Domiporta/RynekPierwotny) — puste ('—') gdy brak", 10, False),
        ("  dopasowania na danym portalu, inaczej klikalny link kolorowany wg werdyktu TEGO KONKRETNEGO", 10, False),
        ("  dopasowania (może się różnić między portalami dla tego samego leada).", 10, False),
        ("Mapa — link do Google Maps: współrzędne działki z ULDK gdy dostępne (najdokładniejsze), inaczej", 10, False),
        ("  wyszukiwanie po adresie z kolumny 'Adres (pełny)'.", 10, False),
        ("Status kontaktu — puste pole do ręcznego zaznaczenia (rozwijana lista), czysto do Twojego użytku,", 10, False),
        ("  narzędzie tego nie odczytuje ani nie nadpisuje.", 10, False),
        ("Uzasadnienie werdyktu — każda linia kończy się '[źródło danych: ...]': otodom_json/olx_api = dane", 10, False),
        ("  strukturalne (wysoka pewność), html_regex = wyciągnięte z tekstu strony (niższa pewność).", 10, False),
        ("Strona dewelopera / Status strony — wyszukana strona firmowa inwestora (Brave Search), NIGDY dla", 10, False),
        ("  osób fizycznych (zbyt duże ryzyko trafienia w nie tę osobę). Status: potwierdzona (NIP inwestora", 10, False),
        ("  znaleziony w treści strony) / prawdopodobna (nazwa domeny zawiera markę inwestora, bez NIP na", 10, False),
        ("  stronie) / kandydat_niepewny (samo wystąpienie nazwy w wynikach wyszukiwania, bez potwierdzenia", 10, False),
        ("  domeną — link pokazany jako zwykły tekst do ręcznej weryfikacji, CELOWO nieklikalny) / brak", 10, False),
        ("  (osoba fizyczna, nie szukano) / nie znaleziono. Klikalny link TYLKO dla potwierdzona/prawdopodobna.", 10, False),
        ("", 10, False),
        ("SCORING korzysta teraz z werdyktów (wcześniej nie korzystał — patrz docs/AUDYT.md):", 11, True),
        ("• Werdykt CONFIRMED odejmuje punkty (inwestycja już się reklamuje — to przeciwieństwo przewagi",  10, False),
        ("  'zanim zaczną marketing', która jest sensem tego narzędzia).", 10, False),
        ("• Seryjny inwestor (≥3 wnioski w RWDZ) i działka należąca do spółki (ewidencja gruntów) dodają", 10, False),
        ("  punkty — działają NIEZALEŻNIE od tego, czy RWDZ ma wypełnioną nazwę inwestora.", 10, False),
    ]
    for i, (text, size, bold) in enumerate(L, start=2):
        c = lg.cell(row=i, column=2, value=text)
        c.font = Font(name=FONT, size=size, bold=bold, color=C_HEAD if bold else "333333")
    lg.column_dimensions["B"].width = 110

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    print(f"zapisano: {out_path} ({len(data)} leadow)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    status = "scored"
    recheck_live = True
    for a in sys.argv[1:]:
        if a.startswith("--status="):
            status = a.split("=", 1)[1]
        if a == "--no-recheck-live":
            # pomija swieza weryfikacje zywotnosci linkow (Zadanie 1.4) — tylko
            # do szybkich testow/iteracji; w normalnym uzyciu zostaw wlaczone
            recheck_live = False
    out = Path(args[0]) if args else ROOT / "output" / "dev_scout_raport.xlsx"
    build(out, status, recheck_live=recheck_live)
