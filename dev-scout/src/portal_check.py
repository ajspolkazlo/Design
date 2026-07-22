"""
Sprawdza, czy dana inwestycja jest juz widoczna na popularnych portalach
nieruchomosci (Otodom, OLX, RynekPierwotny, Morizon, Gratka, Domiporta).

Cel: nie odrzucac na twardo, tylko oznaczyc status + date sprawdzenia.
Lead, ktory dzis jest "czysty", moze pojawic sie na portalu za kilka tygodni —
to okno czasu jest dokladnie tym, co ma dawac przewage. Re-checkuj leady
co `portal_check.recheck_after_days` (patrz config.yaml), nie tylko raz.

============================== TRZY BACKENDY ==============================
0) BACKEND SEARCH API (Brave Search) — PRIORYTETOWY, gdy jest klucz.
   Jedno zapytanie z filtrem site:otodom.pl OR site:olx.pl OR ... pokrywa
   WSZYSTKIE portale naraz, wlacznie z Otodom, ktorego zaden inny backend
   tu nie obsluzy bez ryzyka. To oficjalne, platne API wyszukiwarki (nie
   scraping, nie omijanie blokad) — Brave indeksuje strony portali samo,
   my tylko pytamy o wynik. ZWERYFIKOWANE NA ZYWO (przez WebSearch, manualnie):
   zapytanie '"Kozacka" "Marki" (site:otodom.pl OR site:rynekpierwotny.pl OR ...)'
   trafnie znalazlo realne oferty na Otodom i RynekPierwotny; zapytanie z
   nieistniejacym adresem poprawnie nie znalazlo nic. Wymaga klucza API
   (zmienna BRAVE_SEARCH_API_KEY) — patrz docstring _check_via_search_api.

1) BACKEND HTTP (requests) — dziala z kazdego IP, ale tylko dla portali, ktore
   nie blokuja prostego klienta HTTP. Dzis to praktycznie tylko OLX (jego
   wewnetrzny endpoint /api/v1/offers jest jawnie dozwolony w robots.txt i
   zwraca JSON — ZWERYFIKOWANE na zywo, dziala i trafnie). Uruchamiany ZAWSZE
   jako darmowa, natychmiastowa weryfikacja dodatkowa — niezaleznie od tego,
   czy backend search API jest skonfigurowany.

2) BACKEND BROWSER (Playwright, prawdziwy Chromium) — dla portali, ktore
   blokuja goly HTTP (Otodom = ochrona CDN/CloudFront) albo renderuja wyniki
   dopiero JS-em (Next.js/React). Prawdziwa przegladarka laduje strone tak jak
   czlowiek — to NIE jest omijanie zabezpieczen, tylko uzycie strony zgodnie z
   jej przeznaczeniem. Wlaczany flagą `portal_check.enable_browser`.

   WAZNE — czego tu SWIADOMIE NIE MA (granica, ktorej nie przekraczamy):
   rozwiazywania CAPTCHA, rotacji proxy/IP zeby omijac bany, ani podszywania
   sie pod fingerprint zeby oszukac systemy anty-bot. To juz jest realne
   ryzyko prawne (naruszenie ToS z mozliwym roszczeniem) i techniczna zbroja,
   ktorej ten use-case nie potrzebuje. Praktyczna odpowiedz na "portal blokuje"
   to uruchomienie backendu browser Z MASZYNY ADAMA (polskie IP domowe, realny
   internet) — wiekszosc blokad, ktore widac z serwerowni/proxy, tam znika.

   UWAGA o ToS/robots.txt per portal (stan na 2026, do swiadomej decyzji Adama):
     - OTODOM: brak zakazu w robots na wyniki; blokuje goly HTTP na CDN.
     - RYNEKPIERWOTNY: robots zabrania *?phrase= i */ws/* (czyli wyszukiwania).
     - MORIZON: robots zabrania /api oraz parametrow sort/limit/locations.
     - DOMIPORTA: robots zabrania endpointow wyszukiwania i banuje UA "Scrapy".
     - GRATKA: brak robots.txt.
   Adam swiadomie akceptuje ryzyko ToS dla tych portali (decyzja z lipca 2026).
   Backend browser jest DOMYSLNIE WYLACZONY — wlacz go tam, gdzie to
   uruchamiasz, ustawiajac enable_browser: true.

   Backendu browser NIE dalo sie zweryfikowac w sandboxie, w ktorym powstal ten
   kod — tamtejsze proxy nie przepuszcza ruchu Chromium (ERR_CONNECTION_RESET
   nawet dla dozwolonych hostow). Kod jest napisany "pod prawdziwe srodowisko";
   przy pierwszym uruchomieniu z maszyny Adama trzeba potwierdzic, ze szablony
   URL wyszukiwania (search_url_templates w config.yaml) sa aktualne.

   Gdy backend search API jest skonfigurowany (ma klucz), backend browser jest
   POMIJANY — search API pokrywa te same portale szybciej, taniej (bez
   utrzymywania Chromium) i bez ryzyka ToS. Browser zostaje jako fallback na
   wypadek braku klucza.

KOLEJNOSC PROBOWANIA: search API (jesli klucz) -> zawsze OLX http (za darmo) ->
browser (tylko gdy brak klucza search API i enable_browser=true).

WAZNE o jakosci sygnalu (patrz tez CLAUDE.md):
  NIE dopasowuj po samej nazwie firmy — deweloper sprzedaje pod nazwa
  PROJEKTU/osiedla, nie nazwa spolki. Sygnal = ulica + miejscowosc z RWDZ.
  `_check_*` wymaga co najmniej dwoch sensownych tokenow w query (np. ulica +
  miejscowosc), inaczej "brak trafien" nie jest wiarygodnym sygnalem "czysty".
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

REQUEST_DELAY_SECONDS = 1.5  # bufor miedzy zapytaniami do jednego portalu
SEARCH_API_DELAY_SECONDS = 1.0  # Brave: limit 50 zapytan/s, ale budzet to koszt/miesiac, nie predkosc
BROWSER_DELAY_SECONDS = 3.0  # wolniej dla przegladarki — mniejszy slad, mniej ryzyka bana

OLX_OFFERS_URL = "https://www.olx.pl/api/v1/offers/"
_STOPWORD_TOKENS = {"ul", "ul.", "al", "al.", "os", "os.", "pl", "pl."}

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_API_KEY_ENV_VAR = "BRAVE_SEARCH_API_KEY"

# Domena portalu -> jego klucz w config.yaml (portal_check.portale/browser_portals).
# Uzywane do rozpoznania, KTORY portal odpowiada danemu URL-owi w wynikach search API.
_PORTAL_DOMAINS = {
    "otodom": "otodom.pl",
    "olx": "olx.pl",
    "rynekpierwotny": "rynekpierwotny.pl",
    "morizon": "morizon.pl",
    "gratka": "gratka.pl",
    "domiporta": "domiporta.pl",
}

# Domyslne szablony URL wyszukiwania dla backendu browser. {query} zostanie
# podmienione na URL-encoded "ulica, miejscowosc". Nadpisywalne w config.yaml
# (portal_check.search_url_templates) — bo formaty URL portali sie zmieniaja.
DEFAULT_SEARCH_URL_TEMPLATES = {
    "otodom": "https://www.otodom.pl/pl/wyniki/sprzedaz/dom/cala-polska?ownerTypeSingleSelect=ALL&by=LATEST&direction=DESC&search=%5Bfilter_search%5D={query}",
    "rynekpierwotny": "https://rynekpierwotny.pl/s/?phrase={query}",
    "morizon": "https://www.morizon.pl/do-kupienia/?ps%5Bquery%5D={query}",
    "gratka": "https://gratka.pl/nieruchomosci?keyword={query}",
    "domiporta": "https://www.domiporta.pl/nieruchomosci/sprzedam?Keywords={query}",
}


@dataclass
class PortalPresence:
    found_on: list[str] = field(default_factory=list)  # np. ["otodom", "olx"]
    matches: dict[str, str] = field(default_factory=dict)  # portal -> URL konkretnego ogloszenia
    confirmed_by_investor: list[str] = field(default_factory=list)  # portale, gdzie nazwa inwestora TEZ sie zgadza
    confidence: str = "low"   # "high" gdy confirmed_by_investor niepuste, inaczej "low" (samo dopasowanie adresu)
    checked_at: str | None = None

    @property
    def is_present_anywhere(self) -> bool:
        return len(self.found_on) > 0


def _norm(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower()


def _query_tokens(query: str) -> list[str]:
    """Rozbija 'ulica, miejscowosc' na tokeny do sprawdzenia trafnosci wyniku —
    pomija krotkie prefiksy typu 'ul.'/'al.' i zbyt krotkie fragmenty."""
    raw_tokens = re.split(r"[,\s]+", query)
    return [t for t in raw_tokens if t and _norm(t).rstrip(".") not in _STOPWORD_TOKENS and len(t) > 2]


def _text_matches_all_tokens(haystack: str, tokens: list[str]) -> bool:
    h = _norm(haystack)
    return all(_norm(t) in h for t in tokens)


# Wzorce URL rozrozniajace KONKRETNE OGLOSZENIE od strony wynikow/kategorii —
# zweryfikowane na realnych URL-ach z tego pliku (patrz commit). Bez tego
# wyszukiwarka (Brave) czasem indeksuje strone kategorii portalu (np.
# "gratka.pl/nieruchomosci/mieszkania/karczew/ul-lesna/sprzedaz" — lista
# WSZYSTKICH mieszkan na tej ulicy) jako "trafienie", co wyglada jak konkretna
# oferta, a jest tylko strona wyszukiwania.
_LISTING_URL_PATTERNS = {
    "otodom": re.compile(r"/oferta/"),
    "olx": re.compile(r"/d/oferta/"),
    "rynekpierwotny": re.compile(r"/oferty/"),
    "morizon": re.compile(r"/oferta/"),
    "gratka": re.compile(r"/ob/\d+"),
    "domiporta": re.compile(r"/\d{6,}/?$"),
}


def _is_individual_listing(portal: str, url: str) -> bool:
    pattern = _LISTING_URL_PATTERNS.get(portal)
    if pattern is None:
        return True  # nieznany portal — nie odrzucaj na tej podstawie
    return bool(pattern.search(urllib.parse.urlparse(url).path))


# Ogloszenia WYNAJMU — nasze leady to pozwolenia na BUDOWE (nowe budynki na
# SPRZEDAZ), wiec ogloszenie o wynajem NIGDY nie jest ta inwestycja (to zwykle
# istniejacy budynek wynajmowany przy tej samej ulicy). Zweryfikowane na zywo
# (22.07.2026): OLX ma osobna kategorie "Domy do wynajecia" (cat_id 25), a
# Morizon URL-e wynajmu maja "/oferta/wynajem-...". Filtrujemy je TWARDO,
# zanim staną się dopasowaniem — to najczystszy sygnal "to nie nasz lead".
# "wynaj" pokrywa: wynajem, wynajęcia (wynajecia), wynajmę (wynajme), na wynajem.
_RENTAL_MARKERS = ("wynaj", "do-wynajecia", "na-wynajem")


def _is_rental(url: str, title: str = "") -> bool:
    hay = _norm(f"{url} {title}")
    return any(marker in hay for marker in _RENTAL_MARKERS)


# Typ nieruchomosci: dla zabudowy jednorodzinnej (szeregowa/blizniacza/
# wolnostojaca) szukamy DOMU, nie mieszkania — Gratka/Domiporta/Morizon maja
# osobne kategorie "dom" i "mieszkanie", a dopasowanie samej ulicy+miejscowosci
# bez tego rozroznienia lapalo np. kategorie "mieszkania" dla leada opisujacego
# budowe domu. Dla zabudowy wielorodzinnej (budynek z wieloma mieszkaniami)
# odwrotnie — szukamy mieszkania, bo to indywidualne lokale sa wystawiane.
#
# Odmiany wyrazow WPROST (nie \bdom bez konca granicy) — zweryfikowane na
# zywo, ze samo \bdom (bez konca granicy slowa) falszywie dopasowuje sie do
# "domiporta" w tytulach typu "Sprzedam mieszkanie ... - Domiporta.pl", mimo
# ze ogloszenie jest mieszkaniem, nie domem.
_HOUSE_TYPE_WORDS = [
    "dom", "domu", "domem", "domek", "domku", "domki",
    "blizniak", "blizniaka", "blizniaku",
    "szeregowiec", "szeregowca", "szeregowcu",
    "segment", "segmentu", "segmencie",
    "willa", "willi",
]
_APARTMENT_TYPE_WORDS = [
    "mieszkanie", "mieszkania", "mieszkaniu", "mieszkaniem",
    "kawalerka", "kawalerke", "kawalerki",
    "apartament", "apartamentu", "apartamencie",
]


def expected_property_type(kategoria_obiektu: str | None) -> str:
    v = _norm(kategoria_obiektu or "")
    return "mieszkanie" if "wielorodzinn" in v else "dom"


def _has_type_word(text: str, words: list[str]) -> bool:
    # \b...\b (GRANICA Z OBU STRON) — nie samo \b... — inaczej "dom" fałszywie
    # pasuje do "domiporta" (patrz komentarz przy _HOUSE_TYPE_WORDS wyzej)
    v = _norm(text)
    return any(re.search(rf"\b{w}\b", v) for w in words)


def _matches_property_type(title: str, blob: str, expected_type: str | None) -> bool:
    """Gdy expected_type jest None (nie znamy typu zabudowy), nie odrzucamy —
    lepiej przepuscic niz zgubic trafienie z powodu brakujacej informacji.

    Sprawdzamy TYTUL jako pierwszy, autorytatywny sygnal — dopiero gdy tytul
    nie wspomina zadnego typu (niejednoznaczny), spadamy do calego blobu
    (tytul+opis+url). Zweryfikowane na zywo, ze samo sprawdzanie calego blobu
    nie wystarczy: ogolny opis SEO strony Otodom ("mieszkania, domy, dzialki,
    lokale uzytkowe...") wymienia WSZYSTKIE kategorie portalu jako tekst
    nawigacyjny i falszywie pasowalby do kazdego expected_type, mimo ze tytul
    tej samej oferty jednoznacznie mowil "mieszkanie na sprzedaz"."""
    if not expected_type:
        return True
    house_in_title = _has_type_word(title, _HOUSE_TYPE_WORDS)
    apartment_in_title = _has_type_word(title, _APARTMENT_TYPE_WORDS)
    if house_in_title or apartment_in_title:
        words = _HOUSE_TYPE_WORDS if expected_type == "dom" else _APARTMENT_TYPE_WORDS
        return _has_type_word(title, words)
    words = _HOUSE_TYPE_WORDS if expected_type == "dom" else _APARTMENT_TYPE_WORDS
    return _has_type_word(blob, words)


# Formy prawne odcinane z nazwy inwestora przed cross-checkiem — zostaje
# "rdzen" nazwy (np. "Nowak Budownictwo" z "Nowak Budownictwo Sp. z o.o.").
_LEGAL_FORM_RE = re.compile(
    r"\bsp\.?\s*z\s*o\.?\s*o\.?\b|\bspolka\s+z\s+ograniczona\s+odpowiedzialnoscia\b"
    r"|\bs\.?a\.?\b|\bsp\.?\s*k\.?\b|\bspolka\s+komandytowa\b|\bspolka\s+jawna\b|\bs\.?c\.?\b",
    re.IGNORECASE,
)


def investor_core_name(investor: str | None) -> str | None:
    """Nazwa inwestora bez formy prawnej — do cross-checku z tekstem ogloszenia.
    None gdy po odcieciu formy prawnej nic sensownego nie zostaje (np. sama
    'Sp. z o.o.' bez nazwy wlasciwej, albo brak inwestora w RWDZ w ogole)."""
    if not investor:
        return None
    v = _norm(investor)
    v = _LEGAL_FORM_RE.sub(" ", v)
    v = re.sub(r"[.,\"'()]", " ", v)
    tokens = [t for t in v.split() if len(t) > 2]
    return " ".join(tokens) if tokens else None


def _matches_investor(text: str, investor_core: str | None) -> bool:
    """CELOWO NIE uzywane jako filtr odrzucajacy (patrz docstring modulu:
    'deweloper sprzedaje pod nazwa projektu/osiedla, nie nazwa spolki' — brak
    dopasowania nazwy inwestora w ogloszeniu jest NORMALNY, nie jest sygnalem
    zlego dopasowania). Uzywane WYLACZNIE do podniesienia confidence z "low"
    (samo dopasowanie adresu) do "high" (adres + nazwa inwestora), gdy nazwa
    faktycznie sie pojawia — np. deweloper podpisuje sie wlasna marka w opisie."""
    if not investor_core:
        return False
    v = _norm(text)
    tokens = investor_core.split()
    return bool(tokens) and all(t in v for t in tokens)


@dataclass
class _Match:
    url: str
    investor_confirmed: bool = False
    # surowa oferta OLX z /api/v1/offers (params, map, created_time, business) —
    # przechwycona W MOMENCIE dopasowania, zeby weryfikacja (src/verify.py) nie
    # musiala niczego pobierac ponownie. Dla innych backendow None.
    olx_offer: dict | None = None


# --------------------------- BACKEND SEARCH API ---------------------------

def _portal_for_url(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc.lower()
    for portal, domain in _PORTAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return portal
    return None


def _check_via_search_api(
    query: str,
    portals: list[str],
    api_key: str,
    expected_type: str | None = None,
    investor_core: str | None = None,
) -> dict[str, _Match]:
    """Jedno zapytanie do Brave Search API (oficjalne, platne API wyszukiwarki —
    NIE scraping) z filtrem site: pokrywa WSZYSTKIE portale naraz, wlacznie z
    Otodom. Endpoint i format zweryfikowane na zywo:
      GET https://api.search.brave.com/res/v1/web/search
      naglowek: X-Subscription-Token: <klucz>
    Rejestracja klucza: https://api-dashboard.search.brave.com (plan z
    darmowymi kredytami co miesiac — patrz README). Zwraca {portal: _Match}
    pierwszego trafionego ogloszenia na kazdym portalu, gdzie tytul+opis+url
    zawieraja WSZYSTKIE tokeny adresu (odporne na luzne dopasowania
    wyszukiwarki — zweryfikowane: fraza z Wikipedii bez tokenu ulicy jest
    poprawnie odrzucana), URL wskazuje na KONKRETNE ogloszenie a nie strone
    kategorii/wynikow (zweryfikowane: strona kategorii "mieszkania" na danej
    ulicy bez tego bylaby falszywie uznana za trafienie), i typ nieruchomosci
    zgadza sie z oczekiwanym (dom vs mieszkanie, patrz expected_property_type).
    _Match.investor_confirmed = True gdy nazwa inwestora (bez formy prawnej)
    TEZ pojawia sie w tytule/opisie — patrz _matches_investor."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return {}

    site_filter = " OR ".join(f"site:{_PORTAL_DOMAINS[p]}" for p in portals if p in _PORTAL_DOMAINS)
    if not site_filter:
        return {}
    phrase = " ".join(f'"{t}"' for t in tokens)
    q = f"{phrase} ({site_filter})"

    resp = requests.get(
        BRAVE_SEARCH_URL,
        params={"q": q, "count": 20},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json().get("web", {}).get("results", [])

    matches: dict[str, _Match] = {}
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        if not url:
            continue
        blob = f"{title} {r.get('description', '')} {url}"
        if not _text_matches_all_tokens(blob, tokens):
            continue
        portal = _portal_for_url(url)
        if not portal or portal in matches:
            continue
        if not _is_individual_listing(portal, url):
            continue
        if _is_rental(url, title):  # wynajem — nigdy nie nasza inwestycja z pozwolenia
            continue
        if not _matches_property_type(title, blob, expected_type):
            continue
        matches[portal] = _Match(url=url, investor_confirmed=_matches_investor(blob, investor_core))
    return matches


# ----------------------------- BACKEND HTTP -----------------------------

def _check_olx(query: str, expected_type: str | None = None, investor_core: str | None = None) -> _Match | None:
    """OLX — wewnetrzny endpoint JSON /api/v1/offers (dozwolony w robots.txt).
    Zweryfikowane na zywo: zwraca trafne oferty dla 'ulica, miejscowosc'.
    Zwraca _Match pierwszego trafionego ogloszenia, albo None.

    WAZNE: endpoint przeszukuje CALY OLX (odziez, elektronika, praca...), nie
    tylko nieruchomosci — zlapane na zywo: zapytanie "Kozacka, Marki" trafilo
    w bluze o nazwie "Kozacka" wystawiona z Marek, bo tokeny (nazwa produktu +
    tag lokalizacji OLX) pasowaly tekstowo. Kazda oferta ma pole
    category.type — nieruchomosci maja "real_estate" — wiec filtrujemy po
    tym PRZED dopasowaniem tokenow, nie tylko po tekscie. Dodatkowo filtrujemy
    po typie nieruchomosci (dom vs mieszkanie, patrz expected_property_type) —
    endpoint /api/v1/offers zwraca oferty z calego OLX niezaleznie od typu."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return None
    resp = requests.get(
        OLX_OFFERS_URL,
        params={"query": query, "limit": 20},
        headers={"User-Agent": "dev-scout/0.1"},
        timeout=15,
    )
    resp.raise_for_status()
    offers = resp.json().get("data", [])
    for offer in offers:
        if offer.get("category", {}).get("type") != "real_estate":
            continue
        url = offer.get("url") or ""
        title = offer.get("title", "")
        if not url or _is_rental(url, title):  # pusty URL / wynajem (OLX kat. 25) — odrzuc
            continue
        blob = f"{title} {offer.get('description', '')} {url}"
        if _text_matches_all_tokens(blob, tokens) and _matches_property_type(title, blob, expected_type):
            return _Match(
                url=url,
                investor_confirmed=_matches_investor(blob, investor_core),
                olx_offer={k: offer.get(k) for k in ("params", "map", "created_time", "business")},
            )
    return None


# --------------------------- BACKEND BROWSER ---------------------------

_playwright_ctx = None  # leniwie inicjowany (browser, context) — zeby nie startowac Chromium bez potrzeby
_browser_unavailable = False  # gdy raz sie nie uda, nie probuj (i nie spamuj logu) przy kazdym leadzie


def _get_browser_page(cfg: dict):
    """Leniwie startuje Chromium (Playwright) i zwraca strone. Zwraca None, gdy
    Playwright/Chromium nie jest dostepny — wtedy backend browser jest pomijany
    bez wywalania calego enrichu. Nieudany start zapamietujemy, zeby nie probowac
    (i nie logowac tracebacka) przy kazdym kolejnym leadzie."""
    global _playwright_ctx, _browser_unavailable
    if _browser_unavailable:
        return None
    if _playwright_ctx is not None:
        _, ctx = _playwright_ctx
        return ctx.new_page()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Backend browser wlaczony, ale brak pakietu playwright (pip install playwright). Pomijam.")
        _browser_unavailable = True
        return None

    try:
        pw = sync_playwright().start()
        launch_kwargs = {
            "headless": cfg.get("browser_headless", True),
            "args": ["--no-sandbox"],
        }
        # opcjonalna sciezka do Chromium (np. w srodowiskach z preinstalowana przegladarka)
        chrome_path = os.environ.get("DEV_SCOUT_CHROME_PATH")
        if chrome_path:
            launch_kwargs["executable_path"] = chrome_path
        # opcjonalne proxy (na maszynie Adama zwykle brak — wtedy pomijamy)
        proxy = os.environ.get("HTTPS_PROXY")
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            locale="pl-PL",
        )
        _playwright_ctx = (browser, context)
        return context.new_page()
    except Exception as e:
        log.warning("Nie udalo sie uruchomic Chromium/Playwright (%s) — pomijam backend browser. "
                    "Uruchom z maszyny z realnym internetem i przegladarka.", type(e).__name__)
        _browser_unavailable = True
        return None


def _check_via_browser(
    portal: str, query: str, cfg: dict, expected_type: str | None = None, investor_core: str | None = None
) -> _Match | None:
    """Generyczny checker: laduje URL wyszukiwania portalu w prawdziwej
    przegladarce, czeka na wyrenderowanie i sprawdza, czy w tekscie strony
    pojawiaja sie WSZYSTKIE tokeny adresu (ulica + miejscowosc) ORAZ slowo
    zgodne z oczekiwanym typem nieruchomosci (dom vs mieszkanie). Podejscie
    'tekst na wyrenderowanej stronie' jest odporne na zmiany layoutu — nie
    zalezy od kruchych selektorow CSS. Zwraca _Match ze STRONA WYNIKOW jako url
    (nie pojedynczego ogloszenia — wyodrebnienie konkretnego linku z
    wyrenderowanego tekstu wymagaloby parsowania DOM, a ten backend to i tak
    tylko fallback bez klucza search API) gdy dopasowanie znalezione, inaczej
    None."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return None

    templates = {**DEFAULT_SEARCH_URL_TEMPLATES, **cfg.get("search_url_templates", {})}
    template = templates.get(portal)
    if not template:
        return None

    url = template.replace("{query}", urllib.parse.quote(query))
    page = _get_browser_page(cfg)
    if page is None:
        return None
    try:
        page.goto(url, timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)  # daj JS-owi dorenderowac wyniki
        content = page.content()
        # brak oddzielnego tytulu przy calej wyrenderowanej stronie — przekazujemy
        # ten sam tekst jako "tytul" i "blob" (ten backend to i tak tylko fallback)
        matched = _text_matches_all_tokens(content, tokens) and _matches_property_type(content, content, expected_type)
        return _Match(url=url, investor_confirmed=_matches_investor(content, investor_core)) if matched else None
    except Exception:
        log.warning("Backend browser: blad przy %s (%s)", portal, url, exc_info=True)
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def close_browser() -> None:
    """Zamyka Chromium jesli byl uruchomiony. Wolaj na koncu enrichu."""
    global _playwright_ctx
    if _playwright_ctx is not None:
        browser, _ = _playwright_ctx
        try:
            browser.close()
        except Exception:
            pass
        _playwright_ctx = None


# ------------------------------ DYSPOZYTOR ------------------------------

def check_portals(
    query: str, portal_cfg: dict, property_type: str | None = None, investor_name: str | None = None
) -> tuple[PortalPresence, dict[str, _Match]]:
    """query = najlepiej 'ulica, miejscowosc' (patrz docstring modulu).
    portal_cfg = caly slownik cfg['portal_check'].
    property_type = "dom" albo "mieszkanie" (patrz expected_property_type) —
    odrzuca trafienia niewlasciwego typu nieruchomosci (np. kategoria
    "mieszkania" na portalu, gdy szukamy domu jednorodzinnego) i strony
    kategorii/wynikow zamiast konkretnych ogloszen. None = nie filtruj po
    typie (lepiej przepuscic niz zgubic trafienie z powodu braku informacji).
    investor_name = nazwa inwestora z RWDZ (surowa, z forma prawna) — NIE
    filtruje trafien (patrz docstring _matches_investor), tylko podnosi
    confidence na "high" i dopisuje portal do confirmed_by_investor, gdy nazwa
    (bez formy prawnej) faktycznie pojawia sie w ogloszeniu — cross-check
    "czy ten lead naprawde jest ta sama inwestycja, nie tylko ten sam adres".

    Kolejnosc backendow (patrz docstring modulu): search API (jesli jest
    klucz) -> zawsze OLX http (za darmo, niezaleznie od search API) ->
    browser (tylko gdy BRAK klucza search API i enable_browser=true). Kazdy
    checker jest w try/except: awaria jednego backendu/portalu nie blokuje
    reszty.

    OLX jest CELOWO wykluczony z zapytania do search API (patrz
    all_wanted_portals nizej) — Brave nie ma dostepu do pola category.type
    ktore ma OLX-owy JSON, wiec dopasowanie tekstowe samo w sobie fałszywie
    lapie NIE-nieruchomosciowe ogloszenia OLX (zweryfikowane na zywo:
    "Kozacka, Marki" zlapalo bluze o nazwie "Kozacka" wystawiona z Marek).
    _check_olx() nizej ma dostep do category.type i filtruje po nim —
    zostawiamy WYLACZNIE jemu odpowiedzialnosc za OLX."""
    http_portals = portal_cfg.get("portale", [])
    browser_portals_cfg = portal_cfg.get("browser_portals", [])
    all_wanted_portals = [p for p in dict.fromkeys(http_portals + browser_portals_cfg) if p != "olx"]
    investor_core = investor_core_name(investor_name)

    matches: dict[str, _Match] = {}

    api_key = os.environ.get(BRAVE_API_KEY_ENV_VAR)
    if api_key and all_wanted_portals:
        try:
            matches.update(_check_via_search_api(query, all_wanted_portals, api_key, property_type, investor_core))
        except Exception:
            log.warning("Search API check nie powiodl sie dla %r", query, exc_info=True)
        time.sleep(SEARCH_API_DELAY_SECONDS)

    if "olx" in http_portals and "olx" not in matches:
        try:
            olx_match = _check_olx(query, property_type, investor_core)
            if olx_match:
                matches["olx"] = olx_match
        except Exception:
            log.warning("HTTP check olx nie powiodl sie dla %r", query, exc_info=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    # browser tylko jako fallback bez klucza search API — z kluczem search API
    # i tak pokrywa te same portale, wiec uruchamianie Chromium bylo by
    # zbedne (patrz docstring modulu)
    browser_portals = portal_cfg.get("browser_portals", []) if (portal_cfg.get("enable_browser") and not api_key) else []
    for portal in browser_portals:
        if portal in matches:
            continue
        try:
            browser_match = _check_via_browser(portal, query, portal_cfg, property_type, investor_core)
            if browser_match:
                matches[portal] = browser_match
        except Exception:
            log.warning("Browser check %s nie powiodl sie dla %r", portal, query, exc_info=True)
        time.sleep(BROWSER_DELAY_SECONDS)

    confirmed_by_investor = sorted(p for p, m in matches.items() if m.investor_confirmed)
    presence = PortalPresence(
        found_on=sorted(matches.keys()),
        matches={p: m.url for p, m in matches.items()},
        confirmed_by_investor=confirmed_by_investor,
        confidence="high" if confirmed_by_investor else "low",
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    # surowe _Match (z olx_offer itd.) — dla weryfikacji w src/verify.py;
    # celowo POZA PortalPresence, zeby presence.__dict__ zostal JSON-serializowalny
    return presence, matches
