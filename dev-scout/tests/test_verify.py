"""
Testy regresyjne dla src/verify.py (weryfikacja dopasowania lead<->ogloszenie) —
bez sieci, na zamockowanych ListingFacts. Patrz src/verify.py docstring modulu
dla opisu prawdziwych przypadkow (Kobylka, Brwinow), na ktorych ta logika
zostala zweryfikowana na zywo w trakcie budowy.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import portal_check, verify

CFG = verify.DEFAULTS


def test_kubatura_band_basic():
    lo, hi = verify.kubatura_band(569, CFG)
    assert 100 < lo < 105
    assert 140 < hi < 145


def test_kubatura_band_rejects_placeholder():
    assert verify.kubatura_band(1, CFG) is None
    assert verify.kubatura_band(None, CFG) is None
    assert verify.kubatura_band("nie-liczba", CFG) is None


def test_investor_core_name_strips_legal_form():
    # ta funkcja (do cross-checku tresci ogloszenia) zyje w portal_check.py —
    # nie mylic z verify._investor_key (do liczników seryjnosci w RWDZ)
    assert portal_check.investor_core_name("TOP INVESTMENT Sp. Z o.o.") == "top investment"


def test_investor_core_name_too_short_after_strip():
    # "M4" ma tylko 2 znaki (<=2, filtrowane) — celowa decyzja bezpieczenstwa,
    # zeby nie dopasowywac po zbyt krotkim/generycznym fragmencie
    assert portal_check.investor_core_name("M4 Sp. z o. o.") is None


def test_point_in_polygon():
    # kwadrat (lon, lat) 0..1 x 0..1
    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert verify._point_in_polygon(0.5, 0.5, square)
    assert not verify._point_in_polygon(5, 5, square)


def test_judge_match_geo_confirmed():
    facts = verify.ListingFacts(
        source="otodom_json", market="primary", area_m2=130, coords_precise=True,
        lat=52.11820, lon=20.65103,
    )
    lead = {"kubatura": 569, "data_wniosku": None, "lat": 52.11874, "lon": 20.64969}
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert verdict.verdict == "CONFIRMED"
    assert any("działki" in r or "m" in r for r in verdict.reasons)


def test_judge_match_secondary_market_hard_rejects():
    facts = verify.ListingFacts(source="otodom_json", market="secondary", coords_precise=True,
                                 lat=52.1, lon=20.1)
    lead = {"kubatura": None, "data_wniosku": None, "lat": 52.1, "lon": 20.1}
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert verdict.verdict == "REJECTED"
    assert any("WTÓRNEGO" in r for r in verdict.reasons)


def test_judge_match_far_distance_hard_rejects():
    # Realny przypadek (Brwinow, 22.07.2026): pin 1.82 km od dzialki. To NIE
    # jest hard-reject (poniej progu reject_distance_m=2000) — sprawdzane
    # osobno w test_judge_match_dubious_distance_zone.
    facts = verify.ListingFacts(source="otodom_json", market="primary", coords_precise=True,
                                 lat=52.0, lon=20.0)
    lead = {"kubatura": None, "data_wniosku": None, "lat": 53.0, "lon": 21.0}  # bardzo daleko
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert verdict.verdict == "REJECTED"
    assert any("INNA lokalizacja" in r for r in verdict.reasons)


def test_judge_match_dubious_distance_zone_not_silently_dropped():
    """Regresja: strefa 700m-2km kiedys nie miala ZADNEJ galezi w kodzie —
    sygnal geograficzny znikal calkowicie z powodow (przypadek Brwinowa,
    1.82 km, zweryfikowany na zywo 22.07.2026). Test pilnuje, ze powod
    zawsze sie pojawia, niezaleznie od przyszlych zmian w progach."""
    import math
    # ~1 km na tej szerokosci geograficznej
    facts = verify.ListingFacts(source="otodom_json", market="primary", coords_precise=True,
                                 lat=52.100, lon=20.100)
    lead = {"kubatura": None, "data_wniosku": None, "lat": 52.109, "lon": 20.100}
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert any("km od działki" in r for r in verdict.reasons), verdict.reasons
    assert verdict.verdict != "CONFIRMED"


def test_judge_match_no_facts_is_review():
    verdict = verify.judge_match("gratka", "http://example.com/x", None, {}, {}, CFG)
    assert verdict.verdict == "REVIEW"


def test_best_verdict_prefers_confirmed_over_rejected():
    verdicts = [
        verify.MatchVerdict("olx", "u1", "REJECTED"),
        verify.MatchVerdict("otodom", "u2", "CONFIRMED"),
    ]
    assert verify.best_verdict(verdicts) == "CONFIRMED"


def test_best_verdict_empty_is_none():
    assert verify.best_verdict([]) is None
