"""
Testy dla src/developer_search.py — bez sieci, mockuje requests.get i
_search_brave. Zawiera regresje na realnym falszywym trafieniu zlapanym na
zywo 23.07.2026: "TOP INVESTMENT Sp. z o.o." (marka rzeczywista) trafilo
tekstowo w companiesmarketcap.com, kompletnie niezwiazana strone o rynkach
finansowych — patrz docstring developer_search._rank_candidate.

Uruchomienie: python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import developer_search as ds

# oryginalne implementacje discovery (fixture ponizej podmienia je na stuby
# zwracajace [], zeby find_developer_site nie ruszal sieci — dedykowane testy
# tych funkcji wolaja te oryginaly wprost)
_REAL_DISCOVER_CRTSH = ds._discover_via_crtsh
_REAL_DISCOVER_DDG = ds._discover_via_duckduckgo


class _FakeResp:
    def __init__(self, text="", status_code=200, url=""):
        self.text = text
        self.status_code = status_code
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "CACHE_DB_PATH", tmp_path / "developer_search_cache.sqlite3")
    monkeypatch.setenv(ds.BRAVE_API_KEY_ENV_VAR, "fake-key-for-tests")
    # domyslnie BRAK klucza Places w testach — istniejace testy sciezki Brave
    # maja wiec dzialac dokladnie tak jak przed dodaniem Zadania Places (krok
    # Places jest po prostu pomijany bez klucza, patrz lookup_website_via_places)
    monkeypatch.delenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, raising=False)
    # domyslnie zgadywanie domeny (krok bez klucza, patrz guess_developer_domain)
    # nic nie znajduje — istniejace testy Brave/Places maja wiec dzialac
    # dokladnie tak jak przed dodaniem tego kroku; testy ponizej dedykowane
    # zgadywaniu domeny nadpisuja to explicite
    monkeypatch.setattr(ds, "_probe_domain", lambda domain, timeout=8: None)
    # darmowe warstwy odkrywania (crt.sh / DuckDuckGo) domyslnie NIC nie zwracaja
    # w testach — zero sieci; dedykowane testy ponizej nadpisuja to explicite
    monkeypatch.setattr(ds, "_discover_via_crtsh", lambda investor, timeout=15: [])
    monkeypatch.setattr(ds, "_discover_via_duckduckgo", lambda investor, timeout=20: [])
    monkeypatch.setattr(ds, "_ddg_blocked", False, raising=False)


# --------------------------- is_individual / core_name ---------------------------

def test_is_individual_true_for_person_name():
    assert ds.is_individual("Jan Kowalski")


def test_is_individual_false_for_company_signal():
    assert not ds.is_individual("Testowa Firma Sp. z o.o.")


def test_is_individual_handles_extra_space_bug():
    # zweryfikowany na zywo bug: "M4 Sp. z o. o." (dodatkowa spacja przed "o.")
    # nie dopasowywalo sie plain substringiem do sygnalu "sp. z o.o."
    assert not ds.is_individual("M4 Sp. z o. o.")


def test_core_name_strips_legal_form():
    assert ds.core_name("TOP INVESTMENT Sp. z o.o.") == "top investment"


# --------------------------- _is_blocked_domain ---------------------------

def test_blocks_real_estate_portals():
    assert ds._is_blocked_domain("otodom.pl")
    assert ds._is_blocked_domain("www.olx.pl".removeprefix("www."))
    assert ds._is_blocked_domain("sub.morizon.pl")


def test_blocks_generic_aggregators():
    assert ds._is_blocked_domain("money.pl")
    assert ds._is_blocked_domain("aleo.com")


def test_does_not_block_ordinary_company_domain():
    assert not ds._is_blocked_domain("topinvestment.pl")


# --------------------------- _rank_candidate ---------------------------

def test_rank_candidate_domain_match_is_priority_2():
    result = {"url": "https://topinvestment.pl/", "title": "Top Investment", "description": ""}
    ranked = ds._rank_candidate(result, ds.core_name("TOP INVESTMENT Sp. z o.o."))
    assert ranked is not None
    assert ranked[0] == 2


def test_rank_candidate_blocked_portal_returns_none():
    result = {"url": "https://www.otodom.pl/oferta/x", "title": "Top Investment mieszkania", "description": ""}
    assert ds._rank_candidate(result, ds.core_name("TOP INVESTMENT Sp. z o.o.")) is None


def test_rank_candidate_regression_top_investment_false_positive():
    """Regresja na realnym przypadku: sama fraza w tresci strony (bez dowodu
    domenowego) NIGDY nie moze dac priorytetu 2 — tylko 1 (kandydat_niepewny)."""
    result = {
        "url": "https://companiesmarketcap.com/investment/largest-investment-companies-by-market-cap/",
        "title": "Largest investment companies by market cap",
        "description": "Top investment companies ranked by market cap",
    }
    ranked = ds._rank_candidate(result, ds.core_name("TOP INVESTMENT Sp. z o.o."))
    assert ranked is not None
    assert ranked[0] == 1  # tekstowe trafienie, nigdy 2


def test_rank_candidate_requires_all_long_tokens_in_domain():
    # tylko jeden z dwoch tokenow nazwy w domenie -> nie priorytet 2
    result = {"url": "https://investmentgroup.pl/", "title": "", "description": ""}
    ranked = ds._rank_candidate(result, ds.core_name("TOP INVESTMENT Sp. z o.o."))
    assert ranked is None or ranked[0] != 2


def test_rank_candidate_social_fallback_is_priority_0():
    result = {"url": "https://www.facebook.com/topinvestment", "title": "Top Investment",
              "description": "Top Investment deweloper"}
    ranked = ds._rank_candidate(result, ds.core_name("TOP INVESTMENT Sp. z o.o."))
    assert ranked == (0, "fallback społecznościowy")


# --------------------------- find_developer_site: end-to-end statusy ---------------------------

def test_find_developer_site_skips_individual(monkeypatch):
    called = []
    monkeypatch.setattr(ds, "_search_brave", lambda *a, **k: called.append(1))
    site = ds.find_developer_site("Jan Kowalski")
    assert site.status == ds.STATUS_INDIVIDUAL
    assert not called  # zero zapytan do wyszukiwarki dla osoby fizycznej


def test_find_developer_site_regression_top_investment_caps_at_uncertain(monkeypatch):
    """Pelna regresja end-to-end na zlapanym na zywo falszywym trafieniu —
    musi wyladowac jako kandydat_niepewny, NIGDY jako potwierdzona/prawdopodobna."""
    fake_results = [{
        "url": "https://companiesmarketcap.com/investment/largest-investment-companies-by-market-cap/",
        "title": "Largest investment companies by market cap",
        "description": "Top investment companies ranked by market cap",
    }]
    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: fake_results)
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    site = ds.find_developer_site("TOP INVESTMENT Sp. Z o.o.", nip="5291714728")
    assert site.status == ds.STATUS_UNCERTAIN
    assert site.url == fake_results[0]["url"]


def test_find_developer_site_domain_match_without_nip_is_likely(monkeypatch):
    fake_results = [{"url": "https://topinvestment.pl/", "title": "Top Investment", "description": "deweloper"}]
    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: fake_results)
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeResp(text="strona bez numeru NIP"))
    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", nip="5291714728")
    assert site.status == ds.STATUS_LIKELY


def test_find_developer_site_domain_match_with_nip_is_confirmed(monkeypatch):
    fake_results = [{"url": "https://topinvestment.pl/", "title": "Top Investment", "description": "deweloper"}]
    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: fake_results)
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeResp(text="NIP: 529-171-47-28, ul. Testowa 1"))
    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", nip="5291714728")
    assert site.status == ds.STATUS_CONFIRMED
    assert site.matched_on == "NIP w treści strony"


def test_find_developer_site_no_results_is_not_found(monkeypatch):
    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: [])
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    site = ds.find_developer_site("Nieznana Firma Sp. z o.o.")
    assert site.status == ds.STATUS_NOT_FOUND


def test_find_developer_site_no_api_key_returns_not_found_without_caching(monkeypatch):
    monkeypatch.delenv(ds.BRAVE_API_KEY_ENV_VAR, raising=False)
    called = []
    monkeypatch.setattr(ds, "_search_brave", lambda *a, **k: called.append(1))
    site = ds.find_developer_site("Testowa Firma Sp. z o.o.")
    assert site.status == ds.STATUS_NOT_FOUND
    assert not called
    # brak klucza -> nic nie trafia do cache (nastepne wywolanie tez powinno probowac szukac)
    conn = ds._cache_connect()
    try:
        assert ds._cache_get(conn, ds._norm("Testowa Firma Sp. z o.o.")) is None
    finally:
        conn.close()


# --------------------------- cache: hit/miss + TTL ---------------------------

def test_cache_hit_avoids_second_search(monkeypatch):
    calls = []

    def fake_search(query, api_key, timeout=15):
        calls.append(query)
        return [{"url": "https://topinvestment.pl/", "title": "Top Investment", "description": "deweloper"}]

    monkeypatch.setattr(ds, "_search_brave", fake_search)
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeResp(text="brak numeru"))

    site1 = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.")
    assert len(calls) == 1
    site2 = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.")
    assert len(calls) == 1  # drugie wywolanie trafia w cache, zero nowych zapytan
    assert site2.status == site1.status
    assert site2.url == site1.url


def test_cache_not_found_expires_after_ttl(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: [])
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)

    site = ds.find_developer_site("Nieznana Firma Sp. z o.o.")
    assert site.status == ds.STATUS_NOT_FOUND

    # zasymuluj, ze wpis w cache ma 31 dni (poza TTL nie_znaleziono = 30 dni)
    conn = ds._cache_connect()
    try:
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        conn.execute(
            "UPDATE developer_sites SET checked_at = ? WHERE name_key = ?",
            (old_ts, ds._norm("Nieznana Firma Sp. z o.o.")),
        )
        conn.commit()
        assert ds._cache_get(conn, ds._norm("Nieznana Firma Sp. z o.o.")) is None
    finally:
        conn.close()


def test_cache_found_result_never_expires(monkeypatch):
    from datetime import datetime, timedelta, timezone

    fake_results = [{"url": "https://topinvestment.pl/", "title": "Top Investment", "description": "deweloper"}]
    monkeypatch.setattr(ds, "_search_brave", lambda query, api_key, timeout=15: fake_results)
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeResp(text="brak numeru"))

    ds.find_developer_site("TOP INVESTMENT Sp. z o.o.")

    conn = ds._cache_connect()
    try:
        very_old = (datetime.now(timezone.utc) - timedelta(days=3650)).isoformat()
        conn.execute(
            "UPDATE developer_sites SET checked_at = ? WHERE name_key = ?",
            (very_old, ds._norm("TOP INVESTMENT Sp. z o.o.")),
        )
        conn.commit()
        cached = ds._cache_get(conn, ds._norm("TOP INVESTMENT Sp. z o.o."))
        assert cached is not None  # status != nie_znaleziono -> brak TTL, zawsze wazny
        assert cached.status == ds.STATUS_LIKELY
    finally:
        conn.close()


# --------------------------- Google Places: sygnal podstawowy ---------------------------

def test_lookup_website_via_places_no_key_returns_none_without_network(monkeypatch):
    called = []
    monkeypatch.setattr(ds, "_search_places", lambda *a, **k: called.append(1))
    site = ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno")
    assert site is None
    assert not called  # bez klucza zero zapytan sieciowych


def test_lookup_website_via_places_confirms_with_website(monkeypatch):
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    fake_places = [{"id": "abc", "displayName": {"text": "Top Investment"},
                     "websiteUri": "https://topinvestment.pl/", "formattedAddress": "Warszawa"}]
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: fake_places)

    site = ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno")
    assert site is not None
    assert site.status == ds.STATUS_CONFIRMED
    assert site.url == "https://topinvestment.pl/"
    assert "Places" in site.matched_on


def test_lookup_website_via_places_returns_none_when_no_website(monkeypatch):
    """Brak websiteUri w wynikach (albo brak wynikow w ogole) -> None, zeby
    find_developer_site spadl na fallback Brave, a NIE zaklasyfikowal od razu
    jako 'nie_znaleziono' (to by uniemozliwilo probe przez Brave)."""
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    fake_places = [{"id": "abc", "displayName": {"text": "Nieznana Firma"}, "formattedAddress": "Warszawa"}]
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: fake_places)

    assert ds.lookup_website_via_places("Nieznana Firma Sp. z o.o.", "Piaseczno") is None

    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: [])
    assert ds.lookup_website_via_places("Inna Firma Sp. z o.o.", "Piaseczno") is None


def test_lookup_website_via_places_filters_blocked_domains(monkeypatch):
    # Places zwraca "website" ktory jest w rzeczywistosci portalem nieruchomosci
    # (np. profil firmowy) — nie moze byc uznany za wlasna strone dewelopera
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    fake_places = [{"websiteUri": "https://www.otodom.pl/deweloper/top-investment"}]
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: fake_places)
    assert ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno") is None


def test_lookup_website_via_places_network_error_falls_back_without_caching(monkeypatch):
    import requests

    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")

    def _raise(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr(ds, "_search_places", _raise)
    assert ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno") is None

    # blad sieciowy nie zostal zapisany do cache -> kolejna proba znow odpytuje Places
    calls = []
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: (calls.append(1) or []))
    ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno")
    assert len(calls) == 1


def test_lookup_website_via_places_caches_result(monkeypatch):
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    calls = []

    def fake_search(query, api_key, timeout=15):
        calls.append(query)
        return [{"websiteUri": "https://topinvestment.pl/"}]

    monkeypatch.setattr(ds, "_search_places", fake_search)
    site1 = ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno")
    site2 = ds.lookup_website_via_places("TOP INVESTMENT Sp. z o.o.", "Piaseczno")
    assert len(calls) == 1  # drugie wywolanie trafia w cache Places
    assert site1.url == site2.url == "https://topinvestment.pl/"


def test_lookup_website_via_places_not_found_expires_after_ttl(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: [])

    assert ds.lookup_website_via_places("Nieznana Firma Sp. z o.o.", "Piaseczno") is None

    conn = ds._cache_connect()
    try:
        cache_key = f"{ds._norm('Nieznana Firma Sp. z o.o.')}|{ds._norm('Piaseczno')}"
        old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        conn.execute("UPDATE places_lookup SET checked_at = ? WHERE cache_key = ?", (old_ts, cache_key))
        conn.commit()
        hit, _ = ds._places_cache_get(conn, cache_key)
        assert not hit  # TTL wygasl -> traktowane jak brak wpisu, trzeba odpytac ponownie
    finally:
        conn.close()


def test_find_developer_site_uses_places_before_brave(monkeypatch):
    """Places daje wynik -> Brave NIGDY nie jest odpytywany (Places jest
    sygnalem podstawowym, sprawdzanym jako pierwszy)."""
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    monkeypatch.setattr(ds, "_search_places",
                         lambda query, api_key, timeout=15: [{"websiteUri": "https://topinvestment.pl/"}])
    brave_calls = []
    monkeypatch.setattr(ds, "_search_brave", lambda *a, **k: brave_calls.append(1))

    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", miejscowosc="Piaseczno")
    assert site.status == ds.STATUS_CONFIRMED
    assert site.url == "https://topinvestment.pl/"
    assert not brave_calls


def test_find_developer_site_falls_back_to_brave_when_places_empty(monkeypatch):
    """Places nic nie znajduje -> normalny fallback do Brave, bez zmian w
    logice sciezki Brave (regresja: upewnia sie, ze dodanie Places nie
    zepsulo istniejacego zachowania)."""
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    monkeypatch.setattr(ds, "_search_places", lambda query, api_key, timeout=15: [])
    monkeypatch.setattr(ds, "_search_brave",
                         lambda query, api_key, timeout=15: [
                             {"url": "https://topinvestment.pl/", "title": "Top Investment", "description": "deweloper"}
                         ])
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeResp(text="brak numeru"))

    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", miejscowosc="Piaseczno")
    assert site.status == ds.STATUS_LIKELY  # sciezka Brave, dowod domenowy bez NIP
    assert site.url == "https://topinvestment.pl/"


# --------------------------- zgadywanie domeny: sygnal darmowy ---------------------------

def test_guess_domain_candidates_flat_and_hyphenated():
    candidates = ds._guess_domain_candidates(ds.core_name("TOP INVESTMENT Sp. z o.o."))
    assert "topinvestment.pl" in candidates
    assert "top-investment.pl" in candidates
    assert "topinvestment.com.pl" in candidates
    assert "topinvestment.eu" in candidates
    assert "topinvestment.com" in candidates


def test_guess_domain_candidates_single_token_no_duplicate():
    candidates = ds._guess_domain_candidates(ds.core_name("Aranda Sp. z o.o."))
    assert candidates.count("aranda.pl") == 1  # flat == hyphen dla jednego slowa, bez duplikatu


def test_guess_developer_domain_too_short_name_skips_without_network(monkeypatch):
    calls = []
    monkeypatch.setattr(ds, "_probe_domain", lambda domain, timeout=8: calls.append(domain))
    site = ds.guess_developer_domain("M4 Sp. z o. o.")  # "m4" -> 2 znaki po splaszczeniu, za krotkie
    assert site is None
    assert not calls


def test_guess_developer_domain_confirms_when_name_in_content(monkeypatch):
    def fake_probe(domain, timeout=8):
        if domain == "topinvestment.pl":
            return "https://topinvestment.pl/", "Top Investment sp. z o.o. — mieszkania na sprzedaż w Piasecznie"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    site = ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.")
    assert site is not None
    assert site.status == ds.STATUS_LIKELY  # bez NIP -> nie wyzej niz prawdopodobna
    assert site.url == "https://topinvestment.pl/"


def test_guess_developer_domain_confirms_with_nip(monkeypatch):
    def fake_probe(domain, timeout=8):
        if domain == "topinvestment.pl":
            return "https://topinvestment.pl/", "Top Investment sp. z o.o., NIP 5291714728"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    site = ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.", nip="5291714728")
    assert site is not None
    assert site.status == ds.STATUS_CONFIRMED
    assert "NIP" in site.matched_on


def test_guess_developer_domain_skips_parking_page(monkeypatch):
    """Regresja: domena zyje (HTTP 200) ale to strona parkingowa/na sprzedaz
    — NIE moze byc uznana za trafienie, nawet jesli przypadkiem zawiera
    fragmenty nazwy w jakims boilerplate."""
    def fake_probe(domain, timeout=8):
        return None  # _probe_domain juz sam odrzuca parking (patrz _looks_like_parking_page) — tu symulujemy efekt

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    assert ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.") is None


def test_looks_like_parking_page_detects_common_markers():
    assert ds._looks_like_parking_page("This domain is for sale. Contact us for a quote.")
    assert ds._looks_like_parking_page("Ta domena jest na sprzedaż — zarezerwuj teraz.")
    assert not ds._looks_like_parking_page("Top Investment sp. z o.o. — mieszkania na sprzedaż")


def test_guess_developer_domain_content_without_name_falls_through(monkeypatch):
    def fake_probe(domain, timeout=8):
        return "https://topinvestment.pl/", "zupelnie niezwiazana tresc, bez nazwy inwestora"

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    assert ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.") is None


def test_guess_developer_domain_rejects_blocked_final_domain(monkeypatch):
    # zgadnieta domena przekierowuje finalnie na portal nieruchomosci -> odrzucone
    monkeypatch.setattr(ds, "_probe_domain",
                         lambda domain, timeout=8: ("https://www.otodom.pl/", "Top Investment na Otodom"))
    assert ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.") is None


def test_find_developer_site_uses_domain_guess_before_places_and_brave(monkeypatch):
    """Zgadywanie domeny daje wynik -> ani Places, ani Brave NIE sa odpytywane
    (krok darmowy jest sprawdzany jako pierwszy, patrz docstring modulu)."""
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")

    def fake_probe(domain, timeout=8):
        if domain == "topinvestment.pl":
            return "https://topinvestment.pl/", "Top Investment sp. z o.o. — mieszkania na sprzedaż"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    places_calls, brave_calls = [], []
    monkeypatch.setattr(ds, "_search_places", lambda *a, **k: places_calls.append(1))
    monkeypatch.setattr(ds, "_search_brave", lambda *a, **k: brave_calls.append(1))

    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", miejscowosc="Piaseczno")
    assert site.status == ds.STATUS_LIKELY
    assert site.url == "https://topinvestment.pl/"
    assert not places_calls
    assert not brave_calls


def test_find_developer_site_falls_back_past_domain_guess_to_places(monkeypatch):
    """Zgadywanie domeny nic nie znajduje -> normalny fallback do Places
    (regresja: dodanie kroku darmowego nie zepsulo istniejacej sciezki)."""
    monkeypatch.setenv(ds.GOOGLE_PLACES_API_KEY_ENV_VAR, "fake-places-key")
    monkeypatch.setattr(ds, "_probe_domain", lambda domain, timeout=8: None)
    monkeypatch.setattr(ds, "_search_places",
                         lambda query, api_key, timeout=15: [{"websiteUri": "https://topinvestment.pl/"}])

    site = ds.find_developer_site("TOP INVESTMENT Sp. z o.o.", miejscowosc="Piaseczno")
    assert site.status == ds.STATUS_CONFIRMED
    assert site.url == "https://topinvestment.pl/"


# --------------------------- regresje na zywo zlapanych bledach (23.07.2026) ---------------------------

def test_guess_developer_domain_regression_foreign_homonym_rejected(monkeypatch):
    """Zlapane na zywo: 'TOP INVESTMENT Sp. z o.o.' (Grodzisk Mazowiecki)
    zgadlo domene top-investment.eu, ktora nalezy do NIEMIECKIEGO
    'TOP-Investment GmbH' — zupelnie inna firma o tej samej marce. Sama
    obecnosc nazwy w tresci NIE moze wystarczyc bez zadnego polskiego
    sygnalu (patrz _has_poland_specificity_signal)."""
    def fake_probe(domain, timeout=8):
        if domain == "top-investment.eu":
            return "https://top-investment.eu/", "TOP-Investment GmbH — Impressum, Deutschland, Kontakt"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    assert ds.guess_developer_domain("TOP INVESTMENT Sp. z o.o.") is None


def test_guess_developer_domain_regression_website_builder_placeholder_rejected():
    """Zlapane na zywo: 'ROYAL DEVELOPMENT SP Z O.O.' (Legionowo) zgadlo
    domene royaldevelopment.com, ktora byla pustym szablonem kreatora stron
    Dynadot ('GET STARTED', 'WEBSITE BUILDER') — nie realna strona firmy.
    Pierwsza wersja _PARKING_MARKERS lapala tylko klasyczny "domain for
    sale" i przepuszczala to jako trafienie."""
    raw_html = "<html><body>ROYAL DEVELOPMENT home COVER HEADER GET STARTED DYNADOT WEBSITE BUILDER</body></html>"
    assert ds._looks_like_parking_page(raw_html)


