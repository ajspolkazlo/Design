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


def test_judge_match_listing_predating_wniosek_cannot_reach_confirmed():
    # Zadanie 1B: ogloszenie wystawione ZNACZNIE PRZED data wniosku o
    # pozwolenie to silna poszlaka "inna nieruchomosc" — nawet gdy geometria
    # idealnie pasuje (ta sama dzialka), werdykt NIE MOZE byc CONFIRMED,
    # najwyzej LIKELY (moze to legalnie byc wczesniejsza faza tej samej
    # duzej inwestycji, wiec nie hard-rejectujemy).
    facts = verify.ListingFacts(
        source="otodom_json", market="primary", area_m2=130, coords_precise=True,
        lat=52.11820, lon=20.65103, created_at="2020-01-01T00:00:00Z",
    )
    lead = {"kubatura": 569, "data_wniosku": "2026-06-01", "lat": 52.11874, "lon": 20.64969}
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert verdict.verdict != "CONFIRMED"
    assert any("nie może osiągnąć" in r for r in verdict.reasons)


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


def test_judge_match_dead_link_rejected():
    # link wygasl/przekierowal -> REJECTED (nie REVIEW), zeby martwy link nie
    # pokazywal sie jako klikalne "ogloszenie" w Excelu
    facts = verify._dead_link()
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, {}, {}, CFG)
    assert verdict.verdict == "REJECTED"
    assert any("nieaktualne" in r for r in verdict.reasons)


def test_judge_match_rental_rejected():
    # ogloszenie WYNAJMU nigdy nie jest nasza inwestycja (pozwolenie = budowa
    # na sprzedaz) -> twardy REJECTED niezaleznie od reszty sygnalow
    facts = verify.ListingFacts(source="otodom_json", market="secondary", is_rental=True,
                                 coords_precise=True, lat=52.1, lon=20.1)
    lead = {"kubatura": None, "data_wniosku": None, "lat": 52.1, "lon": 20.1}
    verdict = verify.judge_match("otodom", "http://example.com/x", facts, lead, {}, CFG)
    assert verdict.verdict == "REJECTED"
    assert any("WYNAJMU" in r for r in verdict.reasons)


def test_is_rental_detection():
    from src import portal_check
    assert portal_check._is_rental("https://www.morizon.pl/oferta/wynajem-dom-x-mzn123")
    assert portal_check._is_rental("https://www.olx.pl/d/oferta/dom-na-wynajem-x", "Dom na wynajem")
    assert portal_check._is_rental("https://x.pl/oferta/dom", "Ładny dom do wynajęcia")
    # sprzedaz NIE jest wynajmem
    assert not portal_check._is_rental("https://www.otodom.pl/pl/oferta/dom-na-sprzedaz-x", "dom na sprzedaż")


def test_best_verdict_prefers_confirmed_over_rejected():
    verdicts = [
        verify.MatchVerdict("olx", "u1", "REJECTED"),
        verify.MatchVerdict("otodom", "u2", "CONFIRMED"),
    ]
    assert verify.best_verdict(verdicts) == "CONFIRMED"


def test_best_verdict_empty_is_none():
    assert verify.best_verdict([]) is None


# ------------------- ekstrakcja strukturalna per-portal -------------------
# Zweryfikowane na zywo (22.07.2026) na realnych ofertach; testy tu uzywaja
# syntetycznego HTML (bez sieci) do pilnowania samego parsowania.

def test_meta_content_ignores_attribute_order():
    # zweryfikowane na zywo: Gratka i Morizon ukladaja atrybuty <meta> w roznej
    # kolejnosci (raz property przed content, raz po) — parsowanie nie moze
    # zakladac konkretnej kolejnosci
    html_a = '<meta property="og:description" content="wersja A">'
    html_b = '<meta name="og:description" content="wersja B" property="og:description">'
    assert verify._meta_content(html_a, "og:description") == "wersja A"
    assert verify._meta_content(html_b, "og:description") == "wersja B"


