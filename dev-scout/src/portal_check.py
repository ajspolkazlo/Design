"""
Sprawdza, czy dana inwestycja jest juz widoczna na popularnych portalach
nieruchomosci (Otodom, OLX, RynekPierwotny, Morizon, Gratka, Domiporta).

Cel: nie odrzucac na twardo, tylko oznaczyc status + date sprawdzenia.
Lead, ktory dzis jest "czysty", moze pojawic sie na portalu za kilka tygodni —
to okno czasu jest dokladnie tym, co ma dawac przewage. Re-checkuj leady
co `portal_check.recheck_after_days` (patrz config.yaml), nie tylko raz.

Stan po zweryfikowaniu na zywym internecie (2026, patrz CLAUDE.md zadanie 2b):
tylko OLX da sie dzis sprawdzac uczciwie i bez lamania zasad. Reszta portali
jest swiadomie NIEZAIMPLEMENTOWANA:

  - OTODOM: zablokowane na poziomie CDN/WAF (CloudFront zwraca 403 "Request
    blocked" nawet na samo /robots.txt, niezaleznie od nagłowkow) — to nie
    jest kwestia ToS tylko aktywnej ochrony antybotowej, nie obchodzimy tego.
  - RYNEKPIERWOTNY: robots.txt (rynekpierwotny.pl) explicite zabrania
    `Disallow: *?phrase=` i `Disallow: */ws/*` — czyli dokladnie wyszukiwania
    po frazie i ich web-service. Respektujemy to.
  - MORIZON: robots.txt (www.morizon.pl) ma `Disallow: /api` — respektujemy.
  - DOMIPORTA: robots.txt ma jawny wpis `User-Agent: Scrapy / Disallow: /` i
    blokuje endpointy wyszukiwania (`/Search/SearchMap*`) — respektujemy.
  - GRATKA: brak robots.txt (404), ale tez brak jakiegokolwiek udokumentowanego
    API — sprawdzanie oznaczaloby scrapowanie HTML bez jasnej podstawy w ToS;
    odlozone, do rozwazenia gdy Adam zdecyduje czy akceptuje to ryzyko.

  - OLX: robots.txt (www.olx.pl) JAWNIE zezwala: `Allow: /api/v1/offers/`.
    To wewnetrzny endpoint wyszukiwania uzywany przez sama strone OLX —
    zwraca JSON, dziala bez klucza/tokenu, zweryfikowany na zywo (zwraca
    prawdziwe, trafne oferty dla zapytania "ulica, miejscowosc").

Dopoki Adam nie zdecyduje inaczej, `config.yaml` -> `portal_check.portale`
powinno wiec zawierac tylko "olx" — reszta w liscie oznaczalaby falszywa
pewnosc (portal "niesprawdzony" ≠ portal "czysty", a scoring.py nagradza
"brak_na_portalach" tak, jakby to bylo potwierdzone).

WAZNE o jakosci sygnalu (patrz tez CLAUDE.md):
  NIE dopasowuj po samej nazwie firmy z KRS — deweloper sprzedaje pod nazwa
  PROJEKTU/osiedla, ktora prawie nigdy nie pokrywa sie z nazwa spolki.
  Kolejnosc sygnalow uzyta tutaj:
    a) ulica + miejscowosc z RWDZ jako fraza wyszukiwania (najsilniejszy) —
       patrz main.py step_enrich, tam budowane jest `query`.
    b) promien geograficzny od geokodowanych wspolrzednych — OLX nie ma
       prostego publicznego wyszukiwania po promieniu w tym samym endpoincie;
       nie zaimplementowane w v1, do rozwazenia pozniej.
    c) nazwa inwestora — nie zaimplementowane w v1 (dodatkowy, slabszy sygnal,
       przy obecnym zakresie i tak rzadko pomaga bardziej niz ulica+miejscowosc).

  `_check_olx` wymaga co najmniej dwoch sensownych tokenow w query (np.
  ulica + miejscowosc) zeby uznac brak trafien za realny sygnal "czysty" —
  pojedynczy token (sama gmina/miejscowosc) daje zbyt duzo falszywych trafien
  (i odwrotnie: zbyt latwo bledy uznac "nie znaleziono" za realne, gdy tak
  naprawde nie sprawdzilismy nic sensownego).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = 1.5  # bufor miedzy zapytaniami do jednego portalu

OLX_OFFERS_URL = "https://www.olx.pl/api/v1/offers/"
_STOPWORD_TOKENS = {"ul", "ul.", "al", "al.", "os", "os.", "pl", "pl."}


@dataclass
class PortalPresence:
    found_on: list[str] = field(default_factory=list)  # np. ["otodom", "olx"]
    confidence: str = "low"   # "low" = dopasowanie po adresie, "high" = adres + nazwa firmy
    checked_at: str | None = None

    @property
    def is_present_anywhere(self) -> bool:
        return len(self.found_on) > 0


def _norm(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _query_tokens(query: str) -> list[str]:
    """Rozbija 'ulica, miejscowosc' na tokeny uzywane do sprawdzenia trafnosci
    wyniku — pomija krotkie prefiksy typu 'ul.'/'al.' i puste fragmenty."""
    raw_tokens = re.split(r"[,\s]+", query)
    return [t for t in raw_tokens if t and _norm(t).rstrip(".") not in _STOPWORD_TOKENS and len(t) > 2]


def _check_otodom(query: str) -> bool:
    # Zablokowane na poziomie CDN (CloudFront 403 na kazde zadanie, wlacznie
    # z /robots.txt) — nie obchodzimy ochrony antybotowej. Patrz docstring modulu.
    return False


def _check_olx(query: str) -> bool:
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        # za malo sensownych tokenow (brakuje ulicy) — nie da sie sprawdzic
        # wiarygodnie, wiec nie udajemy ze sprawdzilismy (patrz docstring modulu)
        return False

    resp = requests.get(
        OLX_OFFERS_URL,
        params={"query": query, "limit": 20},
        headers={"User-Agent": "dev-scout/0.1"},
        timeout=15,
    )
    resp.raise_for_status()
    offers = resp.json().get("data", [])

    norm_tokens = [_norm(t) for t in tokens]
    for offer in offers:
        haystack = _norm(
            f"{offer.get('title', '')} {offer.get('description', '')} {offer.get('url', '')}"
        )
        if all(tok in haystack for tok in norm_tokens):
            return True
    return False


def _check_rynekpierwotny(query: str) -> bool:
    # robots.txt (rynekpierwotny.pl): "Disallow: *?phrase=" i "Disallow: */ws/*"
    # — dokladnie wyszukiwanie po frazie i ich web-service. Respektujemy. Patrz
    # docstring modulu.
    return False


def _check_morizon(query: str) -> bool:
    # robots.txt (www.morizon.pl): "Disallow: /api". Respektujemy. Patrz
    # docstring modulu.
    return False


def _check_gratka(query: str) -> bool:
    # Brak robots.txt, ale tez brak udokumentowanego API — scraping HTML bez
    # jasnej podstawy w ToS. Odlozone do decyzji Adama. Patrz docstring modulu.
    return False


def _check_domiporta(query: str) -> bool:
    # robots.txt (www.domiporta.pl) jawnie blokuje "User-Agent: Scrapy" i
    # endpointy wyszukiwania. Respektujemy. Patrz docstring modulu.
    return False


_PORTAL_CHECKERS = {
    "otodom": _check_otodom,
    "olx": _check_olx,
    "rynekpierwotny": _check_rynekpierwotny,
    "morizon": _check_morizon,
    "gratka": _check_gratka,
    "domiporta": _check_domiporta,
}


def check_portals(query: str, portale: list[str]) -> PortalPresence:
    """query = najlepiej 'ulica, miejscowosc' (patrz docstring modulu).
    Kazdy checker jest izolowany w try/except — awaria jednego portalu
    (np. zmiana layoutu strony) nie blokuje sprawdzenia pozostalych."""
    found: list[str] = []
    for portal in portale:
        checker = _PORTAL_CHECKERS.get(portal)
        if checker is None:
            continue
        try:
            if checker(query):
                found.append(portal)
        except Exception:
            log.warning("Sprawdzenie portalu %s nie powiodlo sie dla %r", portal, query, exc_info=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    return PortalPresence(
        found_on=found,
        confidence="low",
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