def test_has_poland_specificity_signal_via_legal_form():
    assert ds._has_poland_specificity_signal("Firma XYZ sp. z o.o., ul. Testowa 1", None)


def test_has_poland_specificity_signal_via_miejscowosc():
    assert ds._has_poland_specificity_signal("Nasza inwestycja w Grodzisku Mazowieckim", "Grodzisk Mazowiecki")


def test_has_poland_specificity_signal_via_diacritics_density():
    assert ds._has_poland_specificity_signal(
        "mieszkania na sprzedaż, świetna lokalizacja, ładne wykończenie, więcej informacji wkrótce", None)


def test_has_poland_specificity_signal_false_for_generic_foreign_text():
    assert not ds._has_poland_specificity_signal("Welcome to our company website, contact us today", None)


def test_guess_developer_domain_uses_miejscowosc_to_confirm(monkeypatch):
    def fake_probe(domain, timeout=8):
        if domain == "zielonywolomin.pl":
            return "https://zielonywolomin.pl/", "Zielony Wolomin - nowa inwestycja w Wolominie"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    site = ds.guess_developer_domain("ZIELONY WOŁOMIN Sp. z o.o.", miejscowosc="Wołomin")
    assert site is not None
    assert site.status == ds.STATUS_LIKELY


# --------------------------- generowanie kandydatow: kolejnosc + dropowanie wypelniaczy ---------------------------

