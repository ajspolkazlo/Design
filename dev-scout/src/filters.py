"""
Logika filtrowania rekordow RWDZ pod katem:
  1. gminy w promieniu 20-30 km od Warszawy
  2. typu zabudowy (szeregowce / bliznaiaki / wielorodzinne)
  3. sygnalu "to raczej firma/deweloper, nie osoba fizyczna budujaca dla siebie"
"""

from __future__ import annotations

import unicodedata

import pandas as pd


def _norm(text: object) -> str:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return ""
    # "ł"/"Ł" nie rozklada sie przez NFKD (patrz rwdz_parse._strip_diacritics) —
    # bez tego np. "Łomianki"/"Wołomin"/"Michałowice" z realnych danych nigdy
    # nie dopasuja sie do ASCII nazw gmin w config.yaml.
    text = str(text).replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


def gmina_matches(value: str, gminy: list[str], wyklucz: list[str]) -> bool:
    v = _norm(value)
    if any(_norm(w) == v or _norm(w) in v for w in wyklucz):
        return False
    return any(_norm(g) in v for g in gminy)


def building_type_matches(value: str, keywords: list[str]) -> bool:
    v = _norm(value)
    return any(_norm(k) in v for k in keywords)


def looks_like_company(investor_name: str, company_signals: list[str]) -> bool:
    v = _norm(investor_name)
    if not v:
        return False
    return any(_norm(sig) in v for sig in company_signals)


def is_known_large_developer(investor_name: str, known_large: list[str]) -> bool:
    """Odrzuca oczywistosci — znanych, duzych deweloperow z pelnym budzetem
    marketingowym, ktorych i tak nie warto sledzic tym narzedziem."""
    v = _norm(investor_name)
    if not v:
        return False
    return any(_norm(name) in v for name in known_large)


def within_scale(liczba_budynkow: object, min_budynkow: int, max_budynkow: int) -> bool:
    """Brak informacji o liczbie budynkow -> nie odrzucaj (lepiej przepuscic
    niz zgubic leada z powodu brakujacej kolumny)."""
    try:
        n = int(str(liczba_budynkow).strip())
    except (ValueError, TypeError):
        return True
    return min_budynkow <= n <= max_budynkow


def apply_filters(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Zaklada, ze df ma kolumny norm_gmina, norm_kategoria_obiektu, norm_inwestor
    (patrz rwdz_parse.normalize_dataframe). Brakujace kolumny sa traktowane
    jako 'nie odrzucaj po tym kryterium', zeby jeden brakujacy sygnal
    nie wywalil calego pipeline'u — ale zostanie to zalogowane wyzej."""

    region = config["region"]
    building = config["building_types"]
    investor_cfg = config["investor_filter"]
    known_large = config.get("known_large_developers", [])
    scale_cfg = config.get("scale_filter", {"min_budynkow": 1, "max_budynkow": 10_000})

    mask = pd.Series(True, index=df.index)

    if "norm_gmina" in df.columns:
        mask &= df["norm_gmina"].apply(
            lambda v: gmina_matches(v, region["gminy"], region.get("wyklucz", []))
        )

    if "norm_kategoria_obiektu" in df.columns:
        mask &= df["norm_kategoria_obiektu"].apply(
            lambda v: building_type_matches(v, building["include_keywords"])
        )

    if "norm_inwestor" in df.columns and known_large:
        mask &= ~df["norm_inwestor"].apply(
            lambda v: is_known_large_developer(v, known_large)
        )

    if "norm_liczba_budynkow" in df.columns:
        mask &= df["norm_liczba_budynkow"].apply(
            lambda v: within_scale(v, scale_cfg["min_budynkow"], scale_cfg["max_budynkow"])
        )

    result = df[mask].copy()

    if "norm_inwestor" in result.columns:
        result["is_likely_company"] = result["norm_inwestor"].apply(
            lambda v: looks_like_company(v, investor_cfg["company_signals"])
        )
    else:
        result["is_likely_company"] = None

    return result