def test_facts_from_meta_description_parses_area_and_plot():
    # dokladny format zweryfikowany na zywo, identyczny na Gratka i Morizon
    # (wspolny wlasciciel, Grupa Domodi) dla tej samej nieruchomosci
    body = '<meta property="og:description" content="Sprawdź dom - 296 m² (pow. działki 1 224 m²) za 1 599 000 zł - Boża Wola">'
    facts = verify._facts_from_meta_description(body)
    assert facts is not None
    assert facts.area_m2 == 296.0
    assert facts.terrain_m2 == 1224.0


def test_facts_from_meta_description_handles_nbsp():
    # NBSP (\xa0) jako separator tysiecy — zweryfikowane na zywo na Morizon
    body = '<meta name="og:description" content="dom - 296 m² (pow. działki 1\xa0224 m²) za 1 599 000 zł">'
    facts = verify._facts_from_meta_description(body)
    assert facts is not None
    assert facts.terrain_m2 == 1224.0


def test_facts_from_meta_description_none_when_no_match():
    assert verify._facts_from_meta_description('<meta name="description" content="zupelnie inny tekst">') is None


def test_facts_from_domiporta_requires_matching_url():
    import json as json_module
    ld = {
        "@type": "RealEstateListing", "url": "https://www.domiporta.pl/nieruchomosci/x/123456",
        "datePosted": "2026-01-07",
        "itemOffered": {"floorSize": {"value": 140}, "yearBuilt": 2025,
                         "geo": {"latitude": 52.14, "longitude": 20.71}},
    }
    body = f'<script type="application/ld+json">{json_module.dumps(ld)}</script>'
    # URL się zgadza -> dane zaufane
    facts = verify._facts_from_domiporta(body, "https://www.domiporta.pl/nieruchomosci/x/123456")
    assert facts is not None
    assert facts.area_m2 == 140
    assert facts.lat == 52.14

    # URL się NIE zgadza (np. blok z innej/kategorii strony) -> odrzucone,
    # zeby nie podpisac cudzych danych pod nasz lead
    facts_wrong = verify._facts_from_domiporta(body, "https://www.domiporta.pl/nieruchomosci/inna-oferta/999999")
    assert facts_wrong is None


def test_facts_from_rynekpierwotny_matches_by_path():
    import json as json_module
    ld = {
        "@type": "ApartmentComplex", "url": "/oferty/csi-development/osiedle-x-14812/",
        "geo": {"latitude": 52.22, "longitude": 20.80},
    }
    body = f'<script type="application/ld+json">{json_module.dumps(ld)}</script>'
    facts = verify._facts_from_rynekpierwotny(body, "https://rynekpierwotny.pl/oferty/csi-development/osiedle-x-14812/")
    assert facts is not None
    assert facts.market == "primary"
    assert facts.lat == 52.22


# ------------------- Zadanie 1: ogloszenia archiwalne/wygasle -------------------
# Kazdy z tych wzorcow zweryfikowany na zywo (23.07.2026) na realnych
# ogloszeniach wskazanych przez Adama jako blednie pokazane linki:
# ST-MZ-PR/WNIOSEK/10447/2026 (Otodom, HTTP 410 + ad.status="removed"),
# ST-MZ-WM/WNIOSEK/9227/2026 (to samo), ST-MZ-OT/WNIOSEK/5992/2026 (Morizon,
# HTTP 404 bez przekierowania). Testy tu mockuja `requests.get`, zeby pilnowac
# tych dokladnych wzorcow bez sieci.

class _FakeResp:
    def __init__(self, status_code=200, url="http://x", text=""):
        self.status_code = status_code
        self.url = url
        self.text = text