def test_guess_domain_bases_drops_filler_preserving_order():
    """Regresja na przypadku zgloszonym przez Adama: 'DOM GRANDE DEVELOPER'
    ma domene grandedeveloper.pl — porzucone 'dom', ale KOLEJNOSC 'grande
    developer' zachowana (nie 'developer grande')."""
    bases = ds._guess_domain_bases(ds.core_name("DOM GRANDE DEVELOPER Sp. z o.o."))
    assert "grandedeveloper" in bases       # dropniete 'dom', kolejnosc zachowana
    assert "domgrandedeveloper" in bases     # pelna nazwa tez wciaz probowana
    assert "developergrande" not in bases    # NIGDY nie odwracamy kolejnosci


def test_guess_domain_bases_adds_distinctive_single_token():
    bases = ds._guess_domain_bases(ds.core_name("GRANDE DEVELOPER Sp. z o.o."))
    assert "grande" in bases  # sam token marki jako oddzielny kandydat


def test_brand_tokens_drops_generic_words():
    assert ds._brand_tokens(ds.core_name("DOM GRANDE DEVELOPER Sp. z o.o.")) == {"grande"}
    assert ds._brand_tokens(ds.core_name("ROYAL DEVELOPMENT Sp. z o.o.")) == {"royal"}


# --------------------------- ekstrakcja identyfikatorow z rejestru ze stopki ---------------------------

