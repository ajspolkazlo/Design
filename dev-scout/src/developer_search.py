"""
Wyszukiwanie strony internetowej dewelopera/inwestora dla leadow ze
zidentyfikowana nazwa inwestora (Zadanie 3, lipiec 2026).

Cel: NIE lista kandydatow, JEDEN najlepiej oceniony wynik per lead, z jasnym
statusem pewnosci — nigdy nie udawac pewnosci, ktorej nie ma (stad 4-stopniowa
skala statusu zamiast prostego znaleziono/nie).

============================= PRZEPLYW =============================
0. Pomin calkowicie, gdy inwestor wyglada na OSOBE FIZYCZNA (brak sygnalow
   spolki w nazwie — te same sygnaly co filters.looks_like_company) — zbyt
   wysokie ryzyko falszywego trafienia (samo imie+nazwisko to za malo, zeby
   bezpiecznie znalezc "tej" osoby strone w internecie).
1. OPCJA C, NAJSILNIEJSZY darmowy sygnal, gdy dostepny: ODWROCENIE z
   POTWIERDZONEGO ogloszenia na portalu (reverse_from_portal_match) — gdy
   verify.py juz potwierdzil (CONFIRMED/LIKELY, geometria+metraz+czas), ze
   konkretne ogloszenie na RynekPierwotny odpowiada TEJ inwestycji z RWDZ,
   strona profilu dewelopera na RynekPierwotny ma wprost link "Odwiedz
   strone dewelopera" + NIP (zweryfikowane na zywo: kazda oferta ma
   breadcrumb do /deweloperzy/{slug}/, ten profil ma jawny link zewnetrzny +
   NIP w polu JSON). Wymaga dzialajacego dopasowania portalu (Brave/browser
   backend) — w sesjach bez takiego backendu portal RynekPierwotny nigdy nie
   jest sprawdzany, wiec ta sciezka nie odpali (udokumentowane ograniczenie).
2. DARMOWY sygnal, zero klucza API: zgadywanie domeny wprost z nazwy
   inwestora (guess_developer_domain). Generuje kandydatow z ZACHOWANIEM
   KOLEJNOSCI tokenow, w tym z porzuceniem slow-wypelniaczy ("DOM GRANDE
   DEVELOPER" -> grandedeveloper.pl, porzucone "dom"), pobiera strone i
   potwierdza jedna z trzech sciezek: (a) NIP inwestora w tresci, (b) KRS/NIP
   ZE STOPKI strony -> oficjalne API KRS -> porownanie marki z inwestorem
   RWDZ (mostkuje 'marka != zarejestrowana nazwa'), (c) pelna nazwa w tresci
   + sygnal polskiej firmy. Polskie male firmy bardzo czesto rejestruja
   domene = nazwa firmy, wiec to zaskakujaco skuteczny, zupelnie darmowy
   pierwszy strzal.
3. DARMOWE warstwy ODKRYWANIA domen, gdy zgadywanie nie trafilo (opcje A/B,
   bez klucza): (B) crt.sh — publiczne logi Certificate Transparency, zwraca
   realne domeny z fragmentem marki; (A) DuckDuckGo HTML — darmowa
   wyszukiwarka rankujaca po trafnosci. Kazdy zwrocony kandydat przechodzi
   DOKLADNIE te sama walidacje co zgadywanie domeny (_probe_and_classify z
   wymogiem tokenu marki w domenie) — luzniejsze zrodlo NIE luzuje kontroli
   falszywych pozytywow. DDG blokuje po 1-2 zapytaniach -> wylacza sie na
   resztę przebiegu.
4. PODSTAWOWY sygnal wymagajacy klucza: Google Places API (New) Text Search
   (lookup_website_via_places) — niepuste websiteUri -> "potwierdzona" BEZ
   dodatkowej walidacji (Google juz zweryfikowal firma<->strona przez Google
   Moja Firma). Brak klucza / brak wyniku -> spada do kroku 5.
5. Fallback koncowy: dla spolek do 3 wariantow zapytania do Brave Search
   (klucz), PRZERYWA na pierwszym wyniku przechodzacym filtry (budzet).
6. Odrzuca domeny portali nieruchomosci (ta sama lista co portal_check.py) i
   krotka blocklist agregatorow/mediow z config.yaml. Facebook/LinkedIn/
   Instagram to fallback drugiej kategorii — nigdy glowny wynik.
7. Ranking (tylko sciezka Brave — kroki 1-3 nie potrzebuja rankingu): nazwa
   domeny zawiera fragment marki inwestora (fuzzy) = najwyzszy priorytet;
   nazwa inwestora w tytule/opisie wyniku = sredni.
8. Walidacja: krok 1 (portal) wymaga zgodnosci marki/NIP z profilem
   dewelopera; krok 2 wymaga pelnej nazwy/NIP w tresci strony; krok 3
   (Places) ufa Google bez dodatkowej walidacji; krok 4 (Brave) szuka
   NIP/KRS (jesli znany) w tresci kandydata. Wynik: "potwierdzona" (krok
   1/2/3 z sukcesem NIP, ALBO krok 4 + NIP/KRS sie zgadza) / "prawdopodobna"
   (krok 1/2 bez NIP, krok 4 sama nazwa domeny) / "kandydat_niepewny" (krok
   4, trafiono cos, walidacja sie nie powiodla, LUB kandydat to Facebook/
   LinkedIn/Instagram) / "brak_do_wyszukania_osoba_fizyczna" (krok 0) /
   "nie_znaleziono".
8. Cache trwaly (SQLite) — osobne tabele dla Places (po nazwa+miejscowosc) i
   dla wyniku koncowego (po znormalizowanej nazwie, obejmuje tez kroki 2 i
   4). Wynik pozytywny bez wygasania, "nie znaleziono" z TTL 30 dni (nazwa
   moze pozniej dostac strone).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import yaml

from src import company_lookup  # oficjalne API KRS (lookup_krs_by_number) — brak cyklu importow

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CACHE_DB_PATH = ROOT / "data" / "developer_search_cache.sqlite3"

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY_ENV_VAR = "BRAVE_SEARCH_API_KEY"  # ta sama zmienna co portal_check.py
NOT_FOUND_TTL_DAYS = 30  # wynik "nie znaleziono" wygasa; "znaleziono" nie (patrz docstring modulu)

# Google Places API (New) — Text Search, sygnal PODSTAWOWY (patrz docstring
# modulu, krok 2), sprawdzany przed Brave Search. Klucz opcjonalny — bez
# niego ten krok jest po prostu pomijany (pipeline dziala dalej na fallbacku
# Brave), zgodnie z zasada "nigdy nie wymagaj logowania/klucza, zeby dzialac".
PLACES_SEARCH_TEXT_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_API_KEY_ENV_VAR = "GOOGLE_PLACES_API_KEY"
PLACES_FIELD_MASK = "places.id,places.displayName,places.websiteUri,places.formattedAddress"

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Portale nieruchomosci (ta sama lista co portal_check._PORTAL_DOMAINS) — te
# NIGDY nie sa strona dewelopera, tylko miejscem, gdzie deweloper reklamuje.
_PORTAL_DOMAINS = {"otodom.pl", "olx.pl", "rynekpierwotny.pl", "morizon.pl", "gratka.pl", "domiporta.pl"}

# Ogolne agregatory/media/rejestry — wynik z tych domen nigdy nie jest samą
# stroną dewelopera, tylko wzmianka o nim. Krotka, bo celem jest usunac
# oczywiste smieci, nie zbudowac wyczerpujaca liste.
_GENERIC_BLOCKLIST = {
    "wikipedia.org", "wikidata.org", "gpw.pl", "money.pl", "gazeta.pl",
    "onet.pl", "wp.pl", "interia.pl", "biznes.gov.pl", "rp.pl", "forbes.pl",
    "krs-online.com.pl", "aleo.com", "rejestr.io", "panoramafirm.pl",
    "pkt.pl", "biznesfirmy.pl", "google.com", "bing.com", "youtube.com",
}

# Fallback DRUGIEJ KATEGORII — nigdy glowny, potwierdzony wynik (patrz
# docstring modulu, krok 3).
_SOCIAL_FALLBACK_DOMAINS = {"facebook.com", "linkedin.com", "instagram.com"}

STATUS_CONFIRMED = "potwierdzona"
STATUS_LIKELY = "prawdopodobna"
STATUS_UNCERTAIN = "kandydat_niepewny"
STATUS_INDIVIDUAL = "brak_do_wyszukania_osoba_fizyczna"
STATUS_NOT_FOUND = "nie_znaleziono"


@dataclass
class DeveloperSite:
    investor: str
    url: str | None = None
    status: str = STATUS_NOT_FOUND
    matched_on: str | None = None  # np. "NIP w tresci strony" / "nazwa domeny" — do debugowania


def _norm(text: str) -> str:
    text = (text or "").replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


_LEGAL_FORM_RE = re.compile(
    r"\bsp\.?\s*z\s*o\.?\s*o\.?\b|\bspolka\s+z\s+ograniczona\s+odpowiedzialnoscia\b"
    r"|\bs\.?a\.?\b|\bsp\.?\s*k\.?\b|\bspolka\s+komandytowa\b|\bspolka\s+jawna\b|\bs\.?c\.?\b",
    re.IGNORECASE,
)


def core_name(investor: str) -> str:
    """Nazwa bez formy prawnej — sama marka do budowania zapytan/porownan
    domeny (ten sam wzorzec co portal_check.investor_core_name, powielony
    tutaj celowo — inny cel uzycia, nie warto sprzegac modulow dla jednej
    funkcji)."""
    v = _norm(investor)
    v = _LEGAL_FORM_RE.sub(" ", v)
    v = re.sub(r"[.,\"'()]", " ", v)
    return " ".join(t for t in v.split() if len(t) > 1)


def _load_company_signals() -> list[str]:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return cfg.get("investor_filter", {}).get("company_signals", [])


def _norm_tight(text: str) -> str:
    """Jak _norm, plus usuniecie kropek/spacji — patrz identyczny komentarz i
    zweryfikowany na zywo bug w filters._norm_tight ('M4 Sp. z o. o.' z
    dodatkowa spacja BLEDNIE klasyfikowane jako osoba fizyczna bez tej
    poprawki)."""
    return re.sub(r"[.\s]", "", _norm(text))


def is_individual(investor: str) -> bool:
    """Brak sygnalow spolki w nazwie -> traktujemy jako osobe fizyczna (ten
    sam zestaw sygnalow co filters.looks_like_company, odwrocony) — zbyt
    ryzykowne szukanie strony po samym imieniu i nazwisku."""
    if not investor or not investor.strip():
        return True
    v = _norm_tight(investor)
    signals = _load_company_signals()
    return not any(_norm_tight(sig) in v for sig in signals)


def _domain_of(url: str) -> str:
    import urllib.parse
    host = urllib.parse.urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _is_blocked_domain(domain: str) -> bool:
    def _matches(d: str, s: set[str]) -> bool:
        return any(d == b or d.endswith("." + b) for b in s)
    return _matches(domain, _PORTAL_DOMAINS) or _matches(domain, _GENERIC_BLOCKLIST)


def _is_social_fallback(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in _SOCIAL_FALLBACK_DOMAINS)


def _query_variants(investor: str) -> list[str]:
    name = core_name(investor) or investor
    return [
        f'"{name}" deweloper',
        f'"{name}" inwestycja mieszkaniowa',
        f'"{name}" mieszkania na sprzedaż',
    ]


# Zgadywanie domeny wprost z nazwy (patrz docstring modulu, krok 2) — zero
# klucza API, TLD-y typowe dla polskich firm.
_DOMAIN_GUESS_TLDS = (".pl", ".com.pl", ".eu", ".com")
_MAX_DOMAIN_PROBES = 16  # gorna granica sond HTTP na inwestora (budzet czasu)
_MAX_DISCOVERY_CANDIDATES = 8  # ile domen-kandydatow z crt.sh / DuckDuckGo probowac

# Opcja B — Certificate Transparency (crt.sh): publiczne logi certyfikatow SSL,
# darmowe, bez klucza. Zwraca realne, istniejace domeny zawierajace zadany
# fragment marki (nawet nietypowe TLD/pisownie, ktorych zgadywanie nie trafi).
# Bywa przeciazone (HTTP 502) — przy bledzie po prostu pomijamy (graceful).
_CRTSH_URL = "https://crt.sh/"

# Opcja A — DuckDuckGo HTML (darmowa wyszukiwarka jako warstwa odkrywania):
# zwraca to, co znalazlby czlowiek szukajac (rankuje po trafnosci — na zywo
# grandedeveloper.pl bylo wynikiem #1). ALE blokuje po 1-2 zapytaniach
# (HTTP 202 "anomaly"), wiec: ostatni darmowy krok (po zgadywaniu i crt.sh),
# lagodny sleep miedzy zapytaniami, a po wykryciu blokady — wylaczamy sie na
# resztę przebiegu (wzorzec jak _browser_unavailable w portal_check).
_DDG_URL = "https://html.duckduckgo.com/html/"
_ddg_blocked = False  # ustawiane na True po wykryciu blokady (anomaly) — na czas procesu

# Slowa-WYPELNIACZE, ktore deweloperzy czesto POMIJAJA w domenie, mimo ze sa
# w zarejestrowanej nazwie. Zweryfikowane na zywo (24.07.2026): "DOM GRANDE
# DEVELOPER Sp. z o.o." ma domene grandedeveloper.pl — porzucone samo "dom".
# UWAGA: NIE ma tu "developer/deweloper/invest" — te akurat czesto ZOSTAJA w
# domenie (grandedeveloper.pl zachowal "developer"), wiec ich dropowanie
# gubiloby prawdziwe trafienia.
_DROPPABLE_FILLER = {
    "dom", "domy", "grupa", "group", "polska", "firma", "przedsiebiorstwo",
    "pph", "pw", "ppu", "zaklad", "spolka",
}

# Slowa (pol)generyczne — gdy WSPOLNE miedzy dwiema nazwami, NIE dowodza
# jeszcze zwiazku (kazda druga firma deweloperska je ma). Uzywane do
# wylowienia tokenow MARKI (patrz _brand_tokens) do porownan krzyzowych.
_BRAND_GENERIC_TOKENS = _DROPPABLE_FILLER | {
    "developer", "deweloper", "development", "invest", "investment",
    "inwestycje", "inwestycja", "nieruchomosci", "budownictwo", "mieszkania",
    "osiedle", "projekt", "construction", "building", "company", "estate",
    "real", "house", "home", "bud",
}

# Fragmenty tresci typowe dla stron parkingowych/"domena na sprzedaz"/
# placeholderow kreatorow stron — odrzucamy takie trafienia, zamiast
# falszywie potwierdzac nieistniejaca jeszcze strone dewelopera. ROZSZERZONE
# na zywo (23.07.2026): pierwsza wersja zlapala tylko klasyczny parking
# ("domain for sale"), ale PRZEPUSCILA placeholder kreatora stron Dynadot
# (royaldevelopment.com — pusty szablon z "GET STARTED"/"WEBSITE BUILDER"),
# ktory tez trzeba bylo dopisac.
_PARKING_MARKERS = (
    "domain is for sale", "this domain may be for sale", "buy this domain",
    "domain for sale", "ta domena jest na sprzedaz", "domena jest dostepna",
    "zarezerwuj te domene", "parkingcrew", "sedoparking",
    "future home of something quite cool",
    "website builder", "dynadot", "wix.com", "squarespace",
    "godaddy website builder", "strona w budowie", "witryna w budowie",
    "under construction", "coming soon", "site not published",
)

# Sygnal "to naprawde polska firma", wymagany OBOK samej nazwy w tresci
# (patrz guess_developer_domain) — zlapany na zywo falszywy pozytyw:
# "TOP INVESTMENT Sp. z o.o." (Grodzisk Mazowiecki) zgadlo domene
# top-investment.eu, ktora nalezy do NIEMIECKIEGO "TOP-Investment GmbH"
# (zupelnie inna firma, sama nazwa marki po prostu tez pasuje) — sama
# obecnosc pelnej nazwy w tresci NIE wystarczyla, strona nie miala zadnego
# polskiego sygnalu (zero "sp. z o.o."/NIP/KRS, zero polskich znakow
# diakrytycznych — za to bylo pelno "GmbH"/"Impressum").
_POLISH_DIACRITICS = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"


def _has_poland_specificity_signal(body_text: str, miejscowosc: str | None, require_strong: bool = False) -> bool:
    """Wymagane OBOK samej nazwy, zeby odrzucic homonimiczne zagraniczne
    firmy (patrz komentarz wyzej) — NIP/KRS/forma prawna PL/miejscowosc z
    RWDZ w tresci, ALBO wystarczajaca gestosc polskich znakow
    diakrytycznych (GmbH/Impressum-owe strony niemieckie ich nie maja).

    `require_strong=True` WYLACZA fallback samej gestosci diakrytykow —
    zlapany na zywo falszywy pozytyw (24.07.2026): "FOKUS Sp. z o.o."
    (jednowyrazowa, generyczna nazwa) zgadlo fokus.pl, ktore okazalo sie byc
    SKLEPEM Z SUKNIAMI WIECZOROWYMI — kompletnie niezwiazana, ale rdzennie
    polska strona z naturalnie wystarczajaca gestoscia polskich znakow, wiec
    diakrytyki jako JEDYNY sygnal nie wystarczaja dla takich nazw. Uzywane
    dla inwestorow z jednym (lub bardzo krotkim) tokenem marki — patrz
    wolujacy (guess_developer_domain/_classify_candidate_page)."""
    sample = body_text[:200_000]
    sample_norm = _norm(sample)
    if miejscowosc:
        # dopasowanie po rdzeniu (pierwsze ~5 znakow tokenu), NIE dokladnym
        # ciagu — polskie nazwy miejscowosci sie odmieniaja (np. "Grodzisk
        # Mazowiecki" w tresci strony czesto wystapi jako "w Grodzisku
        # Mazowieckim"), a dokladny substring by to przegapil
        for token in _norm(miejscowosc).split():
            stem_len = min(len(token), max(4, len(token) - 2))
            if len(token) >= 4 and token[:stem_len] in sample_norm:
                return True
    if re.search(r"sp\.?\s*z\s*o\.?\s*o\.?|\bnip\b|\bkrs\b", sample, re.IGNORECASE):
        return True
    if require_strong:
        return False
    diacritic_count = sum(1 for ch in sample[:50_000] if ch in _POLISH_DIACRITICS)
    return diacritic_count >= 3


def _needs_strong_poland_signal(investor: str) -> bool:
    """True gdy nazwa inwestora to jeden (albo zero) dystynktywny token —
    zbyt duze ryzyko przypadkowego trafienia w niezwiazana polska firme o
    tej samej, generycznej nazwie (patrz FOKUS -> fokus.pl), zeby ufac
    samej gestosci polskich znakow diakrytycznych jako dowodowi."""
    return len([t for t in core_name(investor).split() if len(t) > 1]) <= 1


def _brand_tokens(core: str) -> set[str]:
    """Tokeny MARKI (dystynktywne) — bez slow (pol)generycznych, zeby
    porownania krzyzowe nie odpalaly na samym wspolnym 'developer'/'invest'."""
    return {t for t in core.split() if len(t) >= 4 and t not in _BRAND_GENERIC_TOKENS}


def _guess_domain_bases(name_core: str) -> list[str]:
    """Rdzenie domen (bez TLD), od najpewniejszego. KLUCZOWE: zachowuje
    ORYGINALNA kolejnosc tokenow ('grande developer', nie 'developer
    grande'). Warianty (zweryfikowane na zywo, ze roznia sie w praktyce):
    (a) pelna nazwa, (b) nazwa bez slow-wypelniaczy — to daje
    grandedeveloper z 'dom grande developer', (c) sam token marki, gdy
    wystarczajaco swoisty (>=5 znakow)."""
    tokens = [t for t in name_core.split() if len(t) > 1]
    if not tokens:
        return []
    bases: list[str] = []

    def add(seq: list[str]) -> None:
        seq = [t for t in seq if t]
        if not seq:
            return
        for b in ("".join(seq), "-".join(seq)):
            if b not in bases:
                bases.append(b)

    add(tokens)
    stripped = [t for t in tokens if t not in _DROPPABLE_FILLER]
    if stripped != tokens:
        add(stripped)
    brand = sorted(_brand_tokens(name_core), key=len, reverse=True)
    if brand and len(brand[0]) >= 5:
        add([brand[0]])
    return bases


def _guess_domain_candidates(name_core: str) -> list[str]:
    """Pelna lista domen-kandydatow (rdzen x TLD), od najpewniejszej,
    przycieta do budzetu sond. Polskie male firmy bardzo czesto rejestruja
    domene = nazwa firmy, wiec to tani, zaskakujaco skuteczny pierwszy
    strzal bez zadnego klucza API."""
    cands = [base + tld for base in _guess_domain_bases(name_core) for tld in _DOMAIN_GUESS_TLDS]
    return cands[:_MAX_DOMAIN_PROBES]


def _extract_registry_ids(text: str) -> dict:
    """KRS/NIP wyciagniete z tresci strony (zwykle stopka). Polskie spolki
    maja PRAWNY obowiazek podawac je na swojej stronie, wiec to niemal
    zawsze obecny, mocny sygnal tozsamosci — kluczowy do potwierdzenia
    domeny, gdy marka rozni sie od zarejestrowanej nazwy (patrz
    _confirm_via_footer_registry)."""
    ids: dict = {}
    krs = re.search(r"KRS[:\s]*([0-9]{10})", text, re.IGNORECASE)
    if krs:
        ids["krs"] = krs.group(1)
    nip = re.search(r"NIP[:\s]*([0-9]{3}[\s-]?[0-9]{2,3}[\s-]?[0-9]{2,3}[\s-]?[0-9]{2,3})", text, re.IGNORECASE)
    if nip:
        digits = re.sub(r"\D", "", nip.group(1))
        if len(digits) == 10:
            ids["nip"] = digits
    return ids


def _confirm_via_footer_registry(
    body_text: str, investor: str, domain_base: str, known_nip: str | None, timeout: int = 15,
) -> tuple[str, str] | None:
    """(status, powod) albo None. Wyciaga KRS/NIP ze stopki strony i
    weryfikuje w OFICJALNYM rejestrze KRS (api-krs.ms.gov.pl) — mostkuje
    najtrudniejszy przypadek: marka na stronie != zarejestrowana nazwa
    (zweryfikowane na zywo: grandedeveloper.pl ma w stopce KRS 0000800084 ->
    oficjalnie 'GRANDE DEWELOPER ... sp.k.', co dzieli marke 'grande' z
    inwestorem RWDZ 'DOM GRANDE DEVELOPER sp. z o.o.'). Rejestr jest
    urzedowy, darmowy, bez klucza — najmocniejszy dostepny sygnal."""
    ids = _extract_registry_ids(body_text)
    known_nip_digits = re.sub(r"\D", "", known_nip) if known_nip else ""

    # NIP inwestora (jesli znany z CEIDG/RWDZ) zgodny z NIP ze stopki -> tozsamosc
    if known_nip_digits and ids.get("nip") == known_nip_digits:
        return STATUS_CONFIRMED, "NIP inwestora zgodny z NIP w stopce strony (tożsamość)"

    krs = ids.get("krs")
    if not krs:
        return None
    try:
        info = company_lookup.lookup_krs_by_number(krs, timeout=timeout)
    except Exception:
        return None
    if not info.found or not info.name:
        return None

    if known_nip_digits and info.nip and re.sub(r"\D", "", info.nip) == known_nip_digits:
        return STATUS_CONFIRMED, f"KRS {krs} ze stopki → NIP zgodny z inwestorem (rejestr KRS)"

    shared = {t for t in (_brand_tokens(core_name(investor)) & _brand_tokens(core_name(info.name)))
              if t in domain_base}
    if shared:
        return STATUS_LIKELY, (f"domena potwierdzona przez rejestr: KRS {krs} w stopce → "
                               f"'{info.name}' dzieli markę {sorted(shared)} z inwestorem RWDZ")
    return None


def _looks_like_parking_page(text: str) -> bool:
    blob = _norm(text[:5000])
    return any(marker in blob for marker in _PARKING_MARKERS)


def _probe_domain(domain: str, timeout: int = 8) -> tuple[str, str] | None:
    """(finalny_url, tresc_strony) gdy zgadnieta domena zyje i NIE wyglada na
    strone parkingowa/na sprzedaz, inaczej None. Probuje bez i z 'www.'."""
    for candidate in (f"https://{domain}/", f"https://www.{domain}/"):
        try:
            resp = requests.get(candidate, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"},
                                 timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            continue
        if resp.status_code >= 400:
            continue
        if _looks_like_parking_page(resp.text):
            continue
        return resp.url, resp.text
    return None


def guess_developer_domain(
    investor: str, nip: str | None = None, miejscowosc: str | None = None, timeout: int = 8,
) -> DeveloperSite | None:
    """Sygnal DARMOWY, sprawdzany PIERWSZY (patrz docstring modulu, krok 2) —
    zgaduje domene wprost z nazwy inwestora i probuje ja pobrac. Zwraca None
    (NIGDY status 'nie_znaleziono') gdy nic sensownego nie znaleziono —
    wolujacy (find_developer_site) ma wtedy probowac Places/Brave dalej.

    WALIDACJA — kaskada trzech niezaleznych, coraz slabszych sciezek; kazda
    z wlasnym zabezpieczeniem przeciw falszywym pozytywom zlapanym na zywo:
      1. Znany NIP inwestora (z CEIDG/RWDZ) wprost w tresci -> potwierdzona.
      2. REJESTR ZE STOPKI (patrz _confirm_via_footer_registry): KRS/NIP ze
         strony -> oficjalne API KRS -> porownanie marki. Mostkuje przypadek
         'marka != zarejestrowana nazwa' (grandedeveloper.pl <-> 'Dom Grande
         Developer sp. z o.o.'). Tylko dla domen pokrywajacych >=2 tokeny
         nazwy — guard przeciw trafieniu po jednym generycznym slowie.
      3. PELNA splaszczona nazwa inwestora w tresci ORAZ sygnal 'to polska
         firma' (patrz _has_poland_specificity_signal — odrzuca homonimiczna
         zagraniczna firme, np. niemieckie 'TOP-Investment GmbH').
    Status 'potwierdzona' zarezerwowany dla tozsamosci NIP; reszta ->
    'prawdopodobna' (ten sam poziom ostroznosci co reszta modulu)."""
    name_c = core_name(investor)
    full_flat = re.sub(r"[^a-z0-9]", "", name_c)
    if len(full_flat) < 5:
        return None  # nazwa zbyt krotka/generyczna po splaszczeniu — zbyt ryzykowne zgadywanie
    core_tokens = [t for t in name_c.split() if len(t) >= 3]

    for base in _guess_domain_bases(name_c):
        base_flat = re.sub(r"[^a-z0-9]", "", base)
        coverage = sum(1 for t in core_tokens if t in base_flat)
        for tld in _DOMAIN_GUESS_TLDS:
            site = _probe_and_classify(investor, base + tld, nip, miejscowosc,
                                       source_note="zgadnięta domena z nazwy inwestora",
                                       require_brand_in_domain=False, timeout=timeout)
            if site is not None:
                return site
    return None


def _classify_candidate_page(
    investor: str, final_url: str, body_text: str, nip: str | None, miejscowosc: str | None,
    domain_base: str, coverage: int, source_note: str,
) -> DeveloperSite | None:
    """Wspolna walidacja strony-kandydata — uzywana przez WSZYSTKIE zrodla
    (zgadywanie domeny, crt.sh, DuckDuckGo), zeby dyscyplina anty-falszywo-
    pozytywowa byla identyczna niezaleznie od tego, skad wzieto domene.
    Kaskada trzech coraz slabszych sciezek (patrz guess_developer_domain)."""
    sample = body_text[:200_000]
    nip_digits = re.sub(r"\D", "", nip) if nip else ""

    # 1) znany NIP inwestora wprost w tresci -> tozsamosc
    if nip_digits and nip_digits in re.sub(r"\D", "", sample):
        return DeveloperSite(investor=investor, url=final_url, status=STATUS_CONFIRMED,
                             matched_on=f"{source_note} + NIP inwestora w treści strony")

    # 2) rejestr ze stopki; guard coverage>=2 (domena pokrywa >=2 tokeny nazwy)
    if coverage >= 2:
        conf = _confirm_via_footer_registry(sample, investor, domain_base, nip)
        if conf is not None:
            status, reason = conf
            return DeveloperSite(investor=investor, url=final_url, status=status, matched_on=reason)

    # 3) pelna nazwa inwestora w tresci + sygnal polskiej firmy (require_strong
    #    dla jednowyrazowych/generycznych nazw — patrz _needs_strong_poland_signal)
    body_flat = re.sub(r"[^a-z0-9]", "", _norm(sample))
    strong = _needs_strong_poland_signal(investor)
    if full_flat_ok(investor, body_flat) and _has_poland_specificity_signal(sample, miejscowosc, require_strong=strong):
        return DeveloperSite(investor=investor, url=final_url, status=STATUS_LIKELY,
                             matched_on=f"{source_note}, pełna nazwa + sygnał polskiej firmy w treści")
    return None


def full_flat_ok(investor: str, body_flat: str) -> bool:
    full_flat = re.sub(r"[^a-z0-9]", "", core_name(investor))
    return bool(full_flat) and len(full_flat) >= 5 and full_flat in body_flat


def _probe_and_classify(
    investor: str, domain: str, nip: str | None, miejscowosc: str | None,
    source_note: str, require_brand_in_domain: bool, timeout: int = 8,
) -> DeveloperSite | None:
    """Pobiera domene-kandydata i klasyfikuje przez _classify_candidate_page.
    `require_brand_in_domain` (dla wynikow z crt.sh/DuckDuckGo): odrzuca
    domeny, ktore nie zawieraja zadnego tokenu marki inwestora — chroni przed
    'potwierdzeniem' losowego wyniku wyszukiwarki (np. artykulu/katalogu),
    ktory tylko wspomina firme. Dla zgadywania domeny False (domena i tak
    powstala z nazwy)."""
    domain = domain.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain or "." not in domain or _is_blocked_domain(domain):
        return None
    base_flat = re.sub(r"[^a-z0-9]", "", domain.split(".")[0])
    core_tokens = [t for t in core_name(investor).split() if len(t) >= 3]
    if require_brand_in_domain and not any(t in base_flat for t in _brand_tokens(core_name(investor))):
        return None
    coverage = sum(1 for t in core_tokens if t in base_flat)
    probed = _probe_domain(domain, timeout=timeout)
    if probed is None:
        return None
    final_url, body_text = probed
    if _is_blocked_domain(_domain_of(final_url)):
        return None
    return _classify_candidate_page(investor, final_url, body_text, nip, miejscowosc,
                                    base_flat, coverage, source_note)


def _discover_via_crtsh(investor: str, timeout: int = 15) -> list[str]:
    """OPCJA B — domeny-kandydaci z publicznych logow Certificate Transparency
    (crt.sh). Darmowe, bez klucza, realne istniejace domeny. Zapytanie po
    najbardziej swoistym rdzeniu marki (>=8 znakow — inaczej za duzo szumu).
    Flaky (bywa HTTP 502) — przy jakimkolwiek bledzie zwraca [] (graceful)."""
    tokens = [t for t in core_name(investor).split() if len(t) > 1]
    stripped = [t for t in tokens if t not in _DROPPABLE_FILLER]
    seed = "".join(stripped if len(stripped) >= 2 else tokens)
    if len(seed) < 8:
        return []
    try:
        resp = requests.get(_CRTSH_URL, params={"q": f"%{seed}%", "output": "json"},
                            headers={"User-Agent": _UA}, timeout=timeout)
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    domains: list[str] = []
    for entry in data:
        for name in str(entry.get("name_value", "")).split("\n"):
            name = name.strip().lower().lstrip("*.")
            if name.startswith("www."):
                name = name[4:]
            if name and "." in name and " " not in name and name not in domains:
                domains.append(name)
    return domains[:_MAX_DISCOVERY_CANDIDATES]


def _discover_via_duckduckgo(investor: str, timeout: int = 20) -> list[str]:
    """OPCJA A — domeny-kandydaci z DuckDuckGo HTML (darmowa wyszukiwarka,
    bez klucza). Rankuje po trafnosci (na zywo grandedeveloper.pl bylo #1).
    Blokuje po 1-2 zapytaniach (HTTP 202 'anomaly') — po wykryciu blokady
    wylaczamy sie na resztę przebiegu (_ddg_blocked), zeby nie spamowac."""
    global _ddg_blocked
    if _ddg_blocked:
        return []
    query = f'"{core_name(investor) or investor}" deweloper'
    try:
        resp = requests.post(_DDG_URL, data={"q": query}, headers={"User-Agent": _UA}, timeout=timeout)
    except requests.RequestException:
        return []
    if resp.status_code == 202 or "anomaly" in resp.text[:2000].lower():
        _ddg_blocked = True
        log.info("developer_search: DuckDuckGo zablokowal zapytania (anomaly) — pomijam do konca przebiegu")
        return []
    if resp.status_code != 200:
        return []
    domains: list[str] = []
    for enc in re.findall(r'uddg=([^&"]+)', resp.text):
        d = _domain_of(urllib.parse.unquote(enc))
        if d and d not in domains:
            domains.append(d)
    time.sleep(1.5)  # lagodny rate-limit miedzy zapytaniami
    return domains[:_MAX_DISCOVERY_CANDIDATES]


# ======================= OPCJA C: odwrocenie z portalu =======================
# Gdy verify.py juz potwierdzil (CONFIRMED/LIKELY) ze konkretne ogloszenie na
# portalu odpowiada TEJ inwestycji z RWDZ, strona samego portalu czesto ma
# link do wlasnej strony dewelopera. Zweryfikowane na zywo (24.07.2026) TYLKO
# dla RynekPierwotny — profil dewelopera (link z breadcrumb JSON-LD kazdej
# oferty) ma jawny <a data-gtm-click="Odwiedź stronę dewelopera" href="...">
# oraz NIP w osadzonym JSON. Otodom/inne portale NIE zostaly zweryfikowane na
# zywo w tej rundzie (blokada bot-protection przy eksploracyjnym scrapowaniu
# bez znanego URL-a) — celowo NIE zgadujemy ich struktury, zostaje jedynie
# RynekPierwotny, dopoki ktos nie zweryfikuje pozostalych na zywo.
_RP_DEV_PROFILE_RE = re.compile(
    r'"name":"([^"]+)","item":"(https://rynekpierwotny\.pl/deweloperzy/[^"]+)"'
)
_RP_DEV_WEBSITE_RE = re.compile(
    r'data-gtm-click="Odwiedź stronę dewelopera"[^>]*href="([^"]+)"'
)
_RP_DEV_NIP_RE = re.compile(r'"nip":"(\d{10})"')


def _rynekpierwotny_developer_profile(offer_url: str, timeout: int = 15) -> tuple[str, str] | None:
    """(nazwa_dewelopera_na_portalu, url_profilu) wyciagniete z breadcrumb
    JSON-LD strony oferty, albo None gdy nie znaleziono/blad sieciowy."""
    try:
        resp = requests.get(offer_url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    m = _RP_DEV_PROFILE_RE.search(resp.text)
    return (m.group(1), m.group(2)) if m else None


def reverse_from_portal_match(
    investor: str, portal: str, listing_url: str, verdict: str,
    nip: str | None = None, timeout: int = 15,
) -> DeveloperSite | None:
    """OPCJA C — patrz docstring modulu, krok 1. Zwraca None (NIGDY
    'nie_znaleziono') gdy nie da sie zastosowac albo walidacja marki/NIP sie
    nie powiedzie — wolujacy probuje dalej (zgadywanie/discovery/Places/Brave).

    Celowo TYLKO portal == 'rynekpierwotny' i verdict CONFIRMED/LIKELY —
    REVIEW/REJECTED to dopasowania niepewne, ktore moga wskazywac na INNA
    nieruchomosc, wiec ich deweloper nie musi byc naszym inwestorem (prefer
    false negative)."""
    if portal != "rynekpierwotny" or verdict not in ("CONFIRMED", "LIKELY") or not listing_url:
        return None
    profile = _rynekpierwotny_developer_profile(listing_url, timeout=timeout)
    if profile is None:
        return None
    portal_dev_name, profile_url = profile
    try:
        resp = requests.get(profile_url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    website_match = _RP_DEV_WEBSITE_RE.search(resp.text)
    if not website_match:
        return None
    website = website_match.group(1).split("?")[0]  # bez utm_ parametrow portalu
    if _is_blocked_domain(_domain_of(website)):
        return None

    profile_nip_match = _RP_DEV_NIP_RE.search(resp.text)
    profile_nip = profile_nip_match.group(1) if profile_nip_match else None
    known_nip_digits = re.sub(r"\D", "", nip) if nip else ""
    if known_nip_digits and profile_nip == known_nip_digits:
        return DeveloperSite(
            investor=investor, url=website, status=STATUS_CONFIRMED,
            matched_on=f"link ze zweryfikowanej oferty RynekPierwotny ('{portal_dev_name}') + NIP zgodny",
        )

    # brak znanego NIP inwestora do porownania -> wymagamy zgodnosci marki
    # miedzy nazwa dewelopera NA PORTALU a inwestorem z RWDZ (ten sam
    # wzorzec co _confirm_via_footer_registry)
    shared = _brand_tokens(core_name(investor)) & _brand_tokens(core_name(portal_dev_name))
    if not shared:
        return None
    return DeveloperSite(
        investor=investor, url=website, status=STATUS_LIKELY,
        matched_on=(f"link ze zweryfikowanej oferty RynekPierwotny — deweloper na portalu "
                   f"'{portal_dev_name}' dzieli markę {sorted(shared)} z inwestorem RWDZ"),
    )


def _search_places(query: str, api_key: str, timeout: int = 15) -> list[dict]:
    """Google Places API (New) Text Search. fieldMask ograniczony do pol
    faktycznie potrzebnych (Places API rozlicza koszt zapytania czesciowo wg
    liczby zadanych pol) — patrz PLACES_FIELD_MASK."""
    resp = requests.post(
        PLACES_SEARCH_TEXT_URL,
        json={"textQuery": query},
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": PLACES_FIELD_MASK,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("places", [])


def lookup_website_via_places(investor: str, miejscowosc: str | None, timeout: int = 15) -> DeveloperSite | None:
    """Sygnal PODSTAWOWY, silniejszy niz Brave Search (patrz docstring
    modulu, krok 2) — Google juz zweryfikowal powiazanie firma<->strona przez
    Google Moja Firma, wiec niepuste `websiteUri` od razu daje status
    'potwierdzona' BEZ dodatkowej walidacji tekstowej (w odroznieniu od
    kandydatow ze sciezki Brave, patrz _validate_nip).

    Zwraca None (NIE DeveloperSite ze statusem nie_znaleziono) w kazdym
    przypadku, gdy wolujacy (find_developer_site) ma spasc na fallback Brave:
    brak klucza API, blad sieciowy, brak wyniku, albo zaden wynik nie ma
    uzytecznego websiteUri (pusty / domena portalu-agregatora)."""
    api_key = os.environ.get(GOOGLE_PLACES_API_KEY_ENV_VAR)
    if not api_key:
        return None

    cache_key = f"{_norm(investor)}|{_norm(miejscowosc or '')}"
    conn = _cache_connect()
    try:
        hit, cached_website = _places_cache_get(conn, cache_key)
        if hit:
            if cached_website:
                return DeveloperSite(
                    investor=investor, url=cached_website, status=STATUS_CONFIRMED,
                    matched_on="Google Places (Google Moja Firma) — website zweryfikowany przez Google",
                )
            return None  # zapamietane "brak wyniku", wciaz w ramach TTL

        query = f"{investor} {miejscowosc or ''}".strip()
        try:
            places = _search_places(query, api_key, timeout=timeout)
        except requests.RequestException:
            log.warning("developer_search: zapytanie Places nie powiodlo sie dla %r", query, exc_info=True)
            return None  # blad sieciowy -> fallback do Brave; NIE cache'ujemy bledu jako "nie znaleziono"

        website = None
        for place in places:
            candidate = (place.get("websiteUri") or "").strip()
            if candidate and not _is_blocked_domain(_domain_of(candidate)):
                website = candidate
                break

        _places_cache_put(conn, cache_key, website)
        if website:
            return DeveloperSite(
                investor=investor, url=website, status=STATUS_CONFIRMED,
                matched_on="Google Places (Google Moja Firma) — website zweryfikowany przez Google",
            )
        return None
    finally:
        conn.close()


def _search_brave(query: str, api_key: str, timeout: int = 15) -> list[dict]:
    resp = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": query, "count": 10},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json().get("web", {}).get("results", [])


def _rank_candidate(result: dict, name_core: str) -> tuple[int, str] | None:
    """(priorytet, powod) albo None gdy wynik nie nadaje sie na kandydata w
    ogole (portal/blocklist). Priorytet: 2 = domena zawiera marke (najwyzszy,
    JEDYNY dopuszczalny do statusu potwierdzona/prawdopodobna — patrz nizej),
    1 = nazwa w tytule/opisie (tylko kandydat_niepewny), 0 = social fallback.

    WAZNE, zweryfikowane na zywo (23.07.2026): dopasowanie po samym
    WYSTAPIENIU slow z nazwy w tekscie strony jest NIEWIARYGODNE, gdy nazwa
    inwestora sklada sie ze slow ogolnego jezyka — realny przypadek: "TOP
    INVESTMENT Sp. z o.o." (marka rzeczywista) trafilo w
    companiesmarketcap.com/.../largest-investment-companies-by-market-cap/,
    KOMPLETNIE niezwiazana strone o rynkach finansowych, bo fraza "top
    investment" (dokladnie w tej kolejnosci, sasiadujaco) naturalnie
    wystepuje w angielskim tekscie o "top investment opportunities" itp. —
    nawet wymog SASIEDZTWA slow (nie tylko niezaleznej obecnosci) tego NIE
    zlapal. Jedyny naprawde wiarygodny sygnal to NAZWA DOMENY zawierajaca
    marke — przypadkowa domena praktycznie nigdy nie zawiera akurat tego
    samego ciagu znakow. Dlatego priorytet 1 (samo wystapienie w tekscie)
    moze wyladowac WYLACZNIE jako kandydat_niepewny, nigdy wyzej."""
    url = result.get("url", "")
    if not url:
        return None
    domain = _domain_of(url)
    if _is_blocked_domain(domain):
        return None
    name_tokens = [t for t in name_core.split() if len(t) > 2]
    if not name_tokens:
        return None
    domain_flat = re.sub(r"[^a-z0-9]", "", domain)
    if _is_social_fallback(domain):
        blob = _norm(f"{result.get('title','')} {result.get('description','')}")
        if all(t in blob for t in name_tokens):
            return (0, "fallback społecznościowy")
        return None
    # WSZYSTKIE tokeny nazwy musza byc w domenie (nie wystarczy jeden z wielu —
    # zweryfikowane na zywo, ze "investment" samo w domenie "investmentgroup.pl"
    # to za slaby sygnal dla nazwy "TOP INVESTMENT", mimo ze "investment" ma
    # >=4 znaki). Dla nazw jednowyrazowych wymagamy dodatkowo dlugosci >=4, zeby
    # krotkie, generyczne slowo samo nie wystarczylo.
    if len(name_tokens) == 1:
        domain_evidence = len(name_tokens[0]) >= 4 and name_tokens[0] in domain_flat
    else:
        domain_evidence = all(t in domain_flat for t in name_tokens)
    if domain_evidence:
        return (2, "nazwa domeny zawiera markę inwestora")
    blob = _norm(f"{result.get('title','')} {result.get('description','')}")
    if all(t in blob for t in name_tokens):
        return (1, "nazwa inwestora w tytule/opisie wyniku (bez potwierdzenia domeną — niepewne)")
    return None


def _validate_nip(url: str, nip: str | None, timeout: int = 15) -> tuple[bool, str | None]:
    """(potwierdzone, powod). Sprawdza WYLACZNIE obecnosc NIP w tresci strony
    glownej kandydata — to jedyny sygnal wystarczajaco swoisty (10-cyfrowy
    numer), zeby SAMODZIELNIE podniesc status do 'potwierdzona'.

    Celowo NIE sprawdzamy tu samej pelnej nazwy inwestora w tresci jako
    niezaleznej podstawy potwierdzenia — to dokladnie ten sam blad, ktory
    zlapalismy na zywo w _rank_candidate (patrz jego docstring): nazwy
    zbudowane ze slow ogolnego jezyka (np. "TOP INVESTMENT") wystepuja na
    kompletnie niezwiazanych stronach. Dlatego dopasowanie samej nazwy w
    tresci moze co najwyzej wzmocnic 'matched_on' juz istniejacego kandydata
    z dowodem domenowym (priorytet 2), nigdy nie jest jedyna podstawa."""
    if not nip:
        return False, None
    try:
        resp = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "pl-PL"}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException:
        return False, None
    nip_digits = re.sub(r"\D", "", nip)
    if nip_digits and nip_digits in re.sub(r"\D", "", resp.text):
        return True, "NIP w treści strony"
    return False, None


# ------------------------------- cache -------------------------------

def _cache_connect() -> sqlite3.Connection:
    CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS developer_sites (
            name_key TEXT PRIMARY KEY,
            url TEXT,
            status TEXT,
            matched_on TEXT,
            checked_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    # Cache osobny od developer_sites (klucz obejmuje miejscowosc, nie tylko
    # nazwe — Places jest zapytywane per nazwa+miejscowosc, patrz
    # lookup_website_via_places), analogiczny do cache Brave: "znaleziono"
    # bez wygasania, "brak wyniku" z TTL (patrz _places_cache_get).
    conn.execute(
        """CREATE TABLE IF NOT EXISTS places_lookup (
            cache_key TEXT PRIMARY KEY,
            website_uri TEXT,
            found INTEGER,
            checked_at TEXT DEFAULT (datetime('now'))
        )"""
    )
    return conn


def _places_cache_get(conn: sqlite3.Connection, cache_key: str) -> tuple[bool, str | None]:
    """(trafiono_w_cache, website_uri). `website_uri` None przy trafieniu
    oznacza zapamietane "brak wyniku" (w ramach TTL) — patrz
    lookup_website_via_places, gdzie to rozroznienie decyduje o fallbacku."""
    row = conn.execute(
        "SELECT website_uri, found, checked_at FROM places_lookup WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    if row is None:
        return False, None
    website_uri, found, checked_at = row
    if not found:
        try:
            checked_dt = datetime.fromisoformat(checked_at).replace(tzinfo=timezone.utc)
        except ValueError:
            return False, None
        if datetime.now(timezone.utc) - checked_dt > timedelta(days=NOT_FOUND_TTL_DAYS):
            return False, None  # TTL wygasl — nazwa mogla pozniej dostac wpis w Google Moja Firma
    return True, website_uri


def _places_cache_put(conn: sqlite3.Connection, cache_key: str, website_uri: str | None) -> None:
    conn.execute(
        """INSERT INTO places_lookup (cache_key, website_uri, found, checked_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(cache_key) DO UPDATE SET
             website_uri=excluded.website_uri, found=excluded.found, checked_at=excluded.checked_at""",
        (cache_key, website_uri, int(bool(website_uri))),
    )
    conn.commit()


def _cache_get(conn: sqlite3.Connection, name_key: str) -> DeveloperSite | None:
    row = conn.execute(
        "SELECT url, status, matched_on, checked_at FROM developer_sites WHERE name_key = ?", (name_key,)
    ).fetchone()
    if row is None:
        return None
    url, status, matched_on, checked_at = row
    if status == STATUS_NOT_FOUND:
        try:
            checked_dt = datetime.fromisoformat(checked_at).replace(tzinfo=timezone.utc)
        except ValueError:
            return None  # data nie do sparsowania -> traktuj jak brak cache, odpytaj ponownie
        if datetime.now(timezone.utc) - checked_dt > timedelta(days=NOT_FOUND_TTL_DAYS):
            return None  # TTL wygasl — nazwa mogla pozniej dostac strone
    return DeveloperSite(investor=name_key, url=url, status=status, matched_on=matched_on)


def _cache_put(conn: sqlite3.Connection, name_key: str, site: DeveloperSite) -> None:
    conn.execute(
        """INSERT INTO developer_sites (name_key, url, status, matched_on, checked_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(name_key) DO UPDATE SET
             url=excluded.url, status=excluded.status, matched_on=excluded.matched_on,
             checked_at=excluded.checked_at""",
        (name_key, site.url, site.status, site.matched_on),
    )
    conn.commit()


# ------------------------------ glowna funkcja ------------------------------

def find_developer_site(
    investor: str, nip: str | None = None, miejscowosc: str | None = None,
    use_crtsh: bool = True, use_duckduckgo: bool = True,
    portal_matches: list[dict] | None = None,
) -> DeveloperSite:
    """Punkt wejscia. `nip` opcjonalny (z company_lookup.CompanyInfo.nip,
    jesli akurat znany) — wzmacnia walidacje do statusu 'potwierdzona'.
    `miejscowosc` opcjonalna (z RWDZ). `use_crtsh`/`use_duckduckgo` —
    darmowe warstwy odkrywania domen (opcja B / A), domyslnie wlaczone.
    `portal_matches` — opcjonalna lista {"portal","url","verdict"} z JUZ
    obliczonych dopasowan portalowych (patrz verify.py/main.py step_enrich) —
    wlacza Opcje C (reverse_from_portal_match), NAJSILNIEJSZY dostepny darmowy
    sygnal, gdy jest czego uzyc.

    Kolejnosc (darmowe najpierw): odwrocenie z portalu (opcja C) ->
    zgadywanie domeny -> crt.sh -> DuckDuckGo -> Google Places (klucz) ->
    Brave (klucz)."""
    if not investor or not investor.strip():
        return DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)
    if is_individual(investor):
        return DeveloperSite(investor=investor, status=STATUS_INDIVIDUAL)

    name_key = _norm(investor)
    conn = _cache_connect()
    try:
        cached = _cache_get(conn, name_key)
        if cached is not None:
            return DeveloperSite(investor=investor, url=cached.url, status=cached.status, matched_on=cached.matched_on)

        # OPCJA C, sprawdzana NAJPIERW gdy dostepna: odwrocenie z JUZ
        # potwierdzonego dopasowania portalowego — patrz docstring modulu,
        # krok 1, i reverse_from_portal_match.
        for pm in (portal_matches or []):
            reversed_site = reverse_from_portal_match(
                investor, pm.get("portal", ""), pm.get("url", ""), pm.get("verdict", ""), nip=nip)
            if reversed_site is not None:
                _cache_put(conn, name_key, reversed_site)
                return reversed_site

        # Sygnal DARMOWY, sprawdzany NASTEPNIE: zgadywanie domeny wprost z
        # nazwy inwestora — zero klucza API, zero kosztu (patrz docstring
        # modulu, krok 2, i guess_developer_domain).
        guessed_site = guess_developer_domain(investor, nip=nip, miejscowosc=miejscowosc)
        if guessed_site is not None:
            _cache_put(conn, name_key, guessed_site)
            return guessed_site

        # DARMOWE warstwy ODKRYWANIA domen (opcja B: crt.sh, opcja A:
        # DuckDuckGo) — kazdy zwrocony kandydat przechodzi TE SAMA rygorystyczna
        # walidacje co zgadywanie domeny (_probe_and_classify z wymogiem tokenu
        # marki w domenie), wiec luzniejsze zrodlo NIE luzuje kontroli
        # falszywych pozytywow.
        discovery = []
        if use_crtsh:
            discovery.append(("wynik crt.sh (Certificate Transparency)", _discover_via_crtsh))
        if use_duckduckgo:
            discovery.append(("wynik DuckDuckGo", _discover_via_duckduckgo))
        for source_note, discover in discovery:
            try:
                candidate_domains = discover(investor)
            except Exception:
                log.warning("developer_search: %s nie powiodlo sie", source_note, exc_info=True)
                continue
            for domain in candidate_domains:
                site = _probe_and_classify(investor, domain, nip, miejscowosc,
                                           source_note=source_note, require_brand_in_domain=True)
                if site is not None:
                    _cache_put(conn, name_key, site)
                    return site

        # Sygnal PODSTAWOWY: Google Places API — silniejszy niz Brave, bo
        # Google juz zweryfikowal firma<->strona przez Google Moja Firma.
        # Brak klucza / brak wyniku -> None, spadamy na fallback Brave nizej
        # (patrz docstring lookup_website_via_places).
        places_site = lookup_website_via_places(investor, miejscowosc)
        if places_site is not None:
            _cache_put(conn, name_key, places_site)
            return places_site

        api_key = os.environ.get(BRAVE_API_KEY_ENV_VAR)
        if not api_key:
            # brak klucza — nie cache'ujemy (nie chcemy "nie_znaleziono" na 30 dni
            # tylko dlatego, ze dzis nie bylo klucza w srodowisku)
            return DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)

        name_c = core_name(investor)
        best: tuple[int, dict, str] | None = None  # (priorytet, result, powod)
        for query in _query_variants(investor):
            try:
                results = _search_brave(query, api_key)
            except requests.RequestException:
                log.warning("developer_search: zapytanie Brave nie powiodlo sie dla %r", query, exc_info=True)
                continue
            for r in results:
                ranked = _rank_candidate(r, name_c)
                if ranked is None:
                    continue
                priority, reason = ranked
                if best is None or priority > best[0]:
                    best = (priority, r, reason)
            if best is not None and best[0] >= 1:
                break  # wystarczajaco dobry wynik — nie odpytuj kolejnych wariantow (budzet)
            time.sleep(1.0)

        if best is None:
            site = DeveloperSite(investor=investor, status=STATUS_NOT_FOUND)
            _cache_put(conn, name_key, site)
            return site

        priority, result, reason = best
        url = result.get("url")
        domain = _domain_of(url)
        if _is_social_fallback(domain):
            site = DeveloperSite(investor=investor, url=url, status=STATUS_UNCERTAIN, matched_on=reason)
        elif priority >= 2:
            # dowod domenowy (marka w nazwie domeny) — jedyny priorytet, ktory
            # moze osiagnac potwierdzona/prawdopodobna, patrz _rank_candidate
            nip_confirmed, valid_reason = _validate_nip(url, nip)
            if nip_confirmed:
                site = DeveloperSite(investor=investor, url=url, status=STATUS_CONFIRMED, matched_on=valid_reason)
            else:
                site = DeveloperSite(investor=investor, url=url, status=STATUS_LIKELY, matched_on=reason)
        else:
            # priorytet 1 — samo wystapienie nazwy w tytule/opisie, bez
            # potwierdzenia domena — zawsze kandydat_niepewny, nigdy wyzej
            # (patrz uzasadnienie w _rank_candidate: falszywe trafienie
            # "TOP INVESTMENT" na companiesmarketcap.com)
            site = DeveloperSite(investor=investor, url=url, status=STATUS_UNCERTAIN, matched_on=reason)
        _cache_put(conn, name_key, site)
        return site
    finally:
        conn.close()
