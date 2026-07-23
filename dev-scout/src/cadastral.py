"""
Geokodowanie po numerze dzialki ewidencyjnej przez ULDK (Uniwersalny Lokalizator
Dzialek Katastralnych, GUGiK — oficjalne, darmowe, publiczne API panstwowe).

Dlaczego to wazne: ~67% leadow z realnego RWDZ nie ma wypelnionej kolumny
"ulica" (zweryfikowane na zywo, lipiec 2026) — ale KAZDY wpis w RWDZ ma numer
dzialki (jednostka ewidencyjna + obreb + numer dzialki), bo to wymagany
element kazdego wniosku o pozwolenie/zgloszenie budowy. ULDK zwraca DOKLADNA
geometrie dzialki po tym numerze, bez potrzeby znajomosci ulicy w ogole —
to precyzyjniejsze zrodlo wspolrzednych niz geokodowanie po nazwie ulicy
(Nominatim), nawet gdy ulica jest znana.

Zweryfikowane na zywo:
  GET https://uldk.gugik.gov.pl/?request=GetParcelById&id=146503_8.0423.10/10&result=geom_wkt&srid=4326
  -> "0\nSRID=4326;POLYGON((20.979... 52.340..., ...))" (status "0" = sukces)

Format id: {jednostka_ewidencyjna}.{obreb}.{numer_dzialki}
(np. "146503_8.0423.10/10" — jednostka i obreb sa w RWDZ w kolumnach
jednosta_numer_ew i obreb_numer, numer dzialki w numer_dzialki).
"""

from __future__ import annotations

import logging
import re

import requests

log = logging.getLogger(__name__)

ULDK_URL = "https://uldk.gugik.gov.pl/"


def build_parcel_id(jednostka, obreb, numer_dzialki) -> str | None:
    """Wartosci z raw_json (pandas -> JSON) moga byc float('nan') dla brakow,
    nie None — stad jawne odrzucanie nie-stringow zamiast tylko `not x`."""
    parts = [jednostka, obreb, numer_dzialki]
    if any(not isinstance(p, str) or not p.strip() for p in parts):
        return None
    return f"{jednostka.strip()}.{obreb.strip()}.{numer_dzialki.strip()}"


def _parse_wkt_polygon(wkt: str) -> list[tuple[float, float]]:
    """Wyciaga liste (lon, lat) z 'SRID=4326;POLYGON((lon lat, lon lat, ...))'.
    Bierze tylko zewnetrzny pierscien (wystarczajace dla malych dzialek bez dziur)."""
    match = re.search(r"\(\(([^)]+)\)", wkt)
    if not match:
        return []
    points = []
    for pair in match.group(1).split(","):
        parts = pair.strip().split()
        if len(parts) >= 2:
            points.append((float(parts[0]), float(parts[1])))
    return points


def _polygon_centroid(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Centroid wielokata (wzor Shoelace) — dokladniejszy niz srednia
    wierzcholkow dla nieregularnych ksztaltow dzialek. Dla degenerate/bardzo
    malych dzialek (area ~= 0) spada do zwyklej sredniej wspolrzednych."""
    if len(points) < 3:
        return None
    area = 0.0
    cx = 0.0
    cy = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    area /= 2.0
    if abs(area) < 1e-12:
        lons = [p[0] for p in points]
        lats = [p[1] for p in points]
        return (sum(lats) / len(lats), sum(lons) / len(lons))
    cx /= 6.0 * area
    cy /= 6.0 * area
    return (cy, cx)  # (lat, lon)


def fetch_parcel_centroid(parcel_id: str, timeout: int = 15) -> tuple[float, float] | None:
    """Zwraca (lat, lon) centroidu dzialki, albo None gdy ULDK nie zna tego
    numeru dzialki (np. literowka w RWDZ, dzialka scalona/podzielona od tego czasu)."""
    try:
        resp = requests.get(
            ULDK_URL,
            params={"request": "GetParcelById", "id": parcel_id, "result": "geom_wkt", "srid": 4326},
            headers={"User-Agent": "dev-scout/0.1"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException:
        log.warning("ULDK: zapytanie nie powiodlo sie dla %r", parcel_id, exc_info=True)
        return None

    lines = resp.text.strip().split("\n")
    if not lines or lines[0].strip() != "0":
        # status != "0" -> dzialka nie znaleziona / bledny numer, nie logujemy
        # jako blad (to oczekiwane dla czesci rekordow, np. stare/scalone dzialki)
        return None

    points = _parse_wkt_polygon(lines[1]) if len(lines) > 1 else []
    return _polygon_centroid(points)