def test_extract_registry_ids_parses_krs_and_nip():
    ids = ds._extract_registry_ids("Grodzisk Mazowiecki NIP 529 182 75 04 REGON 384154636 KRS 0000800084")
    assert ids["krs"] == "0000800084"
    assert ids["nip"] == "5291827504"  # znormalizowany, bez spacji


def test_extract_registry_ids_empty_when_none():
    assert ds._extract_registry_ids("zwykła treść strony bez identyfikatorów") == {}


class _FakeKrsInfo:
    def __init__(self, name, nip=None, found=True):
        self.name = name
        self.nip = nip
        self.found = found


def test_confirm_via_footer_registry_brand_overlap_is_likely(monkeypatch):
    """Sedno rozwiazania zgloszonego przez Adama: KRS ze stopki -> oficjalna
    nazwa dzieli markę z inwestorem RWDZ, mimo innej formy prawnej."""
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                         lambda krs, timeout=15: _FakeKrsInfo("GRANDE DEWELOPER ADRIAN ZŁOTUCHA SPÓŁKA KOMANDYTOWA"))
    body = "Grande Developer KRS 0000800084 Grodzisk Mazowiecki"
    result = ds._confirm_via_footer_registry(body, "DOM GRANDE DEVELOPER Sp. z o.o.", "grandedeveloper", None)
    assert result is not None
    status, reason = result
    assert status == ds.STATUS_LIKELY
    assert "grande" in reason.lower()


