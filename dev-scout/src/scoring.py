"""
Liczy score 0-100 dla leada zamiast twardo odrzucac wszystko, co nie spelnia
kazdego kryterium na 100%. Sortuj po tym w eksporcie zamiast filtrowac —
mniej ryzyka utraty dobrego leada przez jedno slabe kryterium.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.distance import haversine_km


def is_recent(data_str: str | None, days: int = 30) -> bool:
    if not data_str:
        return False
    try:
        data = datetime.fromisoformat(data_str.strip())
    except ValueError:
        return False
    if data.tzinfo is None:
        data = data.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - data).days <= days


def compute_distance_km(lat: float | None, lon: float | None, cfg: dict) -> float | None:
    if lat is None or lon is None:
        return None
    center = cfg["scoring"]["warszawa_centrum"]
    return haversine_km(lat, lon, center["lat"], center["lon"])


def compute_score(lead: dict, cfg: dict) -> int:
    weights = cfg["scoring"]["weights"]
    score = 0

    # on_portal_found: True (znaleziono), False (sprawdzono, brak), None (nie
    # sprawdzono — brak ulicy). Nagradzamy tylko potwierdzone False, nie "nie
    # wiem" (ten sam wzor co company_has_website nizej).
    if lead.get("on_portal_found") is False:
        score += weights.get("brak_na_portalach", 0)

    # company_has_website is None gdy nie sprawdzilismy (brak tokenu CEIDG /
    # spolka w KRS) — nagradzamy tylko potwierdzony brak strony, nie "nie wiem"
    if lead.get("is_likely_company") and lead.get("company_has_website") is False:
        score += weights.get("mala_firma_bez_www", 0)

    if is_recent(lead.get("data")):
        score += weights.get("swiezy_wpis", 0)

    liczba_budynkow = lead.get("liczba_budynkow")
    try:
        # int(float(...)): w bazie liczba budynkow jest tekstem typu "2.0"
        # (kolumna TEXT + pandas float), a int("2.0") rzuca ValueError — bez
        # tego bonus mala_skala nigdy by sie nie naliczyl
        liczba_budynkow = int(float(liczba_budynkow)) if liczba_budynkow is not None else None
    except (ValueError, TypeError):
        liczba_budynkow = None
    if liczba_budynkow is not None and 2 <= liczba_budynkow <= 10:
        score += weights.get("mala_skala", 0)

    distance_km = lead.get("distance_km")
    max_distance = cfg["scoring"].get("max_distance_km", 30)
    if distance_km is not None and distance_km <= max_distance:
        score += weights.get("bliska_odleglosc", 0)

    return min(score, 100)
