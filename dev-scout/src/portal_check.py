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
    confidence: str = "low"   # "low" = dopasowanie po adresie, "high" = adres + nazwa firmy
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


# --------------------------- BACKEND SEARCH API ---------------------------

def _portal_for_url(url: str) -> str | None:
    host = urllib.parse.urlparse(url).netloc.lower()
    for portal, domain in _PORTAL_DOMAINS.items():
        if host == domain or host.endswith("." + domain):
            return portal
    return None


def _check_via_search_api(query: str, portals: list[str], api_key: str) -> list[str]:
    """Jedno zapytanie do Brave Search API (oficjalne, platne API wyszukiwarki —
    NIE scraping) z filtrem site: pokrywa WSZYSTKIE portale naraz, wlacznie z
    Otodom. Endpoint i format zweryfikowane na zywo:
      GET https://api.search.brave.com/res/v1/web/search
      naglowek: X-Subscription-Token: <klucz>
    Rejestracja klucza: https://api-dashboard.search.brave.com (plan z
    darmowymi kredytami co miesiac — patrz README). Zwraca liste portali,
    na ktorych ZNALEZIONO oferte pasujaca do WSZYSTKICH tokenow adresu
    (odporne na falszywe trafienia z luznego dopasowania wyszukiwarki)."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return []

    site_filter = " OR ".join(f"site:{_PORTAL_DOMAINS[p]}" for p in portals if p in _PORTAL_DOMAINS)
    if not site_filter:
        return []
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

    found: set[str] = set()
    for r in results:
        url = r.get("url", "")
        blob = f"{r.get('title', '')} {r.get('description', '')} {url}"
        if not _text_matches_all_tokens(blob, tokens):
            continue
        portal = _portal_for_url(url)
        if portal:
            found.add(portal)
    return sorted(found)


# ----------------------------- BACKEND HTTP -----------------------------

def _check_olx(query: str) -> bool:
    """OLX — wewnetrzny endpoint JSON /api/v1/offers (dozwolony w robots.txt).
    Zweryfikowane na zywo: zwraca trafne oferty dla 'ulica, miejscowosc'."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return False
    resp = requests.get(
        OLX_OFFERS_URL,
        params={"query": query, "limit": 20},
        headers={"User-Agent": "dev-scout/0.1"},
        timeout=15,
    )
    resp.raise_for_status()
    offers = resp.json().get("data", [])
    for offer in offers:
        blob = f"{offer.get('title','')} {offer.get('description','')} {offer.get('url','')}"
        if _text_matches_all_tokens(blob, tokens):
            return True
    return False


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


def _check_via_browser(portal: str, query: str, cfg: dict) -> bool:
    """Generyczny checker: laduje URL wyszukiwania portalu w prawdziwej
    przegladarce, czeka na wyrenderowanie i sprawdza, czy w tekscie strony
    pojawiaja sie WSZYSTKIE tokeny adresu (ulica + miejscowosc). Podejscie
    'tekst na wyrenderowanej stronie' jest odporne na zmiany layoutu — nie
    zalezy od kruchych selektorow CSS."""
    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return False

    templates = {**DEFAULT_SEARCH_URL_TEMPLATES, **cfg.get("search_url_templates", {})}
    template = templates.get(portal)
    if not template:
        return False

    url = template.replace("{query}", urllib.parse.quote(query))
    page = _get_browser_page(cfg)
    if page is None:
        return False
    try:
        page.goto(url, timeout=35000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)  # daj JS-owi dorenderowac wyniki
        content = page.content()
        return _text_matches_all_tokens(content, tokens)
    except Exception:
        log.warning("Backend browser: blad przy %s (%s)", portal, url, exc_info=True)
        return False
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

def check_portals(query: str, portal_cfg: dict) -> PortalPresence:
    """query = najlepiej 'ulica, miejscowosc' (patrz docstring modulu).
    portal_cfg = caly slownik cfg['portal_check'].

    Kolejnosc backendow (patrz docstring modulu): search API (jesli jest
    klucz) -> zawsze OLX http (za darmo, niezaleznie od search API) ->
    browser (tylko gdy BRAK klucza search API i enable_browser=true). Kazdy
    checker jest w try/except: awaria jednego backendu/portalu nie blokuje
    reszty."""
    http_portals = portal_cfg.get("portale", [])
    all_wanted_portals = list(dict.fromkeys(http_portals + portal_cfg.get("browser_portals", [])))

    found: list[str] = []

    api_key = os.environ.get(BRAVE_API_KEY_ENV_VAR)
    if api_key and all_wanted_portals:
        try:
            found.extend(_check_via_search_api(query, all_wanted_portals, api_key))
        except Exception:
            log.warning("Search API check nie powiodl sie dla %r", query, exc_info=True)
        time.sleep(SEARCH_API_DELAY_SECONDS)

    if "olx" in http_portals and "olx" not in found:
        try:
            if _check_olx(query):
                found.append("olx")
        except Exception:
            log.warning("HTTP check olx nie powiodl sie dla %r", query, exc_info=True)
        time.sleep(REQUEST_DELAY_SECONDS)

    # browser tylko jako fallback bez klucza search API — z kluczem search API
    # i tak pokrywa te same portale, wiec uruchamianie Chromium bylo by
    # zbedne (patrz docstring modulu)
    browser_portals = portal_cfg.get("browser_portals", []) if (portal_cfg.get("enable_browser") and not api_key) else []
    for portal in browser_portals:
        if portal in found:
            continue
        try:
            if _check_via_browser(portal, query, portal_cfg):
                found.append(portal)
        except Exception:
            log.warning("Browser check %s nie powiodl sie dla %r", portal, query, exc_info=True)
        time.sleep(BROWSER_DELAY_SECONDS)

    return PortalPresence(
        found_on=found,
        confidence="low",
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