def test_confirm_via_footer_registry_nip_identity_is_confirmed(monkeypatch):
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                         lambda krs, timeout=15: _FakeKrsInfo("INNA NAZWA SP Z O O", nip="5291827504"))
    body = "Firma XYZ KRS 0000800084"
    result = ds._confirm_via_footer_registry(body, "Firma XYZ Sp. z o.o.", "firmaxyz", "529-182-75-04")
    assert result is not None
    assert result[0] == ds.STATUS_CONFIRMED


def test_confirm_via_footer_registry_no_overlap_returns_none(monkeypatch):
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                         lambda krs, timeout=15: _FakeKrsInfo("ZUPELNIE INNA PIZZERIA SPÓŁKA KOMANDYTOWA"))
    body = "Coś tam KRS 0000999999"
    result = ds._confirm_via_footer_registry(body, "DOM GRANDE DEVELOPER Sp. z o.o.", "grandedeveloper", None)
    assert result is None  # brak wspolnego tokenu marki -> nie potwierdzamy


def test_guess_developer_domain_registry_footer_end_to_end(monkeypatch):
    """Pelna regresja na zgloszonym przypadku: marka 'Grande Developer' na
    stronie != zarejestrowana nazwa, ale KRS ze stopki mostkuje przez rejestr."""
    def fake_probe(domain, timeout=8):
        if domain == "grandedeveloper.pl":
            return "https://grandedeveloper.pl/", "Grande Developer | Domy pod Warszawą KRS 0000800084"
        return None

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                         lambda krs, timeout=15: _FakeKrsInfo("GRANDE DEWELOPER ADRIAN ZŁOTUCHA SPÓŁKA KOMANDYTOWA"))
    site = ds.guess_developer_domain("DOM GRANDE DEVELOPER Sp. Z o.o.", miejscowosc="Grodzisk Mazowiecki")
    assert site is not None
    assert site.url == "https://grandedeveloper.pl/"
    assert site.status == ds.STATUS_LIKELY
    assert "KRS" in site.matched_on


