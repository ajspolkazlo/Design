"""
Wzbogacanie leada o dane firmy inwestora: czy to spolka w KRS, czy dzialalnosc
w CEIDG, jaki ma adres / czy widac strone www.

Stan po zweryfikowaniu na zywym internecie (2026, patrz CLAUDE.md zadanie 2):

  1. KRS (spolki: sp. z o.o., S.A., sp.k. itd.) — oficjalne API
     https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{numer_krs} DZIALA, ale
     tylko po numerze KRS (zweryfikowane live: KRS 0000250912 -> zwraca pelny
     odpis "TOP INVESTMENT" SPOLKA Z O.O.). NIE ma oficjalnego wyszukiwania
     po nazwie. Wyszukiwarka https://wyszukiwarka-krs.ms.gov.pl/ jest za
     ochrona antybotowa (Incapsula, 403 na kazde zapytanie bez wzgledu na
     naglowki) — nie obchodzimy tego. rejestr.io ma to samo (Cloudflare
     managed challenge). aleo.com nie ma takiej blokady technicznej, ale nie
     ma tez udokumentowanego, platnego API ani jasnej licencji na
     automatyczne pobieranie do uzytku komercyjnego — swiadoma decyzja
     (Adam, lipiec 2026): NIE scrapowac, zaakceptowac brak wzbogacania KRS
     na razie. lookup_company() dla nazw wygladajacych na spolke zwraca
     wiec zawsze found=False, source=None.

     Zbadane dodatkowo (23.07.2026, na zyczenie): Portal Rejestrow Sadowych
     (https://prs.ms.gov.pl/ci) — to NIE jest niezalezna alternatywa. To
     Angular SPA bez wlasnego, otwartego API do wyszukiwania po nazwie; jego
     kafelek "Wyszukiwarka KRS" (zweryfikowane w /assets/env.js:
     window.env.wyszukiwarkaKrsUrl) linkuje wprost do TEJ SAMEJ
     wyszukiwarka-krs.ms.gov.pl za Incapsula (potwierdzone zywo: nadal HTTP
     403 "Request unsuccessful. Incapsula incident..."). Sprobowane tez kilka
     prawdopodobnych sciezek /api/prs/... — wszystkie 404. Wniosek: PRS nie
     domyka tej luki, decyzja z lipca 2026 (nie scrapowac) pozostaje aktualna.

     Sprawdzone tez: pole nazwa_inwestor w realnym zrzucie RWDZ (320 070
     niepustych wartosci) NIGDY nie zawiera numeru KRS wprost (0 dopasowan do
     wzorca numeru KRS ani slowa "KRS") — RWDZ to rejestr budowlany, nie
     gospodarczy, wiec nie ma z czego zbudowac automatycznego mostka
     nazwa->numer. `lookup_krs_by_number()` ponizej jest gotowa, przetestowana
     na zywo funkcja na wypadek, gdyby numer KRS stal sie kiedys dostepny
     jakimkolwiek innym sposobem (np. reczny wpis) — dzis lookup_company() jej
     nie wywoluje automatycznie, bo nie ma z czego wziac numeru.

  2. CEIDG (jednoosobowe dzialalnosci gospodarcze) — oficjalne, w pelni
     udokumentowane REST API v3:
       PRODUKCJA: https://dane.biznes.gov.pl/api/ceidg/v3/firmy  (wyszukiwanie,
                  parametr nazwa[]=..., miasto[]=..., limit=...)
                  https://dane.biznes.gov.pl/api/ceidg/v3/firma/{id} (szczegoly:
                  telefon/email/www)
     Wymaga tokenu JWT w naglowku Authorization: Bearer — token dostaje sie
     TYLKO po zalogowaniu na biznes.gov.pl Profilem Zaufanym/mObywatel
     (https://biznes.gov.pl/pl/e-uslugi/00_9999_00), czyli wymaga akcji
     czlowieka z polska tozsamoscia elektroniczna — Claude Code tego nie
     zalatwi. Limity: 50 zapytan / 3 min, 1000 / 60 min (optymalny odstep
     ~3.6s miedzy zapytaniami).

     Dopoki token nie jest ustawiony w zmiennej srodowiskowej
     CEIDG_API_TOKEN, lookup_company() dla dzialalnosci jednoosobowych tez
     zwraca found=False — bez zadnego bledu, po prostu pomija wzbogacenie.
     Jak tylko Adam zalatwi token, wystarczy ustawic zmienna srodowiskowa —
     zero zmian w kodzie.

Cache: SQLite (data/company_cache.sqlite3), klucz = znormalizowana nazwa
inwestora, zeby nie odpytywac CEIDG wielokrotnie o tego samego inwestora.
Cache'ujemy tylko wyniki realnych zapytan do API (nie stan "brak tokenu" ani
szybka sciezke "to na pewno spolka w KRS", bo obie moga sie zmienic bez
zwiazku z danymi firmy).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
import yaml

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CACHE_DB_PATH = ROOT / "data" / "company_cache.sqlite3"

CEIDG_BASE_URL = "https://dane.biznes.gov.pl/api/ceidg/v3"
CEIDG_TOKEN_ENV_VAR = "CEIDG_API_TOKEN"
# dokumentacja CEIDG API v3: limit 50 zapytan/3min -> ~3.6s odstepu; 4s z zapasem
CEIDG_MIN_SECONDS_BETWEEN_REQUESTS = 4.0

KRS_ODPIS_URL = "https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}"

_last_ceidg_request_at = 0.0


@dataclass
class CompanyInfo:
    name: str
    found: bool
    source: str | None = None          # "krs" | "ceidg" | None
    krs_number: str | None = None
    nip: str | None = None
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    raw: dict | None = None


def _load_company_signals() -> list[str]:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("investor_filter", {}).get("company_signals", [])


def _norm(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


def _norm_tight(text: str) -> str:
    """Jak _norm, plus usuniecie kropek/spacji — patrz identyczny komentarz
    w filters._norm_tight (ten sam bug, ta sama poprawka, zduplikowane
    celowo — nie warto sprzegac modulow dla jednej funkcji)."""
    return re.sub(r"[.\s]", "", _norm(text))


def _looks_like_krs_company(name: str) -> bool:
    """Sygnaly formy prawnej spolki (sp. z o.o., S.A. itd.) -> to KRS, nie
    CEIDG, i KRS po nazwie nie da sie dzis bezpiecznie sprawdzic (patrz
    docstring modulu) — nie ma sensu odpytywac CEIDG."""
    v = _norm_tight(name)
    return any(_norm_tight(sig) in v for sig in _load_company_signals())


# Boilerplate spotykany w polu inwestor z RWDZ, np. "Grazyna Jurczak
# prowadzaca dzialalnosc gospodarcza pod nazwa PPU JURTEX" — CEIDG szuka po
# polu "nazwa" (imie + nazwisko + nazwa handlowa), wiec ten fragment tylko
# przeszkadza w dopasowaniu.
_BOILERPLATE_RE = re.compile(
    r"\s*prowadz\S*\s+dzia\S*alno\S*\s+gospodarcz\S*\s+pod\s+nazw\S*\s+",
    re.IGNORECASE,
)


def _clean_investor_name(name: str) -> str:
    return _BOILERPLATE_RE.sub(" ", name).strip()


def _cache_connect() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS company_cache (
            name_key TEXT PRIMARY KEY,
            found INTEGER,
            source TEXT,
            nip TEXT,
            address TEXT,
            website TEXT,
            phone TEXT,
            checked_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    return conn


def _cache_get(conn: sqlite3.Connection, name_key: str) -> CompanyInfo | None:
    row = conn.execute(
        "SELECT found, source, nip, address, website, phone FROM company_cache WHERE name_key = ?",
        (name_key,),
    ).fetchone()
    if row is None:
        return None
    found, source, nip, address, website, phone = row
    return CompanyInfo(
        name=name_key, found=bool(found), source=source, nip=nip,
        address=address, website=website, phone=phone, raw={"cached": True},
    )


def _cache_put(conn: sqlite3.Connection, name_key: str, info: CompanyInfo) -> None:
    conn.execute(
        """INSERT INTO company_cache (name_key, found, source, nip, address, website, phone)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(name_key) DO UPDATE SET
             found=excluded.found, source=excluded.source, nip=excluded.nip,
             address=excluded.address, website=excluded.website, phone=excluded.phone,
             checked_at=datetime('now')""",
        (name_key, int(info.found), info.source, info.nip, info.address, info.website, info.phone),
    )
    conn.commit()


def _ceidg_rate_limit() -> None:
    global _last_ceidg_request_at
    elapsed = time.monotonic() - _last_ceidg_request_at
    if elapsed < CEIDG_MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(CEIDG_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_ceidg_request_at = time.monotonic()


def _format_ceidg_address(adres: dict) -> str:
    parts = [adres.get("ulica"), adres.get("budynek"), adres.get("miasto"), adres.get("kod")]
    return ", ".join(p for p in parts if p)


def _lookup_ceidg(name: str, token: str) -> CompanyInfo:
    query = _clean_investor_name(name) or name

    _ceidg_rate_limit()
    search_resp = requests.get(
        f"{CEIDG_BASE_URL}/firmy",
        params={"nazwa": query, "limit": 5},
        headers={"Authorization": f"Bearer {token}", "User-Agent": "dev-scout/0.1"},
        timeout=15,
    )
    if search_resp.status_code == 204:
        return CompanyInfo(name=name, found=False, source=None)
    search_resp.raise_for_status()
    firmy = search_resp.json().get("firmy", [])
    if not firmy:
        return CompanyInfo(name=name, found=False, source=None)

    match = firmy[0]
    address = _format_ceidg_address(match.get("adresDzialalnosci", {}))
    nip = match.get("wlasciciel", {}).get("nip")
    website, phone = None, None

    firm_id = match.get("id")
    if firm_id:
        try:
            _ceidg_rate_limit()
            detail_resp = requests.get(
                f"{CEIDG_BASE_URL}/firma/{firm_id}",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "dev-scout/0.1"},
                timeout=15,
            )
            if detail_resp.status_code == 200:
                detail_firmy = detail_resp.json().get("firma", [])
                if detail_firmy:
                    website = detail_firmy[0].get("www")
                    phone = detail_firmy[0].get("telefon")
        except requests.RequestException:
            log.warning("CEIDG: nie udalo sie pobrac szczegolow firmy id=%s", firm_id, exc_info=True)

    return CompanyInfo(
        name=name, found=True, source="ceidg", nip=nip, address=address or None,
        website=website, phone=phone, raw=match,
    )


def lookup_krs_by_number(krs_number: str, timeout: int = 15) -> CompanyInfo:
    """Oficjalne, dzialajace API MS — pelny odpis aktualny po numerze KRS
    (zweryfikowane na zywo: KRS 0000250912 -> "TOP INVESTMENT" SPOLKA Z O.O.,
    NIP i adres w dzial1.danePodmiotu / dzial1.siedzibaIAdres). NIE ma
    wyszukiwania po nazwie (patrz docstring modulu) — ta funkcja przydaje sie
    tylko gdy numer KRS jest juz znany skads indziej (dzis: brak takiego
    zrodla w automatycznym pipeline, patrz docstring modulu; funkcja gotowa
    na przyszlosc / do recznego uzycia)."""
    krs_number = re.sub(r"\D", "", krs_number or "").zfill(10)
    try:
        resp = requests.get(
            KRS_ODPIS_URL.format(krs=krs_number),
            params={"rejestr": "P", "format": "json"},
            headers={"User-Agent": "dev-scout/0.1"},
            timeout=timeout,
        )
    except requests.RequestException:
        log.warning("KRS OdpisAktualny nie powiodl sie dla %r", krs_number, exc_info=True)
        return CompanyInfo(name="", found=False, source=None)
    if resp.status_code != 200:
        return CompanyInfo(name="", found=False, source=None)
    try:
        dane = resp.json()["odpis"]["dane"]
        podmiot = dane["dzial1"]["danePodmiotu"]
        siedziba = dane["dzial1"].get("siedzibaIAdres", {}).get("adres", {})
    except (KeyError, TypeError, ValueError):
        return CompanyInfo(name="", found=False, source=None)
    nazwa = podmiot.get("nazwa", "")
    address = ", ".join(p for p in (siedziba.get("ulica"), siedziba.get("nrDomu"),
                                     siedziba.get("miejscowosc"), siedziba.get("kodPocztowy")) if p)
    return CompanyInfo(
        name=nazwa, found=True, source="krs", krs_number=krs_number,
        nip=podmiot.get("identyfikatory", {}).get("nip") if isinstance(podmiot.get("identyfikatory"), dict) else None,
        address=address or None, raw={"dzial1": dane.get("dzial1")},
    )


def lookup_company(name: str) -> CompanyInfo:
    """Punkt wejscia uzywany przez main.py. Trzyma sygnature (name: str) ->
    CompanyInfo, zeby main.py sie nie zmienial."""
    if not name or not name.strip():
        return CompanyInfo(name=name, found=False, source=None)

    if _looks_like_krs_company(name):
        # spolka (sp. z o.o. / S.A. / sp.k. itd.) -> KRS, ktorego po nazwie
        # dzis nie sprawdzimy bezpiecznie (patrz docstring modulu) — brak
        # sensu cache'owania szybkiej sciezki lokalnej.
        return CompanyInfo(name=name, found=False, source=None)

    name_key = _norm(name)
    conn = _cache_connect()
    try:
        # cache sprawdzamy niezaleznie od tego, czy token jest dzis ustawiony —
        # mogl byc ustawiony przy wczesniejszym uruchomieniu i wynik wciaz jest aktualny
        cached = _cache_get(conn, name_key)
        if cached is not None:
            return CompanyInfo(**{**asdict(cached), "name": name})

        token = os.environ.get(CEIDG_TOKEN_ENV_VAR)
        if not token:
            # brak tokenu CEIDG — pomijamy wzbogacenie, bez bledu (patrz
            # docstring modulu: token wymaga akcji Adama przez Profil Zaufany)
            return CompanyInfo(name=name, found=False, source=None)

        try:
            info = _lookup_ceidg(name, token)
        except requests.RequestException:
            log.warning("CEIDG lookup nie powiodl sie dla %r", name, exc_info=True)
            return CompanyInfo(name=name, found=False, source=None)

        _cache_put(conn, name_key, info)
        return info
    finally:
        conn.close()
