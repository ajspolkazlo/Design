"""
Geokodowanie adresu (gmina + miejscowosc + ulica) do lat/lon przez Nominatim
(OpenStreetMap) — darmowe, ale z limitem 1 zapytanie/sekunde i wymaganym
identyfikowalnym User-Agent (patrz polityka Nominatim). Dla naszej skali
(dziesiatki nowych leadow tygodniowo) to w zupelnosci wystarcza.

Zweryfikowane na zywo (2026): dopasowanie na poziomie ulicy czesto zawodzi —
wiele malych ulic osiedlowych po prostu nie ma pokrycia w danych OSM/Nominatim
(np. "Grażyny, Ząbki" -> brak wyniku), podczas gdy sama miejscowosc/gmina
("Ząbki" -> 52.29, 21.11) dziala prawie zawsze. Stad fallback: probuj z ulica,
a jesli Nominatim nic nie znajdzie, sprobuj ponownie bez niej — lepsze
przyblizone wspolrzedne (poziom miejscowosci) niz brak wspolrzednych w ogole.
"""

from __future__ import annotations

import time

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

_geolocator = Nominatim(user_agent="dev-scout-warszawa-deweloperzy")


def _try_geocode(query: str) -> tuple[float, float] | None:
    try:
        location = _geolocator.geocode(query, timeout=10)
    except GeocoderTimedOut:
        return None
    finally:
        time.sleep(1.1)  # limit Nominatim: max 1 req/s

    if location is None:
        return None
    return (location.latitude, location.longitude)


def geocode_address(miejscowosc: str, gmina: str, ulica: str | None = None) -> tuple[float, float] | None:
    if ulica:
        query = ", ".join(p for p in [ulica, miejscowosc, gmina, "Polska"] if p)
        result = _try_geocode(query)
        if result is not None:
            return result
        # fallback: sama miejscowosc/gmina, bez ulicy ktorej Nominatim nie zna

    query = ", ".join(p for p in [miejscowosc, gmina, "Polska"] if p)
    return _try_geocode(query)
