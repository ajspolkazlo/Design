"""
Testy regresyjne dla src/filters.py i src/rwdz_parse.py — bez sieci, na
zamockowanych/syntetycznych danych. Uzupelniaja (nie zastepuja) `data/raw/
sample_test.csv`, ktory testuje CALY pipeline `run --skip-fetch` na realnym
formacie pliku (patrz docs/AUDYT.md, sekcja 7: brak testow byl realna luka —
ten plik i ta fikstura razem sa pierwszym krokiem do jej domkniecia).

Uruchomienie: python -m pytest tests/ -v
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src import filters, rwdz_parse


def test_gmina_matches_basic():
    assert filters.gmina_matches("Piaseczno", ["Piaseczno"], [])
    assert not filters.gmina_matches("Warszawa", ["Piaseczno"], [])


def test_gmina_matches_excludes_warszawa():
    # zweryfikowane na zywo: Warszawa musi byc odrzucona mimo ze niektore gminy
    # docelowe (np. "Marki") technicznie mogloby czesciowo pasowac tekstowo
    assert not filters.gmina_matches("Warszawa", ["Piaseczno", "Marki"], ["Warszawa"])


def test_gmina_matches_diacritics():
    # "ł" nie rozklada sie przez NFKD (patrz komentarz w filters._norm) —
    # bez jawnej podmiany "Łomianki" nigdy nie dopasuje sie do "Lomianki" w configu
    assert filters.gmina_matches("Łomianki", ["Lomianki"], [])
    assert filters.gmina_matches("Michałowice", ["Michalowice"], [])


def test_building_type_include_and_exclude():
    assert filters.building_type_matches(
        "budowa budynku w zabudowie szeregowej", ["w zabudowie szeregowej"], ["instalacj"]
    )
    # exclude wygrywa nad include — "kwiatek" z realnych danych (instalacja
    # opisana jako budynek w zabudowie szeregowej)
    assert not filters.building_type_matches(
        "budowa instalacji gazowej dla budynkow w zabudowie szeregowej",
        ["w zabudowie szeregowej"], ["instalacj"],
    )


def test_is_new_construction_requires_hint():
    assert filters.is_new_construction("Budowa nowego obiektu budowlanego", "budowa nowego")
    assert not filters.is_new_construction("Rozbiórka obiektu budowlanego", "budowa nowego")
    assert not filters.is_new_construction(None, "budowa nowego")


def test_extract_building_count_digit():
    assert filters.extract_building_count("budowa 4 budynków mieszkalnych") == 4


def test_extract_building_count_word():
    assert filters.extract_building_count("budowa dwóch budynków mieszkalnych") == 2


def test_extract_building_count_zespol_bez_liczby():
    assert filters.extract_building_count("zespół budynków mieszkalnych jednorodzinnych") == 3


def test_extract_building_count_single():
    assert filters.extract_building_count("budowa budynku mieszkalnego jednorodzinnego") == 1


def test_extract_building_count_unknown_returns_none():
    assert filters.extract_building_count("coś zupełnie innego") is None


def test_within_scale_handles_float_string():
    # regresja: int(str(140.0)) rzuca ValueError, wczesniej lapane i traktowane
    # jako "nie odrzucaj" — filtr skali byl calkowicie martwy (patrz historia commitow)
    assert not filters.within_scale("140.0", min_budynkow=1, max_budynkow=40)
    assert filters.within_scale("4.0", min_budynkow=1, max_budynkow=40)


def test_within_scale_none_does_not_reject():
    assert filters.within_scale(None, min_budynkow=1, max_budynkow=40)


def test_looks_like_company():
    assert filters.looks_like_company("Nowak Budownictwo Sp. z o.o.", ["sp. z o.o.", "budownictwo"])
    assert not filters.looks_like_company("Jan Kowalski", ["sp. z o.o.", "budownictwo"])


def test_is_known_large_developer():
    assert filters.is_known_large_developer("Atal S.A.", ["Atal", "Murapol"])
    assert not filters.is_known_large_developer("Mala Firma Sp. z o.o.", ["Atal", "Murapol"])


def test_compose_street_name_with_ulica_dalej():
    # zweryfikowane na 30 realnych przykladach z wynik_mazowieckie.csv —
    # ulica_dalej (imie) POPRZEDZA ulica (nazwisko) w naturalnym zapisie
    assert rwdz_parse.compose_street_name("Piłsudskiego", "Józefa ") == "Józefa Piłsudskiego"
    assert rwdz_parse.compose_street_name("Sloneczna", None) == "Sloneczna"
    assert rwdz_parse.compose_street_name(None, None) is None


def test_clean_house_number_filters_junk():
    assert rwdz_parse.clean_house_number("12") == "12"
    assert rwdz_parse.clean_house_number(".") is None
    assert rwdz_parse.clean_house_number("") is None
    assert rwdz_parse.clean_house_number(None) is None


def test_sample_fixture_end_to_end():
    """Kanarek regresji na PELNYM pliku (parse+normalize+filter), nie tylko
    pojedynczych funkcjach — patrz docs/AUDYT.md o wczesniej zlamanej fikundze
    sample_test.csv (separator '#' vs produkcyjny ';')."""
    import yaml

    root = Path(__file__).parent.parent
    cfg = yaml.safe_load(open(root / "config.yaml", encoding="utf-8"))
    csv_path = root / "data" / "raw" / "sample_test.csv"

    raw_df = rwdz_parse.load_raw(
        csv_path, separator=cfg["rwdz"]["column_separator"], encoding=cfg["rwdz"]["encoding"]
    )
    normalized_df = rwdz_parse.normalize_dataframe(raw_df)
    filtered_df = filters.apply_filters(normalized_df, cfg)

    assert len(raw_df) == 9, "fikstura powinna miec 9 wierszy wejsciowych"
    assert len(filtered_df) == 4, "dokladnie 4 z 9 powinny przejsc filtry"
    assert set(filtered_df["norm_miejscowosc"]) == {"Piaseczno", "Michalowice", "Lomianki", "Legionowo"}


# ------------------- Zadanie 0: dom jednorodzinny os. prywatnej -------------------
# Cztery dokladne przyklady zgloszone przez Adama (22.07.2026) jako smieci
# zaslaniajace wynik — MUSZA byc odrzucone. Dwa z nich maja realne literowki
# z danych zrodlowych RWDZ ("MIESZKANY" zamiast "MIESZKALNY", "SACZELNE"
# zamiast "SZCZELNE"), celowo zostawione w tescie zeby pilnowac fuzzy matchingu.

_PRIVATE_HOME_EXAMPLES = [
    "budowa budynku mieszkalnego jednorodzinnego wolnostojącego wraz z urządzeniami budowlanymi",
    "BUDYNEK MIESZKANY JEDNORODZINNY WOLNOSTOJACY ORAZ SZAMABO SACZELNE O POJ. 10 M3",
    "budowa budynku mieszkalnego jednorodzinnego wolnostojącego oraz szamba szczelnego o poj. 10 m3",
    "Budowa budynku mieszkalnego jednorodzinnego wolnostojącego z garażem",
]

_DEVELOPER_MULTI_BUILDING_EXAMPLES = [
    "trzy budynki mieszkalne jednorodzinne w zabudowie szeregowej",
    "budowa dwóch budynków mieszkalnych jednorodzinnych w zabudowie bliźniaczej",
    "zespół budynków mieszkalnych jednorodzinnych",
    "zespół 4 budynków wolnostojących",
]


def test_private_single_family_home_rejected():
    for text in _PRIVATE_HOME_EXAMPLES:
        lb = filters.extract_building_count(text)
        assert lb == 1, f"oczekiwano liczba_budynkow=1 dla: {text!r} (dostano {lb})"
        assert filters.is_private_single_family_home(text, lb), f"powinno byc odrzucone: {text!r}"


def test_developer_multi_building_not_rejected():
    for text in _DEVELOPER_MULTI_BUILDING_EXAMPLES:
        lb = filters.extract_building_count(text)
        assert not filters.is_private_single_family_home(text, lb), \
            f"NIE powinno byc odrzucone (to profil dewelopera): {text!r} (liczba_budynkow={lb})"


def test_is_private_single_family_home_requires_exact_count_one():
    # liczba_budynkow nieznana (None) -> nie zgadujemy, nie odrzucamy
    assert not filters.is_private_single_family_home("budynek wolnostojący", None)
    # liczba_budynkow > 1 -> nie odrzucamy nawet z "wolnostojący" w tekscie
    assert not filters.is_private_single_family_home("wolnostojący", 2)


def test_has_wolnostojacy_fuzzy_typo():
    # literowka W SAMYM rdzeniu slowa (nie tylko w sasiednich wyrazach) —
    # dystans edycyjny <=2 od "wolnostoj"
    assert filters._has_wolnostojacy("budynek wolnostjacy jednorodzinny")
    assert not filters._has_wolnostojacy("budynek w zabudowie szeregowej")