def test_guess_developer_domain_registry_path_guarded_by_coverage(monkeypatch):
    """Guard: pojedyncze generyczne slowo w domenie (coverage<2) NIE odpala
    potwierdzenia rejestrowego, nawet gdy strona ma jakis KRS."""
    calls = []

    def fake_probe(domain, timeout=8):
        # tylko domena z pojedynczego tokenu 'grande' zyje
        if domain == "grande.pl":
            return "https://grande.pl/", "Grande Pizza KRS 0000111111"
        return None

    def fake_krs(krs, timeout=15):
        calls.append(krs)
        return _FakeKrsInfo("GRANDE PIZZA SPÓŁKA KOMANDYTOWA")

    monkeypatch.setattr(ds, "_probe_domain", fake_probe)
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number", fake_krs)
    # 'dom grande developer' -> base 'grande' pokrywa tylko 1 token -> registry path pominiety
    site = ds.guess_developer_domain("DOM GRANDE DEVELOPER Sp. z o.o.")
    assert site is None
    assert not calls  # lookup KRS nie zostal nawet wywolany dla domeny 1-tokenowej


# --------------------------- Opcja B: crt.sh (Certificate Transparency) ---------------------------

class _FakeCrtResp:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload or []
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("nie JSON")
        return self._payload


def test_discover_via_crtsh_parses_domains(monkeypatch):
    payload = [
        {"name_value": "grandedeveloper.pl\nwww.grandedeveloper.pl"},
        {"name_value": "*.grandedeveloper.com"},
        {"name_value": "grandedeveloper.pl"},  # duplikat
    ]
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeCrtResp(200, payload))
    domains = _REAL_DISCOVER_CRTSH("DOM GRANDE DEVELOPER Sp. z o.o.")
    assert "grandedeveloper.pl" in domains
    assert "grandedeveloper.com" in domains
    assert domains.count("grandedeveloper.pl") == 1  # deduplikacja + zdjete www./*.


