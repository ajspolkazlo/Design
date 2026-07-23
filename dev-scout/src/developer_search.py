"""
Wyszukiwanie strony internetowej dewelopera/inwestora dla leadow ze
zidentyfikowana nazwa inwestora (Zadanie 3, lipiec 2026).

Cel: NIE lista kandydatow, JEDEN najlepiej oceniony wynik per lead, z jasnym
statusem pewnosci — nigdy nie udawac pewnosci, ktorej nie ma (stad 4-stopniowa
skala statusu zamiast prostego znaleziono/nie).

============================= PRZEPLYW =============================
1. Pomin calkowicie, gdy inwestor wyglada na OSOBE FIZYCZNA (brak sygnalow
   spolki w nazwie — te same sygnaly co filters.looks_like_company) — zbyt
   wysokie ryzyko falszywego trafienia (samo imie+nazwisko to za malo, zeby
   bezpiecznie znalezc "tej" osoby strone w internecie).
2. Dla spolek: do 3 wariantow zapytania do Brave Search, PRZERYWA na
   pierwszym, ktory daje wynik przechodzacy filtry ponizej (budzet zapytan).
3. Odrzuca domeny portali nieruchomosci (ta sama lista co portal_check.py) i
   krotka blocklist agregatorow/mediow z config.yaml. Facebook/LinkedIn/
   Instagram to fallback drugiej kategorii — nigdy glowny wynik.
4. Ranking: nazwa domeny zawiera fragment marki inwestora (fuzzy) = najwyzszy
   priorytet; nazwa inwestora w tytule/opisie wyniku = sredni.
5. Walidacja: pobiera strone glowna kandydata, szuka NIP/KRS (jesli znany z
   company_lookup) i/lub pelnej nazwy inwestora w tresci. Wynik:
   "potwierdzona" (NIP/KRS sie zgadza) / "prawdopodobna" (sama nazwa) /
   "kandydat_niepewny" (trafiono cos, walidacja sie nie powiodla, LUB
   kandydat to Facebook/LinkedIn/Instagram) / "brak_do_wyszukania_osoba_fizyczna"
   (krok 1) / "nie_znaleziono".
6. Cache trwaly (SQLite) po znormalizowanej nazwie — wynik pozytywny bez
   wygasania, "nie znaleziono" z TTL 30 dni (nazwa moze pozniej dostac strone).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CACHE_DB_PATH = ROOT / "data" / "developer_search_cache.sqlite3"

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY_ENV_VAR = "BRAVE_SEARCH_API_KEY"  # ta sama zmienna co portal_check.py
NOT_FOUND_TTL_DAYS = 30  # wynik "nie znaleziono" wygasa; "znaleziono" nie (patrz docstring modulu)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Portale nieruchomosci (ta sama lista co portal_check._PORTAL_DOMAINS) — te
# NIGDY nie sa strona dewelopera, tylko miejscem, gdzie deweloper reklamuje.
_PORTAL_DOMAINS = {"otodom.pl", "olx.pl", "rynekpierwotny.pl", "morizon.pl", "gratka.pl", "domiporta.pl"}

# Ogolne agregatory/media/rejestry — wynik z tych domen nigdy nie jest samą
# stroną dewelopera, tylko wzmianka o nim. Krotka, bo celem jest usunac
# oczywiste smieci, nie zbudowac wyczerpujaca liste.
_GENERIC_BLOCKLIST = {
    "wikipedia.org", "wikidata.org", "gpw.pl", "money.pl", "gazeta.pl",
    "onet.pl", "wp.pl", "interia.pl", "biznes.gov.pl", "rp.pl", "forbes.pl",
    "krs-online.com.pl", "aleo.com", "rejestr.io", "panoramafirm.pl",
    "pkt.pl", "biznesfirmy.pl", "google.com", "bing.com", "youtube.com",
}

# Fallback DRUGIEJ KATEGORII — nigdy glowny, potwierdzony wynik (patrz
# docstring modulu, krok 3).
_SOCIAL_FALLBACK_DOMAINS = {"facebook.com", "linkedin.com", "instagram.com"}

STATUS_CONFIRMED = "potwierdzona"
STATUS_LIKELY = "prawdopodobna"
STATUS_UNCERTAIN = "kandydat_niepewny"
STATUS_INDIVIDUAL = "brak_do_wyszukania_osoba_fizyczna"
STATUS_NOT_FOUND = "nie_znaleziono"


@dataclass
class DeveloperSite:
    investor: str
    url: str | None = None
    status: str = STATUS_NOT_FOUND
    matched_on: str | None = None  # np. "NIP w tresci strony" / "nazwa domeny" — do debugowania


def _norm(text: str) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


_LEGAL_FORM_RE = re.compile(
    r"\bsp\.?\s*z\s*o\.?\s*o\.?\b|\bspolka\s+z\s+ograniczona\s+odpowiedzialnoscia\b"
    r"|\bs\.?a\.?\b|\bsp\.?\s*k\.?\b|\bspolka\s+komandytowa\b|\bspolka\s+jawna\b|\bs\.?c\.?\b",
    re.IGNORECASE,
)


def core_name(investor: str) -> str:
    """Nazwa bez formy prawnej — sama marka do budowania zapytan/porownan
    domeny (ten sam wzorzec co portal_check.investor_core_name, powielony
    tutaj celowo — inny cel uzycia, nie warto sprzegac modulow dla jednej
    funkcji)."""
    v = _norm(investor)
    v = _LEGAL_FORM_RE.sub(" ", v)
    v = re.sub(r"[.,\"'()]", " ", v)
    return " ".join(t for t in v.split() if len(t) > 1)


def _load_company_signals() -> list[str]:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("investor_filter", {}).get("company_signals", [])


def _norm_tight(text: str) -> str:
    """Jak _norm, plus usuniecie kropek/spacji — patrz identyczny komentarz i
    zweryfikowany na zywo bug w filters._norm_tight ('M4 Sp. z o. o.' z
    dodatkowa spacja BLEDNIE klasyfikowane jako osoba fizyczna bez tej
    poprawki)."""
    return re.sub(r"[.\s]", "", _norm(text))


def is_individual(investor: str) -> bool:
    """Brak sygnalow spolki w nazwie -> traktujemy jako osobe fizyczna (ten
    sam zestaw sygnalow co filters.looks_like_company, odwrocony) — zbyt
    ryzykowne szukanie strony po samym imieniu i nazwisku."""
    if not investor or not investor.strip():
        return True
    v = _norm_tight(investor)
    signals = _load_company_signals()
    return not any(_norm_tight(sig) in v for sig in signals)


def _domain_of(url: str) -> str:
    import urllib.parse
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_blocked_domain(domain: str) -> bool:
    def _matches(d: str, s: set[str]) -> bool:
        return any(d == b or d.endswith("." + b) for b in s)
    return _matches(domain, _PORTAL_DOMAINS) or _matches(domain, _GENERIC_BLOCKLIST)


def _is_social_fallback(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in _SOCIAL_FALLBACK_DOMAINS)


def _query_variants(investor: str) -> list[str]:
    name = core_name(investor) or investor
    return [
        f'"{name}" deweloper',
        f'"{name}" inwestycja mieszkaniowa',
        f'"{name}" mieszkania na sprzedaż',
    ]


def _search_brave(query: str, api_key: str, timeout: int = 15) -> list[dict]:
    resp = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": query, "count": 10},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("web", {}).get("results", [])


def _rank_candidate(result: dict, name_core: str) -> tuple[int, str] | None:
    """(priorytet, powod) albo None gdy wynik nie nadaje sie na kandydata w
    ogole (portal/blocklist). Priorytet: 2 = domena zawiera marke (najwyzszy,
    JEDYNY dopuszczalny do statusu potwierdzona/prawdopodobna — patrz nizej),
    1 = nazwa w tytule/opisie (tylko kandydat_niepewny), 0 = social fallback.

    WAZNE, zweryfikowane na zywo (23.07.2026): dopasowanie po samym
    WYSTAPIENIU slow z nazwy w tekscie strony jest NIEWIARYGODNE, gdy nazwa
    inwestora sklada sie ze slow ogolnego jezyka — realny przypadek: "TOP
    INVESTMENT Sp. z o.o." (marka rzeczywista) trafilo w
    companiesmarketcap.com/.../largest-investment-companies-by-market-cap/,
    KOMPLETNIE niezwiazana strone o rynkach finansowych, bo fraza "top
    investment" (dokladnie w tej kolejnosci, sasiadujaco) naturalnie
    wystepuje w angielskim tekscie o "top investment opportunities" itp. —
    nawet wymog SASIEDZTWA slow (nie tylko niezaleznej obecnosci) tego NIE
    zlapal. Jedyny naprawde wiarygodny sygnal to NAZWA DOMENY zawierajaca
    marke — przypadkowa domena praktycznie nigdy nie zawiera akurat tego
    samego ciagu znakow. Dlatego priorytet 1 (samo wystapienie w tekscie)
    moze wyladowac WYLACZNIE jako kandydat_niepewny, nigdy wyzej."""
    url = result.get("url", "")
    if not url:
        return None
    domain = _domain_of(url)
    if _is_blocked_domain(domain):
        return None
    name_tokens = [t for t in name_core.split() if len(t) > 2]
    if not name_tokens:
        return None
    domain_flat = re.sub(r"[^a-z0-9]", "", domain)
    if _is_social_fallback(domain):
        blob = _norm(f"{result.get('title','')} {result.get('description','')}")
        if all(t in blob for t in name_tokens):
            return (0, "fallback społecznościowy")
        return None
    # WSZYSTKIE tokeny nazwy musza byc w domenie (nie wystarczy jeden z wielu —
    # zweryfikowane na zywo, ze "investment" samo w domenie "investmentgroup.pl"
    # to za slaby sygnal dla nazwy "TOP INVESTMENT", mimo ze "investment" ma
    # >=4 znaki). Dla nazw jednowyrazowych wymagamy dodatkowo dlugosci >=4, zeby
    # krotkie, generyczne slowo samo nie wystarczylo.
    if len(name_tokens) == 1:
        domain_evidence = len(name_tokens[0]) >= 4 and name_tokens[0] in domain_flat
    else:
        domain_evidence = all(t in domain_flat for t in name_tokens)
    if domain_evidence:
        return (2, "nazwa domeny zawiera markę inwestora")
    blob = _norm(f"{result.get('title','')} {result.get('description','')}")
    if all(t in blob for t in name_tokens):
        return (1, "nazwa inwestora w tytule/opisie wyniku (bez potwierdzenia domeną — niepewne)")
    return None


def _validate_nip(url: str, nip: str | None, timeout: int = 15) -> tuple[bool, str | None]:
    """(potwierdzone, powod). Sprawdza WYLACZNIE obecnosc NIP w tresci strony
    glownej kandydata — to jedyny sygnal wystarczajaco swoisty (10-cyfrowy
    numer), zeby SAMODZIELNIE podniesc status do 'potwierdzona'.

    Celowo NIE sprawdzamy tu samej pelnej nazwy inwestora w tresci jako
    niezaleznej podstawy potwierdzenia — to dokladnie ten sam blad, ktory
    zlapalismy na zywo w _rank_candidate (patrz jego docstring): nazwy
    zbudowane ze slow ogolnego jezyka (np. "TOP INVESTMENT") wystepuja na
    kompletnie niezwiazanych stronach. Dlatego dopasowanie samej nazwy w
    tresci moze co najwyzej wzmocnic 'matched_on' juz istniejacego kandydata
    z dowodem domenowym (priorytet 2), nigdy nie jest jedyna podstawa."""
    if not nip:
        return False, None
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return False, None
    nip_digits = re.sub(r"\D", "", nip)
    if nip_digits and nip_digits in re.sub(r"\D", "", resp.text):
        return True, "NIP w treści strony"
    return False, None


# ------------------------------- cache -------------------------------

def _cache_connect() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS developer_sites (
            name_key TEXT PRIMARY KEY,
            url TEXT,
            status TEXT,
            matched_on TEXT,
            checked_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    return conn


def _cache_get(conn: sqlite3.Connection, name_key: str) -> DeveloperSite | None:
    row = conn.execute(
        "SELECT url, status, matched_on, checked_at FROM developer_sites WHERE name_key = ?", (name_key,)
    ).fetchone()
    if row is None:
        return None
    url, status, matched_on, checked_at = row
    if status == STATUS_NOT_FOUND:
        try:
            checked_dt = datetime.fromisoformat(checked_at).replace(tzinfo=timezone.utc)
        except ValueError:
            return None  # data nie do sparsowania -> traktuj jak brak cache, odpytaj ponownie
        if datetime.now(timezone.utc) - checked_dt > timedelta(days=NOT_FOUND_TTL_DAYS):
            return None  # TTL wygasl — nazwa mogla pozniej dostac strone
    return DeveloperSite(investor=name_key, url=url, status=status, matched_on=matched_on)


def _cache_put(conn: sqlite3.Connection, name_key: str, site: DeveloperSite) -> None:
    conn.execute(
        """INSERT INTO developer_sites (name_key, url, status, matched_on, checked_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(name_key) DO UPDATE SET
             url=excluded.url, status=excluded.status, matched_on=excluded.matched_on,
             checked_at=excluded.checked_at""",
        (name_key, site.url, site.status, site.matched_on),
    )
    conn.commit()


# ------------------------------ glowna funkcja ------------------------------

def find_developer_site(investor: str, nip: str | None = None) -> DeveloperSite:
    """Punkt wejscia. `nip` opcjonalny (z company_lookup.CompanyInfo.nip,
    jesli akurat znany) — wzmacnia walidacje do statusu 'potwierdzona'."""
    if not investor or not investor.strip():
        return DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)
    if is_individual(investor):
        return DeveloperSite(investor=investor, status=STATUS_INDIVIDUAL)

    name_key = _norm(investor)
    conn = _cache_connect()
    try:
        cached = _cache_get(conn, name_key)
        if cached is not None:
            return DeveloperSite(investor=investor, url=cached.url, status=cached.status, matched_on=cached.matched_on)

        api_key = os.environ.get(BRAVE_API_KEY_ENV_VAR)
        if not api_key:
            # brak klucza — nie cache'ujemy (nie chcemy "nie_znaleziono" na 30 dni
            # tylko dlatego, ze dzis nie bylo klucza w srodowisku)
            return DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)

        name_c = core_name(investor)
        best: tuple[int, dict, str] | None = None  # (priorytet, result, powod)
        for query in _query_variants(investor):
            try:
                results = _search_brave(query, api_key)
            except requests.RequestException:
                log.warning("developer_search: zapytanie Brave nie powiodlo sie dla %r", query, exc_info=True)
                continue
            for r in results:
                ranked = _rank_candidate(r, name_c)
                if ranked is None:
                    continue
                priority, reason = ranked
                if best is None or priority > best[0]:
                    best = (priority, r, reason)
            if best is not None and best[0] >= 1:
                break  # wystarczajaco dobry wynik — nie odpytuj kolejnych wariantow (budzet)
            time.sleep(1.0)

        if best is None:
            site = DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)
            _cache_put(conn, name_key, site)
            return site

        priority, result, reason = best
        url = result.get("url")
        domain = _domain_of(url)
        if _is_social_fallback(domain):
            site = DeveloperSite(investor=investor, url=url, status=STATUS_UNCERTAIN, matched_on=reason)
        elif priority >= 2:
            # dowod domenowy (marka w nazwie domeny) — jedyny priorytet, ktory
            # moze osiagnac potwierdzona/prawdopodobna, patrz _rank_candidate
            nip_confirmed, valid_reason = _validate_nip(url, nip)
            if nip_confirmed:
                site = DeveloperSite(investor=investor, url=url, status=STATUS_CONFIRMED, matched_on=valid_reason)
            else:
                site = DeveloperSite(investor=investor, url=url, status=STATUS_LIKELY, matched_on=reason)
        else:
            # priorytet 1 — samo wystapienie nazwy w tytule/opisie, bez
            # potwierdzenia domena — zawsze kandydat_niepewny, nigdy wyzej
            # (patrz uzasadnienie w _rank_candidate: falszywe trafienie
            # "TOP INVESTMENT" na companiesmarketcap.com)
            site = DeveloperSite(investor=investor, url=url, status=STATUS_UNCERTAIN, matched_on=reason)
        _cache_put(conn, name_key, site)
        return site
    finally:
        conn.close()
