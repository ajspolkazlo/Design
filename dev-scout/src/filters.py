"""
Logika filtrowania rekordow RWDZ pod katem:
  1. gminy w promieniu 20-30 km od Warszawy
  2. typu zabudowy (szeregowce / bliznaiaki / wolnostojace / wielorodzinne)
     ORAZ odciecia "smieci" — instalacji, sieci, przylaczy itp. (exclude_keywords)
  3. rodzaju zamierzenia: tylko BUDOWA NOWEGO budynku (nie rozbiorka/rozbudowa/
     "wykonanie robot budowlanych innych", ktore lapaly wiekszosc instalacji)
  4. daty zlozenia wniosku (domyslnie od 2024)
  5. skali inwestycji (liczba budynkow wyciagana z tekstu opisu)
  6. sygnalu "to raczej firma/deweloper, nie osoba fizyczna budujaca dla siebie"
"""

from __future__ import annotations

import re
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


def building_type_matches(value: str, include_keywords: list[str], exclude_keywords: list[str] | None = None) -> bool:
    """Rekord pasuje, gdy opis zawiera ktores ze slow include ORAZ nie zawiera
    zadnego ze slow exclude. Exclude wygrywa — "budowa instalacji gazowej ... w
    zabudowie szeregowej" ma include ('w zabudowie szeregowej') i exclude
    ('instalacj'), wiec ODPADA."""
    v = _norm(value)
    if not any(_norm(k) in v for k in include_keywords):
        return False
    if exclude_keywords and any(_norm(k) in v for k in exclude_keywords):
        return False
    return True


def is_new_construction(rodzaj_zamierzenia: object, hint: str) -> bool:
    """True gdy rodzaj zamierzenia to budowa NOWEGO obiektu. Brak wartosci ->
    False (nie zgadujemy — jesli rejestr nie mowi, ze to nowa budowa, nie
    wpuszczamy). hint domyslnie 'budowa nowego'."""
    v = _norm(rodzaj_zamierzenia)
    if not v:
        return False
    return _norm(hint) in v


# Liczebniki -> liczba (dla "budowa dwoch budynkow ...")
_COUNT_WORDS = {
    "dwa": 2, "dwoch": 2, "dwa budynki": 2,
    "trzy": 3, "trzech": 3,
    "cztery": 4, "czterech": 4,
    "piec": 5, "pieciu": 5,
    "szesc": 6, "szesciu": 6,
    "siedem": 7, "siedmiu": 7,
    "osiem": 8, "osmiu": 8,
    "dziewiec": 9, "dziewieciu": 9,
    "dziesiec": 10, "dziesieciu": 10,
}


