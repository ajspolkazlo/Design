"""
Weryfikacja dopasowania lead RWDZ <-> ogloszenie na portalu, wielopoziomowa.

Problem, ktory ten modul rozwiazuje (zweryfikowany na zywo, lipiec 2026):
dopasowanie tekstowe "ulica + miejscowosc" znajduje ogloszenia PRZY TEJ SAMEJ
ULICY, ale nie gwarantuje, ze to TA SAMA inwestycja. Realne przypadki z probki
10 leadow z 2026:
  - Kobylka/Szeroka: trafione ogloszenie bylo odsprzedaza domu z RYNKU WTORNEGO
    wystawiona w 2020 (nasz wniosek: 2026), dom 100 m2 vs ~230 m2 z kubatury,
    dzialka 3899 m2 vs 1143 m2 z ewidencji — inna nieruchomosc przy tej samej ulicy.
  - Brwinow: pin ogloszenia lezal 1.8 km od dzialki z wniosku — inna inwestycja
    w tym samym miescie.
Zaden z tych przypadkow nie byl wykrywalny samym tekstem; kazdy jest wykrywalny
sygnalami OBIEKTYWNYMI ponizej.

=========================== SYGNALY (wszystkie darmowe) ===========================
1. GEOMETRIA: dokladne wspolrzedne ogloszenia (Otodom osadza je w JSON strony,
   OLX podaje zgrubne w API) vs poligon dzialki ewidencyjnej z ULDK.
   Pin w dzialce / <=150 m => silne potwierdzenie; > 2 km => odrzucenie.
2. PARAMETRY STRUKTURALNE OGLOSZENIA — TEN SAM zestaw sygnalow (market,
   data utworzenia, metraz, dzialka, wspolrzedne) wyciagany z KAZDEGO z 6
   portali, z najlepszego dostepnego zrodla per portal (zweryfikowane na
   zywo, 22.07.2026):
   - Otodom: __NEXT_DATA__ (JSON strony, Next.js) — pelny zestaw + wspolrzedne.
   - OLX: pola `params`/`map` z API /api/v1/offers.
   - Domiporta: JSON-LD schema.org RealEstateListing (datePosted, cena,
     itemOffered.floorSize, itemOffered.geo) — pelny zestaw + wspolrzedne.
   - RynekPierwotny: JSON-LD ApartmentComplex — adres i wspolrzedne CALEJ
     INWESTYCJI (portal grupuje oferty per inwestycja, nie per dom — to
     wlasciwy poziom szczegolowosci dla dopasowania do wniosku RWDZ).
     market="primary" na sztywno (caly portal to wylacznie rynek pierwotny).
   - Gratka/Morizon: brak wlasnego JSON-a dla pojedynczej oferty (ich
     JSON-LD/Nuxt payload na stronie oferty niesie dane "podobnych ofert",
     NIE oferty ktora sie ogladamy — pulapka zweryfikowana na zywo, nie
     dac sie na nia zlapac). Zamiast tego: uniwersalny meta-opis SEO
     (<meta property="og:description">) w formacie "NNN m² (pow. działki
     NNN m²)" — zweryfikowany na zywo jako IDENTYCZNY tekst dla tej samej
     nieruchomosci na obu portalach (wspolny wlasciciel, Grupa Domodi).
     Brak wspolrzednych z tego zrodla — geometria dla tych dwoch portali
     nadal opiera sie na ogolnym regexie jako ostatniej desce ratunku.
   Wszystkie znaczniki: market: primary/secondary — rynek WTORNY nie moze byc
   nowa inwestycja z wniosku; data utworzenia vs data wplywu wniosku;
   metraz vs widelki z kubatury RWDZ (kubatura / 5.5 ... / 4.0); dzialka z
   ogloszenia vs urzedowa z ewidencji gruntow.
   WAZNE (zweryfikowane na zywo): oferta pod zapamietanym URL-em moze
   WYGASNAC i portal CICHO PRZEKIEROWUJE na strone kategorii — bez
   sprawdzenia, ze finalny URL nadal jest konkretnym ogloszeniem (patrz
   fetch_html_facts/fetch_otodom_facts), wyciagnelibysmy dane zupelnie innej,
   przypadkowej oferty i podpisali je pod naszym leadem.
3. EWIDENCJA GRUNTOW (KIEG WMS, GUGiK — publiczna usluga panstwowa):
   - urzedowa powierzchnia dzialki (dokladniejsza niz nasz wlasny centroid/Shoelace)
   - GRUPA REJESTROWA wlasciciela: 7 = osoba fizyczna, 15 = spolka prawa
     handlowego itd. Bez danych osobowych — sama kategoria. Kluczowe dla ~88%
     leadow bez nazwy inwestora w RWDZ: odroznia "firma buduje" od "prywatny dom".
     Zweryfikowane na probce: 9/9 zgodnosci z obecnoscia/brakiem spolki w RWDZ.
4. SERYJNOSC INWESTORA: liczba wnioskow tego samego inwestora w CALYM zrzucie
   RWDZ (mamy go lokalnie — zero kosztu). Seryjny inwestor = prawie na pewno
   deweloper. Zweryfikowane: "M4 Sp. z o.o." (nierozpoznawalna w KRS przez
   generyczna nazwe) ma 31 wnioskow w pasie Kady/Zyrardow/Brwinow/Grodzisk —
   jednoznacznie seryjny lokalny deweloper. Liczniki budowane przy `run`
   (step_parse_and_filter) i zapisywane do data/investor_counts.json.

============================ WERDYKT ============================
Per dopasowany portal: CONFIRMED / LIKELY / REVIEW / REJECTED + lista powodow
po polsku (do kolumny w Excelu). Per lead: najlepszy werdykt z portali;
dopasowania REJECTED sa usuwane z found_on (ogloszenie o INNEJ nieruchomosci
nie jest dowodem, ze NASZA inwestycja jest na portalu).
Progi w config.yaml -> verify (patrz DEFAULTS nizej).
"""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import requests

