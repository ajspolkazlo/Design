"""
Sprawdza, czy dana inwestycja jest juz widoczna na popularnych portalach
nieruchomosci (Otodom, OLX, RynekPierwotny, Morizon, Gratka, Domiporta).

Cel: nie odrzucac na twardo, tylko oznaczyc status + date sprawdzenia.
Lead, ktory dzis jest "czysty", moze pojawic sie na portalu za kilka tygodni —
to okno czasu jest dokladnie tym, co ma dawac przewage. Re-checkuj leady
co `portal_check.recheck_after_days` (patrz config.yaml), nie tylko raz.

WAZNE (do zweryfikowania przez Claude Code — brak internetu w tym sandboxie):
  1. Zaden z portali nie ma oficjalnego publicznego API wyszukiwania.
     Otodom i RynekPierwotny sa na Next.js/React — zwykle maja wewnetrzny
     endpoint JSON pod wyszukiwarka (do podejrzenia w devtoolsach
     przegladarki, zakladka Network przy wpisywaniu frazy w wyszukiwarke).
     To zazwyczaj stabilniejsze i szybsze niz parsowanie HTML.
  2. Sprawdz robots.txt i ToS kazdego portalu. To use case "czy MOJ adres/
     dzialka juz tam jest", nie masowe scrapowanie katalogu — ale i tak
     zachowaj rozsadny rate limit (patrz REQUEST_DELAY_SECONDS ponizej).
  3. NIE dopasowuj po samej nazwie firmy z KRS — deweloper sprzedaje pod
     nazwa PROJEKTU/osiedla, ktora prawie nigdy nie pokrywa sie z nazwa
     spolki. Lepsza kolejnosc sygnalow:
       a) ulica + miejscowosc z RWDZ jako fraza wyszukiwania (najsilniejszy)
       b) promien geograficzny od geokodowanych wspolrzednych, jesli portal
          ma wyszukiwanie po mapie
       c) nazwa inwestora — jako dodatkowy, slabszy sygnal
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

REQUEST_DELAY_SECONDS = 1.5  # bufor miedzy zapytaniami do jednego portalu


@dataclass
class PortalPresence:
    found_on: list[str] = field(default_factory=list)  # np. ["otodom", "olx"]
    confidence: str = "low"   # "low" = dopasowanie po adresie, "high" = adres + nazwa firmy
    checked_at: str | None = None

    @property
    def is_present_anywhere(self) -> bool:
        return len(self.found_on) > 0


def _check_otodom(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania Otodom
    return False


def _check_olx(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania OLX
    return False


def _check_rynekpierwotny(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania RynekPierwotny
    return False


def _check_morizon(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania Morizon
    return False


def _check_gratka(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania Gratka
    return False


def _check_domiporta(query: str) -> bool:
    # TODO(claude-code): podepnij realny endpoint wyszukiwania Domiporta
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
            pass
        time.sleep(REQUEST_DELAY_SECONDS)

    return PortalPresence(
        found_on=found,
        confidence="low",
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
