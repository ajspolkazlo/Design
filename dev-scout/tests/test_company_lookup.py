"""Testy dla src/company_lookup.py — bez sieci, mockuje requests.get."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import company_lookup as cl


class _FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data or {}

    def json(self):
        return self._json


def test_lookup_krs_by_number_parses_real_shape(monkeypatch):
    payload = {"odpis": {"dane": {"dzial1": {
        "danePodmiotu": {"nazwa": "TESTOWA SP. Z O.O.", "identyfikatory": {"nip": "1234567890"}},
        "siedzibaIAdres": {"adres": {"ulica": "UL. TESTOWA", "nrDomu": "1",
                                      "miejscowosc": "WARSZAWA", "kodPocztowy": "00-001"}},
    }}}}
    monkeypatch.setattr(cl.requests, "get", lambda *a, **k: _FakeResp(200, payload))
    info = cl.lookup_krs_by_number("250912")
    assert info.found
    assert info.source == "krs"
    assert info.nip == "1234567890"
    assert "TESTOWA" in info.name
    assert info.krs_number == "0000250912"  # zfill do 10 cyfr


def test_lookup_krs_by_number_not_found(monkeypatch):
    monkeypatch.setattr(cl.requests, "get", lambda *a, **k: _FakeResp(404, {}))
    info = cl.lookup_krs_by_number("9999999999")
    assert not info.found


def test_lookup_company_no_ceidg_token_does_not_error(monkeypatch):
    monkeypatch.delenv(cl.CEIDG_TOKEN_ENV_VAR, raising=False)
    info = cl.lookup_company("Jan Kowalski")
    assert not info.found
    assert info.source is None


def test_lookup_company_krs_signal_skips_ceidg(monkeypatch):
    # spolka (sygnal "sp. z o.o.") nigdy nie odpytuje CEIDG (to domena KRS)
    called = []
    monkeypatch.setattr(cl, "_lookup_ceidg", lambda *a, **k: called.append(1))
    monkeypatch.setenv(cl.CEIDG_TOKEN_ENV_VAR, "fake-token")
    info = cl.lookup_company("Testowa Firma Sp. z o.o.")
    assert not info.found
    assert not called
