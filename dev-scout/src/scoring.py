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
    # wiem" (ten sam wzor co company_has_website nizej). UWAGA: on_portal_found
    # juz jest liczone w main.py z pominieciem dopasowan REJECTED (inna
    # nieruchomosc przy tej samej ulicy — patrz src/verify.py), wiec samo to
    # pole juz nie myli "odrzucone" z "potwierdzone".
    if lead.get("on_portal_found") is False:
        score += weights.get("brak_na_portalach", 0)

    # Werdykt CONFIRMED (patrz src/verify.py) to co innego niz LIKELY/REVIEW —
    # oznacza wysoka pewnosc, ze inwestycja JUZ jest reklamowana na portalu.
    # To bezposrednio przeciwne temu, co ma dawac przewage (CLAUDE.md: wykryc
    # dewelopera ZANIM zacznie marketing), wiec karzemy to jawnie zamiast tylko
    # nie przyznawac bonusu brak_na_portalach jak dla LIKELY/REVIEW.
    if lead.get("lead_verdict") == "CONFIRMED":
        score -= weights.get("kara_potwierdzone_na_portalu", 0)

    # Seryjnosc inwestora w calym zrzucie RWDZ (src/verify.py) — niezalezny od
    # nazwy sygnal "to raczej deweloper, nie osoba budujaca dla siebie",
    # dziala TEZ dla ~88% leadow bez nazwy inwestora wypelnionej w RWDZ.
    serial_min = cfg.get("verify", {}).get("serial_investor_min", 3)
    if (lead.get("investor_serial_count") or 0) >= serial_min:
        score += weights.get("seryjny_inwestor", 0)

    # Kategoria wlasciciela dzialki z ewidencji gruntow (KIEG WMS) — "spolka
    # prawa handlowego" jest silnym sygnalem dzialalnosci deweloperskiej
    # NIEZALEZNIE od tego, czy RWDZ ma wypelnione pole inwestora (dziala wiec
    # tam, gdzie is_likely_company/looks_like_company nie ma czego analizowac).
    if lead.get("parcel_owner_group") == "15":
        score += weights.get("dzialka_spolki", 0)

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

    # gorny I DOLNY limit — kara_potwierdzone_na_portalu (nowa waga, patrz
    # wyzej) moze przewazyc sume bonusow i zejsc ponizej 0, co lamaloby
    # udokumentowana skale 0-100 (zweryfikowane na zywo: bez tego limitu
    # realny lead z werdyktem CONFIRMED wyszedl ze score -5)
    return max(0, min(score, 100))
