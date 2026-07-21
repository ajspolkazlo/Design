"""
Geokodowanie adresu (gmina + miejscowosc + ulica) do lat/lon przez Nominatim
(OpenStreetMap) — darmowe, ale z limitem 1 zapytanie/sekunde i wymaganym
identyfikowalnym User-Agent (patrz polityka Nominatim). Dla naszej skali
(dziesiatki nowych leadow tygodniowo) to w zupelnosci wystarcza.
"""

from __future__ import annotations

import time

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

_geolocator = Nominatim(user_agent="dev-scout-warszawa-deweloperzy")


def geocode_address(miejscowosc: str, gmina: str, ulica: str | None = None) -> tuple[float, float] | None:
    query_parts = [p for p in [ulica, miejscowosc, gmina, "Polska"] if p]
    query = ", ".join(query_parts)
    try:
        location = _geolocator.geocode(query, timeout=10)
    except GeocoderTimedOut:
        return None
    finally:
        time.sleep(1.1)  # limit Nominatim: max 1 req/s

    if location is None:
        return None
    return (location.latitude, location.longitude)