def test_discover_via_crtsh_seed_too_short_skips(monkeypatch):
    calls = []
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: calls.append(1))
    assert _REAL_DISCOVER_CRTSH("M4 Sp. z o.o.") == []  # 'm4' -> seed <8 znakow
    assert not calls


def test_discover_via_crtsh_http_502_graceful(monkeypatch):
    monkeypatch.setattr(ds.requests, "get", lambda *a, **k: _FakeCrtResp(502))
    assert _REAL_DISCOVER_CRTSH("GRANDE DEVELOPER Sp. z o.o.") == []


def test_discover_via_crtsh_network_error_graceful(monkeypatch):
    def boom(*a, **k):
        raise ds.requests.RequestException("down")
    monkeypatch.setattr(ds.requests, "get", boom)
    assert _REAL_DISCOVER_CRTSH("GRANDE DEVELOPER Sp. z o.o.") == []


# --------------------------- Opcja A: DuckDuckGo HTML ---------------------------

class _FakeDdgResp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def test_discover_via_duckduckgo_parses_result_domains(monkeypatch):
    monkeypatch.setattr(ds, "_ddg_blocked", False, raising=False)
    html = ('<a href="/l/?uddg=https%3A%2F%2Fgrandedeveloper.pl%2F">x</a>'
            '<a href="/l/?uddg=https%3A%2F%2Fwww.grandegroup.eu%2Fo-nas">y</a>')
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: _FakeDdgResp(200, html))
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    domains = _REAL_DISCOVER_DDG("DOM GRANDE DEVELOPER Sp. z o.o.")
    assert "grandedeveloper.pl" in domains
    assert "grandegroup.eu" in domains  # www. zdjete przez _domain_of


