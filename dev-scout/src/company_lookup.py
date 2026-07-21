"""
Wzbogacanie leada o dane firmy inwestora: czy to spolka w KRS, czy dzialalnosc
w CEIDG, jaki ma adres / czy widac strone www.

WAZNE — do zweryfikowania przez Claude Code (nie dalo sie przetestowac na
zywo w tym srodowisku, brak dostepu do ms.gov.pl / biznes.gov.pl z tego
sandboxa):

  1. KRS — oficjalne API GUNB... a wlasciwie Ministerstwa Sprawiedliwosci:
     https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{numer_krs}
     Dziala po numerze KRS, NIE po nazwie firmy. Do wyszukiwania PO NAZWIE
     potrzebna jest wyszukiwarka na https://wyszukiwarka-krs.ms.gov.pl/
     (sprawdz czy ma publiczne API, czy tylko formularz HTML — jesli tylko
     HTML, trzeba bedzie to parsowac jako strone, nie jako API).

  2. CEIDG — otwarte dane biznesowe: https://api.biznes.gov.pl/ (dawniej
     dane.biznes.gov.pl). Rejestracja + klucz API sa zwykle wymagane.
     Sprawdz aktualna dokumentacje na https://api.biznes.gov.pl/ przed
     implementacja.

  3. Alternatywa bez klucza API: serwisy agregujace jak rejestr.io czy
     aleo.com maja wlasne, nieoficjalne API/wyszukiwarki — do rozwazenia
     jesli oficjalne API okaze sie zbyt ograniczone, ale sprawdz ich ToS.

Ten plik definiuje tylko wspolny interfejs (CompanyInfo + lookup_company)
i DZIALAJACY szkielet z jasno oznaczonymi TODO w miejscach, ktore wymagaja
zweryfikowanego endpointu.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests


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


def lookup_company(name: str) -> CompanyInfo:
    """Punkt wejscia uzywany przez main.py. Na razie zwraca 'not found' —
    podepnij tu realny klient po zweryfikowaniu endpointow (patrz docstring
    modulu). Trzymaj ten sam sygnature, zeby main.py sie nie zmienial."""
    # TODO(claude-code): podmienic na realne wywolanie KRS/CEIDG
    return CompanyInfo(name=name, found=False, source=None)


def _http_get_json(url: str, params: dict | None = None, timeout: int = 15) -> dict:
    resp = requests.get(url, params=params, timeout=timeout, headers={"User-Agent": "dev-scout/0.1"})
    resp.raise_for_status()
    return resp.json()