from src import cadastral

log = logging.getLogger(__name__)

KIEG_WMS_URL = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
INVESTOR_COUNTS_FILE = "investor_counts.json"  # w data/, obok bazy

# Grupy rejestrowe EGiB (kategorie wlascicieli gruntow — dane publiczne, bez nazwisk)
EGIB_GROUPS = {
    "1": "Skarb Państwa",
    "4": "gmina",
    "5": "gminna osoba prawna",
    "7": "osoba fizyczna",
    "8": "spółdzielnia",
    "11": "powiat",
    "13": "województwo",
    "15": "spółka prawa handlowego",
}

DEFAULTS = {
    "confirm_distance_m": 150,   # pin <= tego progu = potwierdzenie geograficzne
    "likely_distance_m": 700,    # rozmycie pinu / sasiedztwo
    "reject_distance_m": 2000,   # dalej niz to = inna lokalizacja
    "kubatura_div_lo": 4.0,      # widelki pow. uzytkowej: kubatura/5.5 .. kubatura/4.0
    "kubatura_div_hi": 5.5,      # (kalibracja na realnych parach z probki 2026)
    "listing_age_tolerance_days": 120,  # ogloszenie starsze od wniosku o wiecej = inna nieruchomosc
    "serial_investor_min": 3,    # tyle wnioskow w RWDZ = "seryjny inwestor"
}

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# cache per-run (proces enrichu) — te same dzialki/inwestorzy nie sa odpytywani 2x
_parcel_cache: dict[str, dict] = {}
_investor_counts: dict[str, int] | None = None


