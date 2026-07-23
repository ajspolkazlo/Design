"""
Geokodowanie adresu (gmina + miejscowosc + ulica) do lat/lon przez Nominatim
(OpenStreetMap) — darmowe, ale z limitem 1 zapytanie/sekunde i wymaganym
identyfikowalnym User-Agent (patrz polityka Nominatim). Dla naszej skali
(dziesiatki nowych leadow tygodniowo) to w zupelnosci wystarcza.

Zweryfikowane na zywo (2026), dwa realne problemy z jakoscia dopasowania:

1. Dopasowanie na poziomie ulicy czesto zawodzi — wiele malych ulic
   osiedlowych po prostu nie ma pokrycia w danych OSM/Nominatim (np.
   "Grażyny, Ząbki" -> brak wyniku), podczas gdy sama miejscowosc/gmina
   ("Ząbki" -> 52.29, 21.11) dziala prawie zawsze. Stad fallback: probuj z
   ulica, a jesli Nominatim nic nie znajdzie, sprobuj ponownie bez niej.

2. Polska ma mnostwo miejscowosci o identycznej nazwie w roznych czesciach
   kraju — samo "Jabłonna" istnieje jako 10 odrebnych miejscowosci w 6
   wojewodztwach (zweryfikowane live). Bez dodatkowej wskazowki Nominatim
   czasem trafia w zupelnie inna, odlegla miejscowosc o tej samej nazwie
   (np. "Jabłonna, Jabłonna, Polska" trafilo w gmine Rusinow, ~96 km od
   Warszawy, zamiast prawdziwej gminy Jabłonna kolo Legionowa, ~17 km).
   Poniewaz caly ten projekt dotyczy tylko okolic Warszawy, pobieramy kilka
   kandydatow (exactly_one=False) i wybieramy tego najblizszego centrum
   Warszawy — a jesli nawet najblizszy kandydat jest nierealnie daleko
   (> _MAX_PLAUSIBLE_KM), uznajemy to za brak wiarygodnego dopasowania
   zamiast zwracac cos ewidentnie zlego.
"""

from __future__ import annotations

import time
from pathlib import Path

import yaml
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

from src.distance import haversine_km

_geolocator = Nominatim(user_agent="dev-scout-warszawa-deweloperzy")

_ROOT = Path(__file__).parent.parent
with open(_ROOT / "config.yaml", encoding="utf-8") as _f:
    _WARSZAWA_CENTRUM = yaml.safe_load(_f)["scoring"]["warszawa_centrum"]

# projekt dotyczy tylko promienia 20-30 km od Warszawy — dopasowanie dalej
# niz to jest prawie na pewno inna miejscowosc o tej samej nazwie, nie
# przyblizenie tego samego miejsca
_MAX_PLAUSIBLE_KM = 80.0


def _closest_candidate(candidates) -> tuple[float, float] | None:
    best_coords, best_dist = None, None
    for loc in candidates:
        dist = haversine_km(loc.latitude, loc.longitude, _WARSZAWA_CENTRUM["lat"], _WARSZAWA_CENTRUM["lon"])
        if best_dist is None or dist < best_dist:
            best_coords, best_dist = (loc.latitude, loc.longitude), dist
    if best_dist is not None and best_dist > _MAX_PLAUSIBLE_KM:
        return None
    return best_coords


def _try_geocode(query: str) -> tuple[float, float] | None:
    try:
        candidates = _geolocator.geocode(query, timeout=10, exactly_one=False, limit=8)
    except GeocoderTimedOut:
        return None
    finally:
        time.sleep(1.1)  # limit Nominatim: max 1 req/s

    if not candidates:
        return None
    return _closest_candidate(candidates)


def geocode_address(miejscowosc: str, gmina: str, ulica: str | None = None) -> tuple[float, float] | None:
    if ulica:
        query = ", ".join(p for p in [ulica, miejscowosc, gmina, "Polska"] if p)
        result = _try_geocode(query)
        if result is not None:
            return result
        # fallback: sama miejscowosc/gmina, bez ulicy ktorej Nominatim nie zna

    query = ", ".join(p for p in [miejscowosc, gmina, "Polska"] if p)
    return _try_geocode(query)


def reverse_geocode_street(lat: float, lon: float) -> str | None:
    """Odwrotne geokodowanie: z dokladnych wspolrzednych (np. z ULDK — patrz
    src/cadastral.py) odzyskuje nazwe ulicy. Uzywane dla ~67% leadow z realnego
    RWDZ, ktore nie maja wypelnionej kolumny ulica, ale MAJA numer dzialki —
    zamiast szukac po samej miejscowosci (za slaby sygnal), odzyskujemy realna
    ulice i szukamy po niej normalnie. Zweryfikowane na zywo: dzialka bez ulicy
    w RWDZ, po ULDK+reverse geocode -> "Karnicka" (z numerem domu)."""
    try:
        location = _geolocator.reverse(f"{lat}, {lon}", timeout=10, language="pl")
    except GeocoderTimedOut:
        return None
    finally:
        time.sleep(1.1)  # limit Nominatim: max 1 req/s

    if location is None:
        return None
    return location.raw.get("address", {}).get("road")
