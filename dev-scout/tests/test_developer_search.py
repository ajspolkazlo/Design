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


class _FakeResp:
    def __init__(self, text="", status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "CACHE_DB_PATH", tmp_path / "developer_search_cache.sqlite3")
    monkeypatch.setenv(ds.BRAVE_API_KEY_ENV_VAR, "fake-key-for-tests")


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