def _norm(text: str) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    out = "".join(c for c in normalized if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", out).strip()


def _investor_key(text: str) -> str:
    """Klucz do licznikow seryjnosci: agresywniejszy niz _norm — usuwa kropki,
    przecinki i spacje, zeby warianty pisowni tej samej spolki ("M4 Sp. z o.o."
    vs "M4 Sp. z o. o." vs "M4Sp. z o.o.") liczyly sie razem. Zweryfikowane na
    realnym zrzucie: kazda wieksza spolka wystepuje w RWDZ w kilku wariantach."""
    return re.sub(r"[.,\s]+", "", _norm(text))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * r * asin(sqrt(a))


def _point_in_polygon(lat: float, lon: float, poly_lonlat: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly_lonlat)
    j = n - 1
    for i in range(n):
        xi, yi = poly_lonlat[i]
        xj, yj = poly_lonlat[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


# ------------------------- liczniki seryjnosci inwestora -------------------------

def build_investor_counts(raw_df, data_dir: Path) -> None:
    """Wolane raz przy `run` (step_parse_and_filter) na PELNYM, jeszcze
    nieodfiltrowanym zbiorze RWDZ. Zapisuje liczniki wnioskow per inwestor
    (znormalizowana nazwa) do data/investor_counts.json. Trzymamy tylko
    liczniki >= 2 — brak wpisu przy odczycie oznacza 1 wniosek."""
    col = None
    for c in raw_df.columns:
        if "inwestor" in str(c).lower():
            col = c
            break
    if col is None:
        log.warning("build_investor_counts: brak kolumny inwestora w zrzucie RWDZ")
        return
    counts: dict[str, int] = {}
    for v in raw_df[col].dropna():
        k = _investor_key(str(v))
        if k:
            counts[k] = counts.get(k, 0) + 1
    slim = {k: v for k, v in counts.items() if v >= 2}
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / INVESTOR_COUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False)
    log.info("Zapisano liczniki seryjnosci: %d inwestorow z >=2 wnioskami", len(slim))


def investor_serial_count(inwestor: str | None, data_dir: Path) -> int:
    """Ile wnioskow ma ten inwestor w calym zrzucie RWDZ (1 gdy brak w licznikach)."""
    global _investor_counts
    if not inwestor:
        return 0
    if _investor_counts is None:
        path = data_dir / INVESTOR_COUNTS_FILE
        try:
            with open(path, encoding="utf-8") as f:
                _investor_counts = json.load(f)
        except (OSError, json.JSONDecodeError):
            log.warning("Brak %s — uruchom `run`, zeby zbudowac liczniki seryjnosci", path)
            _investor_counts = {}
    return _investor_counts.get(_investor_key(inwestor), 1)


# ------------------------- ewidencja gruntow (ULDK + KIEG) -------------------------

def parcel_official(parcel_id: str) -> dict:
    """Urzedowe dane dzialki: poligon WGS84 (ULDK), centroid w PUWG1992,
    powierzchnia z ewidencji [m2] i grupa rejestrowa wlasciciela (KIEG WMS).
    Wynik cache'owany per proces. Wszystkie pola moga byc None (brak danych
    nie moze wywracac enrichu)."""
    if parcel_id in _parcel_cache:
        return _parcel_cache[parcel_id]
    out: dict = {"polygon_wgs84": None, "area_m2": None, "owner_group": None, "owner_desc": None}

    # 1) poligon WGS84 (do point-in-polygon) — przez istniejacy cadastral
    try:
        resp = requests.get(
            cadastral.ULDK_URL,
            params={"request": "GetParcelById", "id": parcel_id, "result": "geom_wkt", "srid": 4326},
            headers={"User-Agent": "dev-scout/0.1"}, timeout=15,
        )
        lines = resp.text.strip().split("\n")
        if lines and lines[0].strip() == "0" and len(lines) > 1:
            out["polygon_wgs84"] = cadastral._parse_wkt_polygon(lines[1]) or None
    except requests.RequestException:
        log.warning("ULDK WGS84 nie odpowiada dla %r", parcel_id)

    # 2) centroid w EPSG:2180 (metry) — potrzebny do zapytania WMS
    cx = cy = None
    try:
        resp = requests.get(
            cadastral.ULDK_URL,
            params={"request": "GetParcelById", "id": parcel_id, "result": "geom_wkt", "srid": 2180},
            headers={"User-Agent": "dev-scout/0.1"}, timeout=15,
        )
        lines = resp.text.strip().split("\n")
        if lines and lines[0].strip() == "0" and len(lines) > 1:
            m = re.search(r"\(\(([^)]+)\)", lines[1])
            if m:
                pts = [tuple(map(float, p.strip().split()[:2])) for p in m.group(1).split(",")]
                cx = sum(p[0] for p in pts) / len(pts)
                cy = sum(p[1] for p in pts) / len(pts)
    except requests.RequestException:
        pass

    # 3) KIEG WMS GetFeatureInfo — urzedowa powierzchnia + grupa rejestrowa.
    #    UWAGA: WMS 1.1.1 + EPSG:2180, nie 1.3.0+CRS:84 — tamta kombinacja
    #    zwraca pusty szablon (zweryfikowane na zywo).
    if cx is not None:
        try:
            d = 30
            resp = requests.get(
                KIEG_WMS_URL,
                params={
                    "SERVICE": "WMS", "REQUEST": "GetFeatureInfo", "VERSION": "1.1.1",
                    "LAYERS": "dzialki", "QUERY_LAYERS": "dzialki", "SRS": "EPSG:2180",
                    "BBOX": f"{cx-d},{cy-d},{cx+d},{cy+d}",
                    "WIDTH": 101, "HEIGHT": 101, "X": 50, "Y": 50,
                    "INFO_FORMAT": "text/html", "FEATURE_COUNT": 3,
                },
                headers={"User-Agent": "dev-scout/0.1"}, timeout=20,
            )
            vals = dict(re.findall(r"<td>([^<]*)</td><td>([^<]*)</td>", resp.text))
            for k, v in vals.items():
                if "Pole pow" in k and v.strip():
                    try:
                        out["area_m2"] = round(float(v) * 10000)
                    except ValueError:
                        pass
                if "Grupa" in k and v.strip():
                    out["owner_group"] = v.strip()
                    out["owner_desc"] = EGIB_GROUPS.get(v.strip(), f"grupa {v.strip()}")
        except requests.RequestException:
            log.warning("KIEG WMS nie odpowiada dla %r", parcel_id)

    _parcel_cache[parcel_id] = out
    return out


# ------------------------- dane strukturalne ogloszen -------------------------

@dataclass
class ListingFacts:
    """Znormalizowane fakty z ogloszenia — z JSON-a strony (Otodom), parametrow
    API (OLX), JSON-LD schema.org (Domiporta/RynekPierwotny), uniwersalnego
    meta-opisu SEO (Gratka/Morizon) albo regexow na HTML (ostatnia deska
    ratunku, gdy nic z powyzszego nie zadziala — nizsza pewnosc)."""
    source: str = ""                   # np. "otodom_json" / "domiporta_ldjson" / "gratka_meta_description" / "html_regex"
    market: str | None = None          # "primary" / "secondary"
    created_at: str | None = None      # ISO data utworzenia ogloszenia
    area_m2: float | None = None       # pow. uzytkowa domu/lokalu
    terrain_m2: float | None = None    # pow. dzialki wg ogloszenia
    build_year: int | None = None
    lat: float | None = None
    lon: float | None = None
    coords_precise: bool = False       # OLX rozmywa pin — wtedy False
    advertiser: str | None = None      # "business"/"private"/"agency"
    is_rental: bool = False            # ogloszenie WYNAJMU (nie sprzedaz) — nigdy nie nasz lead
    dead: bool = False                 # link wygasl/przekierowal poza oferte (nieaktualne ogloszenie)


# Zwracany, gdy URL ogloszenia przekierowal poza konkretna oferte (wygasl) —
# ODROZNIENIE od None (strona zywa, ale nie dalo sie sparsowac danych). None ->
# werdykt REVIEW ("tylko dopasowanie tekstowe"), DEAD_LINK -> REJECTED
# ("ogloszenie nieaktualne"). Bez tego rozroznienia martwy link szedl jako
# REVIEW i pokazywal sie w Excelu jako klikalne "ogloszenie" prowadzace donikad.
def _dead_link() -> "ListingFacts":
    return ListingFacts(source="dead_link", dead=True)


def fetch_otodom_facts(url: str, timeout: int = 20) -> ListingFacts | None:
    """Pelny strukturalny JSON oferty Otodom (__NEXT_DATA__). Zweryfikowane na
    zywo: market, createdAt, Area, Terrain_area, Build_year, wspolrzedne.
    Tag <script> ma dodatkowe atrybuty (crossorigin) — regex musi byc luzny."""
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
    except requests.RequestException:
        return None
    from src import portal_check  # import tutaj — unika cyklu importu na poziomie modulu
    if not portal_check._is_individual_listing("otodom", resp.url):
        log.info("Ogloszenie %s przekierowalo poza konkretna oferte (%s) — prawdopodobnie wygaslo, pomijam", url, resp.url)
        return _dead_link()
    body = resp.text
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', body, re.S)
    if not m:
        return None
    try:
        ad = json.loads(m.group(1))["props"]["pageProps"]["ad"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    t = ad.get("target", {}) or {}
    loc = (ad.get("location", {}) or {}).get("coordinates", {}) or {}

    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # target.OfferType = "sprzedaz" / "wynajem" — autorytatywne pole Otodom
    # (pewniejsze niz slowo w URL/tytule). Wynajem = nie nasza inwestycja.
    offer_type = (t.get("OfferType") or "").lower()
    facts = ListingFacts(
        source="otodom_json",
        market=(ad.get("market") or "").lower() or None,
        created_at=ad.get("createdAt"),
        area_m2=_f(t.get("Area")),
        terrain_m2=_f(t.get("Terrain_area")),
        build_year=int(t["Build_year"]) if str(t.get("Build_year") or "").isdigit() else None,
        lat=_f(loc.get("latitude")), lon=_f(loc.get("longitude")),
        coords_precise=True,
        advertiser=ad.get("advertiserType"),
        is_rental=(offer_type == "wynajem"),
    )
    if facts.lat is None:
        mlat = re.search(r'"latitude"\s*:\s*(-?\d{1,2}\.\d{3,})', body)
        mlon = re.search(r'"longitude"\s*:\s*(-?\d{1,2}\.\d{3,})', body)
        if mlat and mlon:
            facts.lat, facts.lon = float(mlat.group(1)), float(mlon.group(1))
    return facts


def olx_facts_from_offer(offer: dict) -> ListingFacts:
    """Fakty z surowej odpowiedzi OLX /api/v1/offers — przekazywane z
    portal_check._check_olx w momencie dopasowania (zero dodatkowych zapytan).
    UWAGA: OLX celowo rozmywa wspolrzedne (map.show_detailed=False, pin na
    poziomie centrum miasta) — coords_precise=False, uzywamy ich tylko
    wspierajaco, nigdy do odrzucania."""
    params = {}
    for p in offer.get("params", []) or []:
        val = p.get("value") or {}
        params[p.get("key")] = val.get("key") or val.get("label")

    def _f(v):
        try:
            return float(str(v).replace(",", "."))
        except (TypeError, ValueError):
            return None

    mp = offer.get("map") or {}
    return ListingFacts(
        source="olx_api",
        market=params.get("market"),
        created_at=offer.get("created_time"),
        area_m2=_f(params.get("m")),
        terrain_m2=_f(params.get("area")),
        build_year=int(params["rok_budowy"]) if str(params.get("rok_budowy") or "").isdigit() else None,
        lat=_f(mp.get("lat")), lon=_f(mp.get("lon")),
        coords_precise=bool(mp.get("show_detailed")),
        advertiser="business" if offer.get("business") else "private",
    )


_HTML_AREA_RE = re.compile(
    r'(?:powierzchnia(?:\s+(?:domu|uzytkowa|użytkowa|całkowita|calkowita))?)[^0-9]{0,25}(\d{2,4}(?:[.,]\d{1,2})?)\s*(?:m|²)',
    re.I)
_HTML_TERRAIN_RE = re.compile(
    r'(?:powierzchnia\s+dzia[łl]ki|dzia[łl]ka)[^0-9]{0,25}(\d{2,5}(?:[.,]\d{1,2})?)\s*(?:m|²|ar)',
    re.I)

# "296 m² (pow. działki 1 224 m²) za 1 599 000 zł" — format meta description
# (og:description / <meta name="description">) uzywany PRZEZ WIELE portali dla
# SEO. To zdanie opisuje strone, na ktorej sie znajdujemy (nie inne oferty w
# okolicy jak komponenty "podobne oferty" w reszcie strony) — zweryfikowane na
# zywo na Gratka i Morizon: IDENTYCZNY tekst (ten sam adres, ten sam numer
# oferty w nawiasie) dla tej samej nieruchomosci wystawionej na obu portalach
# (wspolny wlasciciel/system — Grupa Domodi). Liczby moga byc rozdzielone
# zwykla spacja albo NBSP (\xa0) — [\d\s]. wystarcza (\s w Pythonie obejmuje NBSP).
_META_AREA_PLOT_RE = re.compile(
    r'(\d[\d\s]{0,6})\s*m²\s*\(pow\.\s*działki\s*(\d[\d\s]{0,7})\s*m²\)', re.I)


def _meta_content(body: str, key: str) -> str | None:
    """Wartosc <meta name=".."/property=".." content="..">, niezaleznie od
    KOLEJNOSCI atrybutow w znaczniku (zweryfikowane na zywo: Morizon i Gratka
    ukladaja je inaczej — raz property przed content, raz po)."""
    for tag_match in re.finditer(r"<meta\b[^>]*>", body):
        tag = tag_match.group(0)
        if f'"{key}"' not in tag:
            continue
        m = re.search(r'content="([^"]*)"', tag)
        if m:
            return html.unescape(m.group(1))
    return None


def _facts_from_meta_description(body: str) -> ListingFacts | None:
    """Uniwersalny fallback (dziala TAM, gdzie portal uzywa standardowego
    formatu SEO-opisu) — nie jest specyficzny dla jednego portalu, wiec
    proboway go dla kazdego, u ktorego nie mamy dedykowanego parsera JSON-LD."""
    desc = _meta_content(body, "og:description") or _meta_content(body, "description")
    if not desc:
        return None
    m = _META_AREA_PLOT_RE.search(desc)
    if not m:
        return None
    area = float(re.sub(r"\s", "", m.group(1)))
    terrain = float(re.sub(r"\s", "", m.group(2)))
    return ListingFacts(source="meta_description", area_m2=area, terrain_m2=terrain)


def _parse_ld_json_blocks(body: str) -> list[dict]:
    """Wszystkie poprawne bloki <script type="application/ld+json"> na stronie."""
    blocks = []
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', body, re.S):
        try:
            blocks.append(json.loads(m.group(1)))
        except (json.JSONDecodeError, TypeError):
            continue
    return blocks


def _urls_match(a: str | None, b: str) -> bool:
    return bool(a) and a.rstrip("/") == b.rstrip("/")


def _facts_from_domiporta(body: str, expected_url: str) -> ListingFacts | None:
    """Domiporta osadza pelny schema.org RealEstateListing (JSON-LD) —
    datePosted, cena, itemOffered.floorSize, itemOffered.geo — zweryfikowane
    na zywo na realnej ofercie. WAZNE: sprawdzamy, ze blok.url zgadza sie z
    zadanym URL-em, zanim zaufamy danym — ten sam wzorzec bloku bywa uzywany
    tez na stronach kategorii z innym url."""
    for d in _parse_ld_json_blocks(body):
        if d.get("@type") != "RealEstateListing" or not _urls_match(d.get("url"), expected_url):
            continue
        item = d.get("itemOffered") or {}
        geo = item.get("geo") or {}
        floor = item.get("floorSize") or {}
        lat, lon = geo.get("latitude"), geo.get("longitude")
        return ListingFacts(
            source="domiporta_ldjson",
            created_at=d.get("datePosted"),
            area_m2=floor.get("value"),
            build_year=item.get("yearBuilt"),
            lat=lat, lon=lon,
            coords_precise=lat is not None,
        )
    return None


def _facts_from_rynekpierwotny(body: str, expected_url: str) -> ListingFacts | None:
    """RynekPierwotny grupuje oferty PER INWESTYCJA (nie per pojedynczy dom) —
    zweryfikowane na zywo: JSON-LD ApartmentComplex daje precyzyjne
    wspolrzedne i adres calej inwestycji, co jest wlasciwym poziomem
    szczegolowosci dla dopasowania do wniosku RWDZ (jeden wniosek = jedna
    inwestycja). market='primary' na sztywno — caly portal to WYLACZNIE
    rynek pierwotny, to fakt o portalu, nie zgadywanie o konkretnej ofercie.
    Blok nie ma pelnego URL (tylko sciezke wzgledna), wiec dopasowanie po
    sciezce, nie identycznosci calego stringa."""
    try:
        expected_path = re.sub(r"^https?://[^/]+", "", expected_url).rstrip("/")
    except Exception:
        expected_path = expected_url
    for d in _parse_ld_json_blocks(body):
        if d.get("@type") != "ApartmentComplex":
            continue
        rel_url = (d.get("url") or "").rstrip("/")
        if rel_url and rel_url != expected_path:
            continue
        geo = d.get("geo") or {}
        lat, lon = geo.get("latitude"), geo.get("longitude")
        return ListingFacts(
            source="rynekpierwotny_ldjson", market="primary",
            lat=lat, lon=lon, coords_precise=lat is not None,
        )
    return None


# Dysponenci strukturalni per portal (poza Otodom/OLX, ktore maja wlasne
# dedykowane funkcje wyzej) — zweryfikowani na zywo na realnych ofertach.
_STRUCTURED_EXTRACTORS = {
    "domiporta": _facts_from_domiporta,
    "rynekpierwotny": _facts_from_rynekpierwotny,
}


def fetch_html_facts(portal: str, url: str, timeout: int = 20) -> ListingFacts | None:
    """Fakty dla portali bez dedykowanej funkcji jak fetch_otodom_facts/
    olx_facts_from_offer. Kolejnosc prob: (1) strukturalny JSON-LD gdy portal
    go ma i zgadza sie z URL-em (Domiporta/RynekPierwotny), (2) uniwersalny
    meta-opis SEO (dziala dla Gratka/Morizon — ten sam string na obu, patrz
    _META_AREA_PLOT_RE), (3) regexy na calym HTML jako ostatnia deska ratunku.

    WAZNE, zweryfikowane na zywo (22.07.2026): dwa z trzech testowych URL-i z
    wczesniejszej sesji (Gratka, Morizon) okazaly sie NIEAKTUALNE i po prostu
    PRZEKIEROWALY na strone kategorii (oferta wygasla/usunieta) — bez
    sprawdzenia response.url wzgledem wzorca "to jest konkretne ogloszenie"
    wyciagnelibysmy dane INNEJ, przypadkowej oferty z tej kategorii i
    podpisali je pod naszym leadem. To gorsze niz brak danych."""
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
    except requests.RequestException:
        return None
    from src import portal_check  # import tutaj, nie na gorze modulu — unika cyklu importu
    if not portal_check._is_individual_listing(portal, resp.url):
        log.info("Ogloszenie %s przekierowalo poza konkretna oferte (%s) — prawdopodobnie wygaslo, pomijam", url, resp.url)
        return _dead_link()
    if portal_check._is_rental(resp.url):  # wynajem po finalnym URL — nie nasz lead
        return ListingFacts(source=f"{portal}_html", is_rental=True)
    body = resp.text

    extractor = _STRUCTURED_EXTRACTORS.get(portal)
    facts = extractor(body, resp.url) if extractor else None

    meta_facts = _facts_from_meta_description(body)
    if meta_facts:
        if facts is None:
            facts = meta_facts
            facts.source = f"{portal}_meta_description"
        else:
            # dopelnij strukturalne dane o metraz/dzialke, jesli ich brakowalo
            if facts.area_m2 is None:
                facts.area_m2 = meta_facts.area_m2
            if facts.terrain_m2 is None:
                facts.terrain_m2 = meta_facts.terrain_m2

    if facts is None:
        facts = ListingFacts(source="html_regex")
        m = _HTML_AREA_RE.search(body)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 10 <= v <= 9999:
                facts.area_m2 = v
        m = _HTML_TERRAIN_RE.search(body)
        if m:
            v = float(m.group(1).replace(",", "."))
            if 50 <= v <= 99999:
                facts.terrain_m2 = v
        mlat = re.search(r'"lat(?:itude)?"\s*:\s*(-?\d{1,2}\.\d{3,})', body)
        mlon = re.search(r'"l(?:on|ng)(?:gitude)?"\s*:\s*(-?\d{1,2}\.\d{3,})', body)
        if mlat and mlon:
            facts.lat, facts.lon = float(mlat.group(1)), float(mlon.group(1))
            facts.coords_precise = True
        if facts.area_m2 is None and facts.terrain_m2 is None and facts.lat is None:
            return None

    return facts


# ------------------------------- werdykt -------------------------------

VERDICT_ORDER = ["CONFIRMED", "LIKELY", "REVIEW", "REJECTED"]


@dataclass
class MatchVerdict:
    portal: str
    url: str
    verdict: str                       # CONFIRMED / LIKELY / REVIEW / REJECTED
    reasons: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)


def kubatura_band(kubatura, cfg: dict) -> tuple[float, float] | None:
    """Widelki pow. uzytkowej [m2] z kubatury [m3]. None dla brakow i
    placeholderow (kubatura <= 5 m3 to nie jest realny budynek)."""
    try:
        k = float(kubatura)
    except (TypeError, ValueError):
        return None
    if k <= 5:
        return None
    return (k / cfg["kubatura_div_hi"], k / cfg["kubatura_div_lo"])


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def judge_match(
    portal: str,
    url: str,
    facts: ListingFacts | None,
    lead: dict,
    parcel: dict,
    cfg: dict,
) -> MatchVerdict:
    """Laczy sygnaly w werdykt dla JEDNEGO dopasowania portalowego.
    lead: kubatura (float|None), data_wniosku (str|None), lat/lon centroidu
    dzialki (float|None), investor_confirmed (bool).
    parcel: wynik parcel_official() (moze byc pusty dict)."""
    reasons: list[str] = []
    pluses = 0
    hard_reject = False
    geo_confirmed = False

    # Twarde odrzucenia PRZED cala reszta — link nieaktualny albo wynajem to nie
    # jest "slabe dopasowanie do rozwazenia", tylko "to na pewno nie nasz lead".
    if facts is not None and facts.dead:
        return MatchVerdict(portal, url, "REJECTED",
                            ["ogłoszenie nieaktualne — link wygasł lub przekierował poza konkretną ofertę"],
                            {"source": facts.source})
    if facts is not None and facts.is_rental:
        return MatchVerdict(portal, url, "REJECTED",
                            ["ogłoszenie dotyczy WYNAJMU, nie sprzedaży — nowa inwestycja z pozwolenia jest na sprzedaż"],
                            {"source": facts.source})

    if facts is None:
        return MatchVerdict(portal, url, "REVIEW", ["brak danych strukturalnych ogłoszenia — tylko dopasowanie tekstowe"], {})

    # --- geometria ---
    dist_m = None
    if facts.lat is not None and lead.get("lat") is not None:
        dist_m = _haversine_m(facts.lat, facts.lon, lead["lat"], lead["lon"])
        in_poly = bool(parcel.get("polygon_wgs84")) and _point_in_polygon(
            facts.lat, facts.lon, parcel["polygon_wgs84"])
        if facts.coords_precise:
            if in_poly:
                geo_confirmed = True
                reasons.append("pin ogłoszenia leży W GRANICACH działki z wniosku")
            elif dist_m <= cfg["confirm_distance_m"]:
                geo_confirmed = True
                reasons.append(f"pin ogłoszenia ~{dist_m:.0f} m od działki (≤{cfg['confirm_distance_m']} m)")
            elif dist_m <= cfg["likely_distance_m"]:
                reasons.append(f"pin ~{dist_m:.0f} m od działki — sąsiedztwo/rozmycie pinu")
                pluses += 1
            elif dist_m > cfg["reject_distance_m"]:
                hard_reject = True
                reasons.append(f"pin ogłoszenia ~{dist_m/1000:.1f} km od działki z wniosku — INNA lokalizacja")
            else:
                # strefa "watpliwa" (likely_distance_m .. reject_distance_m): za
                # daleko na "sasiedztwo", za blisko na pewne odrzucenie — bez tej
                # galezi dystans w tym przedziale znikal calkowicie z powodow
                # (zero informacji), mimo ze to WAZNY sygnal ostrzegawczy.
                reasons.append(f"pin ~{dist_m/1000:.2f} km od działki z wniosku — prawdopodobnie INNA nieruchomość w tej samej miejscowości")
                pluses -= 1
        else:
            # zgrubny pin (OLX): tylko wspierajaco, nigdy do odrzucenia
            if dist_m <= cfg["likely_distance_m"]:
                pluses += 1
                reasons.append(f"zgrubny pin OLX ~{dist_m:.0f} m — zgodny rejon")

    # --- rynek pierwotny/wtorny ---
    if facts.market == "secondary":
        hard_reject = True
        reasons.append("ogłoszenie z RYNKU WTÓRNEGO — nie może być nową inwestycją z wniosku")
    elif facts.market == "primary":
        pluses += 1
        reasons.append("rynek pierwotny")

    # --- czas: ogloszenie vs wniosek ---
    created = _parse_dt(facts.created_at)
    wniosek = _parse_dt(lead.get("data_wniosku"))
    if created and wniosek:
        if created < wniosek - timedelta(days=cfg["listing_age_tolerance_days"]):
            months = int((wniosek - created).days / 30)
            reasons.append(f"ogłoszenie starsze od wniosku o ~{months} mies. — możliwa wcześniejsza faza/inna nieruchomość")
            # celowo NIE hard_reject: seryjni deweloperzy prowadza sprzedaz
            # faz rownolegle; to demota do REVIEW, chyba ze geometria potwierdza
        else:
            pluses += 1
            reasons.append("ogłoszenie nie starsze niż wniosek (spójny czas)")

    # --- metraz vs kubatura ---
    band = kubatura_band(lead.get("kubatura"), cfg)
    if band and facts.area_m2:
        lo, hi = band
        if lo * 0.9 <= facts.area_m2 <= hi * 1.1:
            pluses += 1
            reasons.append(f"metraż {facts.area_m2:.0f} m² w widełkach z kubatury ({lo:.0f}–{hi:.0f} m²)")
        elif facts.area_m2 < lo * 0.55 or facts.area_m2 > hi * 1.8:
            reasons.append(f"metraż {facts.area_m2:.0f} m² MOCNO poza widełkami z kubatury ({lo:.0f}–{hi:.0f} m²)")
            pluses -= 1
        # posrednie rozjazdy: bez kary — kubatura bywa dla calego zamierzenia (kilka budynkow)

    # --- dzialka vs ewidencja ---
    if facts.terrain_m2 and parcel.get("area_m2"):
        ratio = facts.terrain_m2 / parcel["area_m2"]
        if 0.7 <= ratio <= 1.3:
            pluses += 1
            reasons.append(f"powierzchnia działki z ogłoszenia ({facts.terrain_m2:.0f} m²) zgodna z ewidencją ({parcel['area_m2']} m²)")
        elif ratio > 3.0 or ratio < 0.15:
            reasons.append(f"działka z ogłoszenia ({facts.terrain_m2:.0f} m²) wyraźnie inna niż w ewidencji ({parcel['area_m2']} m²)")
            pluses -= 1
        # 0.15-0.7 i 1.3-3.0: neutralne — deweloperzy dziela dzialki na mniejsze

    # --- nazwa inwestora (przekazana z portal_check) ---
    if lead.get("investor_confirmed"):
        pluses += 1
        reasons.append("nazwa inwestora widoczna w treści ogłoszenia")

    # --- agregacja ---
    if hard_reject:
        verdict = "REJECTED"
    elif geo_confirmed and pluses >= 1:
        verdict = "CONFIRMED"
    elif geo_confirmed or pluses >= 2:
        verdict = "LIKELY"
    else:
        verdict = "REVIEW"

    facts_dict = {k: v for k, v in facts.__dict__.items() if v is not None and k != "polygon_wgs84"}
    return MatchVerdict(portal, url, verdict, reasons, facts_dict)


def best_verdict(verdicts: list[MatchVerdict]) -> str | None:
    """Najlepszy werdykt sposrod dopasowan (CONFIRMED > LIKELY > REVIEW >
    REJECTED). None gdy brak dopasowan."""
    if not verdicts:
        return None
    return min((v.verdict for v in verdicts), key=VERDICT_ORDER.index)