def test_discover_via_duckduckgo_anomaly_blocks_rest_of_run(monkeypatch):
    monkeypatch.setattr(ds, "_ddg_blocked", False, raising=False)
    monkeypatch.setattr(ds.requests, "post",
                        lambda *a, **k: _FakeDdgResp(202, "Please try again... anomaly detected"))
    monkeypatch.setattr(ds.time, "sleep", lambda *a: None)
    assert _REAL_DISCOVER_DDG("GRANDE DEVELOPER Sp. z o.o.") == []
    # po wykryciu blokady kolejne wywolania nie robia juz zadnego zapytania
    calls = []
    monkeypatch.setattr(ds.requests, "post", lambda *a, **k: calls.append(1))
    assert _REAL_DISCOVER_DDG("INNA FIRMA Sp. z o.o.") == []
    assert not calls


def test_discover_via_duckduckgo_network_error_graceful(monkeypatch):
    monkeypatch.setattr(ds, "_ddg_blocked", False, raising=False)
    def boom(*a, **k):
        raise ds.requests.RequestException("down")
    monkeypatch.setattr(ds.requests, "post", boom)
    assert _REAL_DISCOVER_DDG("GRANDE DEVELOPER Sp. z o.o.") == []


# --------------------------- discovery -> ta sama walidacja ---------------------------

def test_probe_and_classify_requires_brand_token_in_domain(monkeypatch):
    # domena wyniku wyszukiwarki bez tokenu marki -> odrzucona jeszcze przed pobraniem
    calls = []
    monkeypatch.setattr(ds, "_probe_domain", lambda domain, timeout=8: calls.append(domain))
    site = ds._probe_and_classify("GRANDE DEVELOPER Sp. z o.o.", "losowyportal.pl", None, None,
                                  source_note="wynik DuckDuckGo", require_brand_in_domain=True)
    assert site is None
    assert not calls  # nie pobrano — domena nie zawiera 'grande'


def test_probe_and_classify_discovery_confirmed_via_registry(monkeypatch):
    monkeypatch.setattr(ds, "_probe_domain",
                        lambda domain, timeout=8: ("https://grandedeveloper.pl/",
                                                   "Grande Developer KRS 0000800084 Grodzisk"))
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                        lambda krs, timeout=15: _FakeKrsInfo("GRANDE DEWELOPER ADRIAN ZŁOTUCHA SPÓŁKA KOMANDYTOWA"))
    site = ds._probe_and_classify("DOM GRANDE DEVELOPER Sp. z o.o.", "grandedeveloper.pl", None, "Grodzisk Mazowiecki",
                                  source_note="wynik crt.sh", require_brand_in_domain=True)
    assert site is not None
    assert site.status == ds.STATUS_LIKELY
    assert site.url == "https://grandedeveloper.pl/"


def test_find_developer_site_uses_crtsh_when_guess_fails(monkeypatch):
    """crt.sh znajduje domene, ktorej zgadywanie nie trafilo -> walidacja przez rejestr."""
    monkeypatch.setattr(ds, "_probe_domain",
                        lambda domain, timeout=8: (("https://grandedeveloper.pl/",
                                                    "Grande Developer KRS 0000800084 Grodzisk")
                                                   if domain == "grandedeveloper.pl" else None))
    monkeypatch.setattr(ds, "_discover_via_crtsh", lambda investor, timeout=15: ["grandedeveloper.pl"])
    monkeypatch.setattr(ds, "_discover_via_duckduckgo", lambda investor, timeout=20: [])
    monkeypatch.setattr(ds.company_lookup, "lookup_krs_by_number",
                        lambda krs, timeout=15: _FakeKrsInfo("GRANDE DEWELOPER ADRIAN ZŁOTUCHA SPÓŁKA KOMANDYTOWA"))
    site = ds.find_developer_site("DOM GRANDE DEVELOPER Sp. z o.o.", miejscowosc="Grodzisk Mazowiecki")
    assert site.status == ds.STATUS_LIKELY
    assert site.url == "https://grandedeveloper.pl/"


def test_find_developer_site_discovery_toggles_off(monkeypatch):
    """use_crtsh=False i use_duckduckgo=False -> discovery w ogole nie wolane."""
    monkeypatch.setattr(ds, "_discover_via_crtsh",
                        lambda investor, timeout=15: (_ for _ in ()).throw(AssertionError("crtsh nie powinno byc wolane")))
    monkeypatch.setattr(ds, "_discover_via_duckduckgo",
                        lambda investor, timeout=20: (_ for _ in ()).throw(AssertionError("ddg nie powinno byc wolane")))
    site = ds.find_developer_site("NIEZNANA FIRMA Sp. z o.o.", use_crtsh=False, use_duckduckgo=False)
    assert site.status == ds.STATUS_NOT_FOUND
