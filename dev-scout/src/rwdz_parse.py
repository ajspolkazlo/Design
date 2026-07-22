"""
Parsuje plik CSV z RWDZ do pandas.DataFrame ze znormalizowanymi nazwami kolumn.

Separator to '#' (potwierdzone na stronie GUNB), kodowanie UTF-8. Dokladnych
nazw kolumn nie udalo sie zweryfikowac na zywym pliku (brak dostepu do sieci
w srodowisku, w ktorym powstal ten kod) — zamiast zakladac konkretne nazwy,
kod szuka kolumn po dopasowaniu fragmentow nazw (case-insensitive, bez
polskich znakow). To sprawia, ze parser dziala nawet jesli dokladna nazwa
kolumny w realnym pliku odrobine sie rozni.

Claude Code: po pierwszym realnym imporcie, wypisz `df.columns.tolist()`
i doprecyzuj COLUMN_HINTS ponizej, jesli auto-detekcja czegos nie znajdzie
(zobacz `unresolved_columns()`).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Dla kazdego logicznego pola: lista fragmentow, ktore szukamy w nazwie kolumny
# (dopasowanie "zawiera", w kolejnosci priorytetu).
#
# Zweryfikowane na realnym pliku wynik_mazowieckie.csv — realne naglowki uzywaja
# podkreslen (np. "data_wplywu_wniosku"), nie spacji jak pierwotnie zakladano
# (patrz _normalize nizej), i nie ma osobnych kolumn gmina/powiat/liczba_budynkow/
# liczba_lokali — jest tylko "miasto" (uzywane tu jako proxy dla gminy) i "terc"
# (kod TERYT, nieuzywany na razie). "kategoria_obiektu" mapuje na kolumne
# nazwa_zam_budowlanego (wolny tekst opisu inwestycji) — kolumna "kategoria"
# to numer rzymski kategorii z prawa budowlanego (I-XXX), za malo ziarnisty,
# a "rodzaj_inwestycji" ma tylko 2 wartosci (jednorodzinny / inny).
COLUMN_HINTS: dict[str, list[str]] = {
    "id_sprawy": ["numer gunb", "numer urzad", "identyfikator", "nr sprawy", "numer sprawy", "sygnatura"],
    "data": ["data wplywu", "data zlozenia", "data wydania", "data"],
    "rodzaj_dokumentu": ["rodzaj dokumentu", "typ dokumentu", "kategoria dokumentu"],
    # rodzaj zamierzenia (intencja): "budowa nowego/nowych obiektow budowlanych" vs
    # rozbiorka/rozbudowa/nadbudowa/"wykonanie robot budowlanych innych" — uzywane
    # przez filters.py do odciecia wszystkiego co nie jest budowa nowego budynku
    "rodzaj_zamierzenia": ["zamierzenia bud", "rodzaj zamierzenia"],
    "kategoria_obiektu": ["zam budowlanego", "kategoria obiektu", "rodzaj obiektu", "nazwa obiektu", "opis obiektu"],
    "wojewodztwo": ["wojewodztwo"],
    "powiat": ["powiat"],
    "gmina": ["gmina", "miasto"],
    "miejscowosc": ["miejscowosc", "miasto"],
    "ulica": ["ulica"],
    # RWDZ dzieli nazwe ulicy na dwie kolumny: "ulica" = czlon glowny (zwykle
    # nazwisko/rzeczownik, uzywany do alfabetycznego sortowania w rejestrze),
    # "ulica_dalej" = czlon dodatkowy (imie/tytul), ktory POPRZEDZA czlon
    # glowny w naturalnym zapisie. Zweryfikowane na 30 realnych przykladach:
    # ulica="Piłsudskiego", ulica_dalej="Józefa " -> pelna nazwa "Józefa
    # Piłsudskiego"; ulica="Abrahama", ulica_dalej="gen. Romana " -> "gen.
    # Romana Abrahama". Bez tego skladania nazwa ulicy jest ucieta/mylaca.
    "ulica_ciag_dalszy": ["ulica dalej", "ulica c d", "ciag dalszy ulicy"],
    "numer_domu": ["nr domu", "numer domu", "numer nieruchomosci"],
    "inwestor": ["inwestor", "nazwa wnioskodawcy", "wnioskodawca"],
    "organ": ["organ", "urzad"],
    "liczba_budynkow": ["liczba budynkow", "ilosc budynkow"],
    "liczba_lokali": ["liczba lokali", "liczba mieszkan"],
}

# Wartosci-smieci w numer_domu, ktore realnie oznaczaja "brak numeru" (np.
# pojedyncza kropka jako placeholder w niektorych wnioskach) — zweryfikowane
# na zywo w wynik_mazowieckie.csv.
_JUNK_HOUSE_NUMBERS = {"", ".", "-", "brak", "b/n", "bn"}


def compose_street_name(ulica: object, ulica_dalej: object) -> str | None:
    """Sklada pelna nazwe ulicy z dwoch kolumn RWDZ (patrz COLUMN_HINTS
    powyzej). Kolejnosc: ulica_dalej (imie/tytul) + ulica (nazwisko/rdzen) —
    to naturalny szyk polskich nazw ulic. Gdy ulica_dalej brak, zwraca sama
    ulice bez zmian (wiekszosc ulic nie ma tego rozbicia w ogole)."""
    main = str(ulica).strip() if ulica is not None and pd.notna(ulica) else ""
    if not main:
        return None
    extra = str(ulica_dalej).strip() if ulica_dalej is not None and pd.notna(ulica_dalej) else ""
    return f"{extra} {main}".strip() if extra else main


def clean_house_number(numer_domu: object) -> str | None:
    if numer_domu is None or (isinstance(numer_domu, float) and pd.isna(numer_domu)):
        return None
    v = str(numer_domu).strip()
    return v if v and v.lower() not in _JUNK_HOUSE_NUMBERS else None


def _strip_diacritics(text: str) -> str:
    # NFKD nie rozkłada "ł"/"Ł" (to nie jest litera+znak diakrytyczny w Unicode,
    # tylko odrebny, samodzielny znak) — bez jawnej podmiany nazwy typu
    # "Łomianki"/"Wołomin"/"Michałowice" nigdy nie dopasuja sie do configu.
    text = text.replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    # podkreslenia -> spacje, zeby COLUMN_HINTS pisane ze spacjami ("data wplywu")
    # dopasowywaly sie do realnych naglowkow ze znakami podkreslenia
    # ("data_wplywu_wniosku").
    return _strip_diacritics(str(text)).lower().replace("_", " ").strip()


def load_raw(csv_path: Path, separator: str = ";", encoding: str = "utf-8-sig") -> pd.DataFrame:
    df = pd.read_csv(
        csv_path,
        sep=separator,
        encoding=encoding,
        dtype=str,
        engine="python",
        on_bad_lines="warn",
    )
    df.columns = [str(c) for c in df.columns]
    return df


def build_column_map(columns: list[str]) -> dict[str, str]:
    """Zwraca mapowanie logiczne_pole -> rzeczywista_nazwa_kolumny (jesli znaleziona)."""
    normalized_cols = {c: _normalize(c) for c in columns}
    mapping: dict[str, str] = {}
    for field, hints in COLUMN_HINTS.items():
        for hint in hints:
            hint_norm = _normalize(hint)
            match = next((orig for orig, norm in normalized_cols.items() if hint_norm in norm), None)
            if match:
                mapping[field] = match
                break
    return mapping


def unresolved_columns(columns: list[str]) -> list[str]:
    mapping = build_column_map(columns)
    return [field for field in COLUMN_HINTS if field not in mapping]


def normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Zwraca DataFrame z dodatkowymi znormalizowanymi kolumnami (prefiks norm_)
    dla wykrytych pol logicznych, nie ruszajac oryginalnych kolumn."""
    mapping = build_column_map(df.columns.tolist())
    missing = unresolved_columns(df.columns.tolist())
    if missing:
        log.warning(
            "Nie rozpoznano %d pol logicznych: %s. Sprawdz COLUMN_HINTS w rwdz_parse.py "
            "wzgledem realnych naglowkow: %s",
            len(missing), missing, df.columns.tolist(),
        )

    out = df.copy()
    for field, col in mapping.items():
        out[f"norm_{field}"] = out[col]

    # norm_ulica nadpisujemy pelnym skladem (ulica_dalej + ulica) zamiast
    # samego czlonu glownego — patrz compose_street_name() i komentarz przy
    # COLUMN_HINTS["ulica_ciag_dalszy"] powyzej.
    if "ulica" in mapping:
        ulica_dalej_col = mapping.get("ulica_ciag_dalszy")
        out["norm_ulica"] = out.apply(
            lambda r: compose_street_name(
                r[mapping["ulica"]], r[ulica_dalej_col] if ulica_dalej_col else None
            ),
            axis=1,
        )
    if "numer_domu" in mapping:
        out["norm_numer_domu"] = out[mapping["numer_domu"]].apply(clean_house_number)
    else:
        out["norm_numer_domu"] = None

    return out


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Uzycie: python rwdz_parse.py sciezka_do_pliku.csv")
        sys.exit(1)

    import yaml

    cfg = yaml.safe_load(open(Path(__file__).parent.parent / "config.yaml", encoding="utf-8"))
    df = load_raw(
        Path(sys.argv[1]),
        separator=cfg["rwdz"]["column_separator"],
        encoding=cfg["rwdz"]["encoding"],
    )
    print(f"Wczytano {len(df)} wierszy, {len(df.columns)} kolumn.")
    print("Kolumny:", df.columns.tolist())
    print("Nierozpoznane pola logiczne:", unresolved_columns(df.columns.tolist()))