def extract_building_count(opis: object) -> int | None:
    """Wyciaga liczbe budynkow z tekstu opisu inwestycji. Realny eksport RWDZ nie
    ma osobnej kolumny z liczba budynkow, wiec to jedyne zrodlo tego sygnalu.
    Zwraca None gdy nie da sie ustalic (wtedy filtr skali nie odrzuca)."""
    v = _norm(opis)
    if not v:
        return None

    # 1) cyfra bezposrednio przed "budynk" ("budowa 4 budynkow ...")
    m = re.search(r"(\d{1,3})\s*budynk", v)
    if m:
        n = int(m.group(1))
        # 4-cyfrowe liczby to zwykle rok/numer dzialki, nie liczba budynkow —
        # tu i tak ograniczamy do 1-3 cyfr, ale sanity-check na absurdy
        return n if 1 <= n <= 300 else None

    # 2) liczebnik slowny w poblizu "budynk" ("budowa dwoch budynkow ...")
    for word, n in _COUNT_WORDS.items():
        if re.search(rf"\b{word}\b.{{0,25}}budynk", v):
            return n

    # 3) "zespol budynkow" bez konkretnej liczby -> zaklada wielobudynkowa (>=3)
    if "zespol" in v and "budynk" in v:
        return 3

    # 4) pojedynczy budynek wprost ("budowa budynku mieszkalnego ...")
    if "budynku" in v or "budynek" in v:
        return 1

    return None


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
    niz zgubic leada). Odcinamy tylko gdy liczba jest znana i poza zakresem —
    w praktyce glownie gorny limit (duzi gracze)."""
    if liczba_budynkow is None or (isinstance(liczba_budynkow, float) and pd.isna(liczba_budynkow)):
        return True
    try:
        # int(float(...)) — NIE int(str(...)): gdy kolumna liczb ma braki, pandas
        # rzutuje ja na float, wiec do funkcji trafia np. 140.0 / "140.0", a
        # int("140.0") rzuca ValueError. Wczesniej ten wyjatek byl lapany i
        # zwracal True (nie odrzucaj) -> filtr skali NIGDY nie dzialal.
        n = int(float(liczba_budynkow))
    except (ValueError, TypeError):
        return True
    return min_budynkow <= n <= max_budynkow


def apply_filters(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Zaklada, ze df ma kolumny norm_gmina, norm_kategoria_obiektu,
    norm_rodzaj_zamierzenia, norm_data, norm_inwestor (patrz
    rwdz_parse.normalize_dataframe). Brakujace kolumny sa traktowane jako
    'nie odrzucaj po tym kryterium', zeby jeden brakujacy sygnal nie wywalil
    calego pipeline'u — ale zostanie to zalogowane wyzej."""

    region = config["region"]
    building = config["building_types"]
    investor_cfg = config["investor_filter"]
    known_large = config.get("known_large_developers", [])
    scale_cfg = config.get("scale_filter", {"min_budynkow": 1, "max_budynkow": 10_000})
    date_cfg = config.get("date_filter", {})
    exclude_keywords = building.get("exclude_keywords", [])

    mask = pd.Series(True, index=df.index)

    if "norm_gmina" in df.columns:
        mask &= df["norm_gmina"].apply(
            lambda v: gmina_matches(v, region["gminy"], region.get("wyklucz", []))
        )

    # typ zabudowy: include ORAZ nie-exclude (odcina instalacje/sieci/przylacza)
    if "norm_kategoria_obiektu" in df.columns:
        mask &= df["norm_kategoria_obiektu"].apply(
            lambda v: building_type_matches(v, building["include_keywords"], exclude_keywords)
        )

    # rodzaj zamierzenia: tylko budowa nowego obiektu (odcina rozbiorki/rozbudowy/
    # "wykonanie robot budowlanych innych" = wiekszosc instalacji)
    if building.get("require_new_construction") and "norm_rodzaj_zamierzenia" in df.columns:
        hint = building.get("new_construction_hint", "budowa nowego")
        mask &= df["norm_rodzaj_zamierzenia"].apply(lambda v: is_new_construction(v, hint))

    # data zlozenia wniosku (domyslnie od 2024)
    min_data = date_cfg.get("min_data")
    if min_data and "norm_data" in df.columns:
        parsed_dates = pd.to_datetime(df["norm_data"], errors="coerce")
        mask &= parsed_dates >= pd.Timestamp(min_data)

    if "norm_inwestor" in df.columns and known_large:
        mask &= ~df["norm_inwestor"].apply(
            lambda v: is_known_large_developer(v, known_large)
        )

    # liczba budynkow wyciagana z opisu -> filtr skali (glownie gorny limit)
    if "norm_kategoria_obiektu" in df.columns:
        counts = df["norm_kategoria_obiektu"].apply(extract_building_count)
        mask &= counts.apply(
            lambda n: within_scale(n, scale_cfg["min_budynkow"], scale_cfg["max_budynkow"])
        )

    result = df[mask].copy()

    # zapisz wyciagnieta liczbe budynkow, zeby scoring i eksport mialy do niej dostep
    if "norm_kategoria_obiektu" in result.columns:
        result["norm_liczba_budynkow"] = result["norm_kategoria_obiektu"].apply(extract_building_count)

    if "norm_inwestor" in result.columns:
        result["is_likely_company"] = result["norm_inwestor"].apply(
            lambda v: looks_like_company(v, investor_cfg["company_signals"])
        )
    else:
        result["is_likely_company"] = None

    return result