def test_fetch_otodom_facts_http_410_with_live_looking_json_is_dead(monkeypatch):
    # Realny przypadek: HTTP 410, ale __NEXT_DATA__.ad wciaz w pelni obecny
    # (tytul, daty, wspolrzedne) — bez sprawdzenia kodu statusu wygladaloby
    # to jak w pelni poprawne ogloszenie
    import json as json_module
    next_data = {"props": {"pageProps": {"ad": {
        "status": "removed", "title": "Stare ogloszenie", "market": "primary",
        "target": {}, "location": {"coordinates": {}},
    }}}}
    body = f'<script id="__NEXT_DATA__" crossorigin="anonymous">{json_module.dumps(next_data)}</script>'
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=410, url=a[0], text=body))
    facts = verify.fetch_otodom_facts("https://www.otodom.pl/pl/oferta/stare-id")
    assert facts is not None and facts.dead


def test_fetch_otodom_facts_ad_status_removed_even_with_200(monkeypatch):
    # Zabezpieczenie niezalezne od HTTP-statusu — gdyby Otodom kiedys zaczal
    # zwracac 200 dla usunietych ofert
    import json as json_module
    next_data = {"props": {"pageProps": {"ad": {
        "status": "removed", "market": "primary", "target": {}, "location": {"coordinates": {}},
    }}}}
    body = f'<script id="__NEXT_DATA__">{json_module.dumps(next_data)}</script>'
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=200, url=a[0], text=body))
    facts = verify.fetch_otodom_facts("https://www.otodom.pl/pl/oferta/usuniete-ale-200")
    assert facts is not None and facts.dead


def test_fetch_otodom_facts_live_ad_status_active_not_dead(monkeypatch):
    import json as json_module
    next_data = {"props": {"pageProps": {"ad": {
        "status": "active", "market": "primary", "target": {"Area": "100"},
        "location": {"coordinates": {"latitude": 52.1, "longitude": 21.0}},
        "advertiserType": "business",
    }}}}
    body = f'<script id="__NEXT_DATA__">{json_module.dumps(next_data)}</script>'
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=200, url=a[0], text=body))
    facts = verify.fetch_otodom_facts("https://www.otodom.pl/pl/oferta/zywe-id")
    assert facts is not None and not facts.dead
    assert facts.area_m2 == 100.0


def test_fetch_html_facts_http_404_no_redirect_is_dead_gratka(monkeypatch):
    # Zweryfikowane na zywo: Gratka i Morizon zwracaja HTTP 404 BEZ
    # przekierowania dla usunietych ofert (tytul "Pod tym adresem nic nie ma...")
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=404, url=a[0], text="<title>Pod tym adresem nic nie ma...</title>"))
    facts = verify.fetch_html_facts("gratka", "https://gratka.pl/nieruchomosci/x/ob/1")
    assert facts is not None and facts.dead


def test_fetch_html_facts_http_404_no_redirect_is_dead_morizon(monkeypatch):
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=404, url=a[0], text="<title>Pod tym adresem nic nie ma...</title>"))
    facts = verify.fetch_html_facts("morizon", "https://www.morizon.pl/oferta/x")
    assert facts is not None and facts.dead


def test_fetch_html_facts_http_404_rynekpierwotny(monkeypatch):
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=404, url=a[0], text="<title>404 - Nie znaleziono strony</title>"))
    facts = verify.fetch_html_facts("rynekpierwotny", "https://rynekpierwotny.pl/oferty/x/")
    assert facts is not None and facts.dead


def test_fetch_html_facts_live_200_not_dead(monkeypatch):
    body = '<meta property="og:description" content="dom - 200 m² (pow. działki 500 m²) za 900 000 zł">'
    monkeypatch.setattr(verify.requests, "get",
                         lambda *a, **k: _FakeResp(status_code=200, url=a[0], text=body))
    facts = verify.fetch_html_facts("gratka", "https://gratka.pl/nieruchomosci/x/ob/1")
    assert facts is not None and not facts.dead
    assert facts.area_m2 == 200.0
