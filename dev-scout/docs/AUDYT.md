# Audyt Dev Scout — co zmienić, żeby mieć najświeższe i najtrafniejsze leady

Stan na 22 lipca 2026, po czterech rundach pracy: (1) wdrożenie wielosygnałowej
weryfikacji dopasowań (`src/verify.py`) + raportu Excel (`tools/report_xlsx.py`),
(2) domknięcie większości znalezisk z pierwszej rundy audytu — scoring, recheck,
cache, adres pełny, testy, poprawki Excela, (3) usunięcie zakładki Dashboard
(źle się renderowała) i rozszerzenie ekstrakcji danych strukturalnych z Otodom/
OLX na pozostałe 4 portale, (4) precyzja dopasowań: twarde odrzucanie ogłoszeń
wynajmu i wygasłych/martwych linków, brak klikalnych martwych linków w Excelu.
Punkty ułożone od największego wpływu.
"✅ zrobione" = już w kodzie na tym branchu, reszta = rekomendacje.

---

## 00. Precyzja dopasowań — wynajem, martwe linki, puste linki (runda 4)

Zgłoszone przez Adama: w Excelu wciąż były (a) puste linki, (b) nieaktualne
linki, (c) linki do ogłoszeń o WYNAJEM. Zbadane na żywo i naprawione:

- ✅ **Wynajem odrzucany twardo.** Pozwolenie na budowę = nowy budynek na
  SPRZEDAŻ, więc ogłoszenie wynajmu nigdy nie jest tą inwestycją (to zwykle
  istniejący budynek wynajmowany przy tej samej ulicy). Filtr działa na 3
  poziomach: (1) `portal_check._is_rental` odrzuca kandydata już na etapie
  wyszukiwania po URL/tytule ("wynaj…"), (2) OLX ma osobną kategorię
  "Domy do wynajęcia" (cat_id 25) — łapaną tym samym filtrem, (3) Otodom ma
  autorytatywne pole `target.OfferType` (sprzedaz/wynajem) sprawdzane w
  `verify`. Zweryfikowane na żywo: lead 13861 (Radzymin), który wcześniej
  matchował ogłoszenie WYNAJMU na Morizon, po zmianie ma zero dopasowań i
  poprawnie czyta się jako CLEAN.
- ✅ **Martwe/wygasłe linki → REJECTED, nie REVIEW.** Wcześniej gdy link
  wygasł i portal przekierował poza ofertę, `verify` zwracał `None`, co
  `judge_match` traktował jak "brak danych strukturalnych" (REVIEW) — i martwy
  link nadal pokazywał się jako klikalne "ogłoszenie". Teraz zwracamy odrębny
  sygnał `dead_link` → werdykt REJECTED z powodem "ogłoszenie nieaktualne".
  Zweryfikowane na żywo: lead 813 (Jabłonna), Domiporta — link przekierował na
  stronę kategorii, poprawnie oznaczony REJECTED.
- ✅ **Brak klikalnych martwych/mylących linków w Excelu.** Kolumny per-portal
  robią klikalny link TYLKO dla dopasowań nie-REJECTED z niepustym URL-em; dla
  odrzuconych (wynajem/nieaktualne/inna nieruchomość) i pustych URL-i
  pokazujemy sam znacznik „✖ odrzucone" bez hiperłącza. Sprawdzone na próbce:
  13 zdrowych klikalnych ogłoszeń, 0 klikalnych odrzuconych.
- ✅ **Lead z samymi odrzuconymi dopasowaniami = CLEAN, nie „odrzucone".**
  Jeśli wszystko, co znaleziono, odrzucono (wynajem/martwe/inna nieruchomość),
  to z punktu widzenia leada NIC wiarygodnego nie jest na portalu — czyli
  wciąż dobry, wczesny lead. Excel pokazuje CLEAN z rozpiską, co odrzucono i
  dlaczego (spójne z `on_portal_found`, który już wcześniej pomijał REJECTED).

Pokryte testami (`tests/test_verify.py`): odrzucanie wynajmu (URL/tytuł/pole
Otodom), martwy link → REJECTED, detekcja `_is_rental`.

---

## 0. Ekstrakcja danych strukturalnych — teraz na WSZYSTKICH 6 portalach

✅ Wcześniej tylko Otodom (`__NEXT_DATA__`) i OLX (API) dawały dane
strukturalne (metraż, działka, rynek, współrzędne) do weryfikacji — pozostałe
4 portale miały tylko luźny regex na całym HTML. Zbadane na żywo (22.07.2026)
i wdrożone:
- **Domiporta**: pełny `schema.org RealEstateListing` (JSON-LD) — data
  wystawienia, cena, `itemOffered.floorSize`, precyzyjne współrzędne
  (`itemOffered.geo`). Najbogatsze źródło z czterech nowych.
- **RynekPierwotny**: `schema.org ApartmentComplex` (JSON-LD) — adres i
  precyzyjne współrzędne CAŁEJ INWESTYCJI (nie pojedynczego domu — portal z
  natury grupuje oferty per inwestycja, co akurat idealnie pasuje do tego, jak
  RWDZ też grupuje wnioski per inwestycja). `market="primary"` ustawiane na
  sztywno — to fakt o całym portalu (wyłącznie rynek pierwotny), nie zgadywanie.
- **Gratka / Morizon**: brak własnego JSON-a dla POJEDYNCZEJ oferty — ich
  JSON-LD/Nuxt payload na stronie oferty niesie dane "podobnych ofert"
  wyświetlanych obok, NIE oferty którą się ogląda (pułapka złapana na żywo:
  pierwsze podejście wyciągnęłoby dane zupełnie INNEJ nieruchomości). Zamiast
  tego: uniwersalny meta-opis SEO (`<meta property="og:description">`) w
  formacie „NNN m² (pow. działki NNN m²)" — zweryfikowany jako identyczny
  tekst dla tej samej nieruchomości wystawionej na obu portalach (wspólny
  właściciel, Grupa Domodi). Bez współrzędnych z tego źródła.

**Bonusowe znalezisko przy testowaniu (realny bug, nie hipotetyczny):** oferty
pod zapamiętanymi URL-ami potrafią WYGASNĄĆ, a portal wtedy CICHO
PRZEKIEROWUJE na stronę kategorii zamiast zwrócić 404. Złapane na żywo 2×
(Gratka i Morizon) na URL-ach z wcześniejszej sesji — bez zabezpieczenia
wyciągnęlibyśmy dane zupełnie przypadkowej, INNEJ oferty z tej kategorii i
podpisali je pod naszym leadem. Naprawione: `fetch_html_facts`/
`fetch_otodom_facts` sprawdzają teraz, że finalny URL (po ew. przekierowaniu)
nadal wygląda jak konkretne ogłoszenie, zanim zaufają jakimkolwiek danym.
Złapane też żywo podczas właściwego testu na 20 leadach (Domiporta
przekierowała `/nieruchomosci/sprzedam-dom-.../151582529` na
`/nieruchomosci/sprzedam` — zabezpieczenie zadziałało poprawnie).

Pokryte testami (`tests/test_verify.py`): parsowanie meta-opisu (w tym wariant
z NBSP jako separatorem tysięcy), wymóg zgodności URL-a dla Domiporta/
RynekPierwotny.

---

## 0b. Arkusz Dashboard — usunięty (źle się renderował)

❌→✅ Usunięty na wyraźne życzenie — wykresy/KPI wyglądały fatalnie w
renderowaniu Excela mimo wcześniejszej naprawy buga z `visible_cells_only`.
Raport ma teraz dwie zakładki: Leady (dane) i Legenda (metodologia). Jeśli
w przyszłości wrócimy do pomysłu wizualizacji, warto rozważyć osobny plik/
narzędzie zamiast wykresów natywnych Excela — one najwyraźniej nie renderują
się dobrze w używanym przez Adama czytniku plików.

---

## 1. Świeżość danych — jak mieć „najnowsze" informacje

| Co | Status | Uwagi |
|---|---|---|
| **Cykliczne uruchamianie (cron dzienny)** | ❌ nadal do zrobienia (zadanie 4 z CLAUDE.md) | RWDZ/GUNB aktualizuje plik co noc. Tego nie da się zrobić z tej sesji — to wymaga crontaba na TRWAŁEJ maszynie Adama (ten sandbox jest efemeryczny). Gotowa linia crona jest w `CLAUDE.md`. |
| **Filtr „tylko od 2024"** | ✅ zrobione | `date_filter.min_data` w config. |
| **Re-check portali co N dni** | ✅ **zrobione** — `src/main.py::step_recheck` + komenda `python -m src.main recheck` | Cofa `scored`→`new` dla leadów sprawdzonych, ale nie znalezionych (`on_portal_found` 0/NULL), starszych niż `recheck_after_days`. Leady już potwierdzone (`on_portal_found=1`) NIE są cofane — zgodnie z CLAUDE.md ("nie usuwaj leada tylko dlatego, że się pojawił"). Przetestowane na żywo: 9/20 leadów (te "czyste") poprawnie cofnięte, 11/20 (znalezione) poprawnie pozostawione. Wołać PRZED `enrich` w cyklu cron. |
| **CEIDG endpoint `/zmiana`** | do rozważenia | Bez zmian. |

---

## 2. Weryfikacja dopasowań lead↔ogłoszenie

✅ **`src/verify.py`** — geometria działki (ULDK), rynek pierwotny/wtórny, wiek
ogłoszenia vs data wniosku, metraż vs kubatura, działka vs ewidencja gruntów,
kategoria właściciela działki, seryjność inwestora. Werdykt
CONFIRMED/LIKELY/REVIEW/REJECTED + powody w `verify_json` i w kolumnie
"Uzasadnienie werdyktu" w Excelu.

**Naprawione w tej rundzie:**
- ✅ **Martwa strefa dystansu 700 m–2 km** — realny przypadek (Brwinów, 1,82 km)
  nie miał ŻADNEJ gałęzi kodu obsługującej ten zakres, sygnał geograficzny
  znikał całkowicie z powodów werdyktu. Teraz ten zakres jawnie obniża ocenę
  i zawsze zostawia powód w Excelu. Pokryte testem regresji
  (`tests/test_verify.py::test_judge_match_dubious_distance_zone_not_silently_dropped`).

**Wciąż otwarte ograniczenia (nie do rozwiązania bez dalszej pracy):**
- Gratka/Morizon nadal bez współrzędnych (patrz punkt 0) — meta-opis SEO daje
  metraż/działkę, ale nie geometrię, więc dla dopasowań TYLKO na tych dwóch
  portalach werdykt rzadko dojdzie do CONFIRMED (brak najsilniejszego sygnału).
- KIEG WMS czasem nie zwraca danych (na próbce 20 leadów ~4 miały
  `parcel_owner_group=None` mimo poprawnego numeru działki) — przyczyna
  nieznana, do zbadania jeśli ten sygnał ma być kluczowy.
- Kalibracja widełek kubatura→metraż (÷4.0…÷5.5) oparta o garść realnych par —
  wystarczające do wykrycia rażących rozjazdów, ale warto przeliczyć po
  zebraniu większej próby potwierdzonych dopasowań.
- Seryjność inwestora to dopasowanie tekstowe (`_investor_key` w `verify.py`)
  po znormalizowanej nazwie — literówki/nietypowe skróty nazwy spółki mogą się
  nie połączyć w jeden licznik.

---

## 3. Scoring — teraz korzysta z weryfikacji (był to największy gap)

✅ **Naprawione.** `src/scoring.py::compute_score` czyta teraz `lead_verdict`,
`investor_serial_count`, `parcel_owner_group` (przekazywane z `verify_json`
w `main.py::step_score`) i trzy nowe wagi w `config.yaml`:
- `kara_potwierdzone_na_portalu` (30 pkt, odejmowane) — werdykt CONFIRMED =
  inwestycja już się reklamuje, czyli przeciwieństwo przewagi "zanim zaczną
  marketing", która jest sensem narzędzia.
- `seryjny_inwestor` (15 pkt) — inwestor ma ≥ `verify.serial_investor_min`
  wniosków w RWDZ.
- `dzialka_spolki` (10 pkt) — właściciel działki (ewidencja gruntów) to spółka
  prawa handlowego; działa NIEZALEŻNIE od tego, czy RWDZ ma wypełnioną nazwę
  inwestora (kluczowe dla ~88% leadów bez tej nazwy).

**Uwaga, doprecyzowanie względem poprzedniej wersji audytu:** wcześniejszy
zapis "REJECTED i CONFIRMED dostają identyczny wpływ na scoring" był
nieprecyzyjny — `on_portal_found` w `main.py` już wcześniej filtrował
dopasowania REJECTED (nie liczyły się jako "znaleziono"). Prawdziwą luką był
brak rozróżnienia CONFIRMED/LIKELY/REVIEW między sobą i brak wykorzystania
`investor_serial_count`/`parcel_owner_group` — to jest teraz naprawione.

**Bonus-bug znaleziony przy wdrażaniu:** `kara_potwierdzone_na_portalu` mogła
zejść poniżej 0 (zweryfikowane na żywo: realny lead z werdyktem CONFIRMED
wyszedł ze score -5), łamiąc udokumentowaną skalę 0-100. Naprawione —
`compute_score` ma teraz `max(0, min(score, 100))`.

---

## 4. Adres pełny z RWDZ — NOWA funkcja (na życzenie Adama)

✅ RWDZ dzieli nazwę ulicy na dwie kolumny (`ulica` = człon główny/nazwisko,
`ulica_dalej` = imię/tytuł — zweryfikowane na 30 realnych przykładach, np.
`ulica="Piłsudskiego"` + `ulica_dalej="Józefa "` → pełna nazwa "Józefa
Piłsudskiego"), plus osobną kolumnę `nr_domu`. Wcześniej parser brał tylko
`ulica`, gubiąc zarówno numer domu, jak i pierwszy człon nazwy ulicy.

Teraz: `rwdz_parse.compose_street_name()` składa pełną nazwę, `numer_domu`
trafia do bazy, a `main.py::step_enrich` liczy `adres_pelny` — pełny adres
pocztowy gdy RWDZ ma ulicę+numer, samą ulicę gdy brak numeru, albo ulicę
ODZYSKANĄ z lokalizacji działki (oznaczoną jawnie jako "przybliżony") gdy RWDZ
w ogóle nie ma ulicy. Widoczne w Excelu jako kolumna "Adres (pełny)" + link do
Google Maps (kolumna "Mapa") — Adam może teraz SAM zlokalizować i zweryfikować
każdą inwestycję niezależnie od wyniku portal_check/verify.

---

## 5. Cache trwały dla zapytań sieciowych — NOWE (`src/geo_cache.py`)

✅ Tabela `geo_cache` w tej samej bazie SQLite, keyowana po numerze działki
(ULDK centroid, ULDK+KIEG ewidencja) albo po znormalizowanym adresie
(Nominatim geokodowanie, odwrotne geokodowanie). Bez tego każde ponowne
`enrich` na tych samych leadach (re-check, powtórne testy — co się w tej
sesji zdarzało wielokrotnie) odpytywało te same zewnętrzne API od nowa.
Cache'owane są tylko UDANE odpowiedzi (brak cache'owania negatywnego), żeby
chwilowa awaria/literówka w RWDZ nie blokowała leada na stałe.

---

## 6. Testy automatyczne — NOWE, pierwszy krok domknięty

✅ `tests/test_filters.py` (17 testów: dopasowanie gmin/typu zabudowy/dat,
ekstrakcja liczby budynków, kompozycja adresu, oraz **test end-to-end na
`sample_test.csv`** — parse+normalize+filter na pełnym pliku, nie tylko
pojedynczych funkcjach) + `tests/test_verify.py` (12 testów: kalibracja
kubatury, cross-check inwestora, geometria punkt-w-wielokącie, werdykty
CONFIRMED/REJECTED/REVIEW na zamockowanych `ListingFacts`, w tym regresja na
martwą strefę dystansu z punktu 2). Razem 29 testów, bez sieci, `python -m
pytest tests/ -v`.

**Naprawiony przy okazji:** `data/raw/sample_test.csv` był martwym kanarkiem —
używał separatora `#` i starych, zmyślonych nazw kolumn sprzed odkrycia
realnego formatu RWDZ, więc `run --skip-fetch` dawał 0 wierszy zamiast
udokumentowanych 4. Przepisany na realny format (`;`, prawdziwe nazwy
kolumn z `wynik_mazowieckie.csv`, w tym `ulica_dalej`/`nr_domu`), teraz 9
wierszy wejściowych → dokładnie 4 przechodzą filtry, każde z jawnym, opisanym
powodem odrzucenia pozostałych 5 (Warszawa/instalacja/rozbiórka/data
sprzed 2024/znany duży deweloper).

**Wciąż brak:** CI (`.github/workflows`) — testy trzeba uruchamiać ręcznie.
Pokrycie nie obejmuje `portal_check.py` (wymagałoby mockowania
requests/Playwright) ani `main.py::step_enrich` jako całości (integracyjne,
wymaga sieci) — to świadomy kompromis czasowy, nie przeoczenie.

---

## 7. Sprawdzanie portali — Search API główny backend

- ✅ Brave Search API priorytetowy, OLX HTTP zawsze włączony, filtr
  typu/URL konkretnego ogłoszenia.
- ⚠️ Backend browser (Playwright) nadal niezweryfikowany na żywym ruchu w tym
  środowisku (proxy blokuje Chromium) — fallback bez klucza Brave.
- **Budżet Brave** — pełne 884 leady zużyje ~88% miesięcznego limitu. Decyzja
  wciąż nierozstrzygnięta z Adamem.

---

## 8. Geokodowanie — ULDK główne źródło, teraz z cache

- ✅ ULDK przed Nominatim, fallback ulica→miejscowość, wybór kandydata
  najbliżej Warszawy.
- ✅ Cache trwały (punkt 5) — rozwiązuje wcześniejszy brak.

---

## 9. Warstwa raportowania (Excel) — poprawki i nowe kolumny

**Naprawiony bug zgłoszony przez Adama:** wykresy na Dashboardzie renderowały
się jako puste. Przyczyna: openpyxl/Excel domyślnie rysuje wykres tylko z
WIDOCZNYCH komórek (`chart.visible_cells_only = True` domyślnie), a dane pod
wykresy celowo siedziały w ukrytych kolumnach. Naprawione — wszystkie 4
wykresy mają teraz `visible_cells_only = False`.

**Nowe kolumny (domykają większość braków z poprzedniej wersji audytu):**
- ✅ "Adres (pełny)" + "Mapa" (link Google Maps) — patrz punkt 4.
- ✅ Osobne, klikalne kolumny per portal (Otodom/OLX/Gratka/Morizon/
  Domiporta/RynekPierwotny) zamiast jednego bloku tekstu — kolorowane wg
  werdyktu TEGO KONKRETNEGO dopasowania.
- ✅ "Status kontaktu" — rozwijana lista (Nie kontaktowano/W trakcie/
  Skontaktowano/Odrzucone), czysto do ręcznego użytku, narzędzie tego nie
  czyta ani nie nadpisuje.
- ✅ Źródło dopasowania (`otodom_json`/`olx_api`/`html_regex`) dopisane do
  każdej linii w "Uzasadnienie werdyktu".

**Wciąż brakuje (świadomie odłożone, większy zakres niż "clean up"):**
- Widok "co nowego od ostatniego uruchomienia" — wymaga śledzenia poprzedniego
  snapshotu eksportu, nie tylko `first_seen` w bazie.
- Prawdziwy eksport do zewnętrznego CRM (płaski CSV bez kolumn analitycznych).
- Wykres "Leady per gmina" nabierze sensu dopiero przy pełnych 884 leadach —
  przy próbce 20 to ciekawostka, nie sygnał.

---

## 10. Nowe źródła danych — jeszcze wcześniejszy sygnał (bez zmian)

- Decyzje WZ/MPZP z gmin, GUS REGON (PKD 41.10/41.20), Monitor Sądowy i
  Gospodarczy (nowe SPV deweloperów), przetargi na media/drogi — nic z tego
  nie ruszone.

---

## Podsumowanie: co zostało z poprzedniej listy "4 rzeczy"

1. ~~Wpiąć werdykty weryfikacji do scoringu~~ — ✅ zrobione (punkt 3).
2. ~~Domknąć re-check portali~~ — ✅ zrobione (punkt 1).
3. **Cron dzienny** — nadal do zrobienia, wymaga trwałej maszyny Adama (nie
   da się zrobić z tej sesji).
4. ~~Minimalny test regresji~~ — ✅ zrobione (punkt 6), 29 testów.

**Nowa lista priorytetów, gdyby był czas tylko na jedną rzecz:** cron dzienny —
to jedyny pozostały punkt z pierwotnej listy, i jedyny, którego nie da się
zrobić bez dostępu do trwałej infrastruktury Adama.

---

## 11. Zadania 0-4 (lipiec 2026) — twardy filtr domów prywatnych, martwe
## linki, nowe sygnały matchowania, KRS/PRS, wyszukiwanie strony dewelopera

Duża runda zmian po kolejnej rundzie zrzutów ekranu od Adama z konkretnymi,
błędnymi wierszami (WNIOSEK/10447/2026, WNIOSEK/9227/2026, WNIOSEK/5992/2026).
Zasada nadrzędna przez całą rundę: **w razie niejednoznaczności — zawsze
"wymaga ręcznej weryfikacji", nigdy "pewne dopasowanie"** (fałszywy negatyw
wolimy od fałszywego pozytywu).

### Zadanie 0 — twardy filtr domów jednorodzinnych osób prywatnych

- ✅ `filters.is_private_single_family_home()`: `liczba_budynkow == 1` I
  fuzzy-dopasowanie słowa "wolnostojący" w kategorii obiektu (własny
  Levenshtein, tolerancja literówek — złapie też "WOLNOSTOJACY" bez ogonków
  i realny błąd źródła "SZAMABO" zamiast "SZAMBO").
  Nie odrzuca "zespół budynków"/szeregowy/bliźniak (liczba_budynkow > 1).
- ✅ Odrzucone leady zapisywane do bazy ze `status='rejected'` +
  `rejection_reason` (audyt, nigdy nie eksportowane — `step_export` ma teraz
  `WHERE status != 'rejected'`, wcześniej **w ogóle nie miał WHERE**, czyli
  nawet nieocenione leady trafiały do CSV — realny, niezależny bug znaleziony
  przy okazji).
- ✅ Zweryfikowane na żywo na 884 realnych leadach: 253 odrzucone.
- ✅ Testy: dokładnie 4 przykłady Adama (muszą odrzucić) + przykłady
  wielobudynkowe (muszą przejść) — `tests/test_filters.py`.

### Zadanie 1 — martwe/archiwalne ogłoszenia bez przekierowania

Zdiagnozowane na żywo dla wszystkich 3 zgłoszonych przypadków:

- **Otodom (WNIOSEK/10447 i /9227): HTTP 410, ale strona wciąż serwuje pełny
  `__NEXT_DATA__.ad` JSON** jakby ogłoszenie żyło — poprzedni kod w ogóle nie
  sprawdzał kodu HTTP. Naprawione: `status_code >= 400` → martwe, PLUS
  niezależny sygnał `ad.status != "active"`.
- **Morizon (WNIOSEK/5992): HTTP 404 bez przekierowania.** Naprawione tym
  samym sprawdzeniem kodu HTTP (pierwsza rzecz w `fetch_html_facts`).
- Skatalogowane sygnały "martwe" per portal (wszystkie zweryfikowane na
  żywo 23.07.2026): Gratka/Morizon = HTTP 404 bez przekierowania; RynekPierwotny
  = HTTP 404 bez przekierowania; Domiporta = HTTP 200 PO przekierowaniu na
  kategorię (już wcześniej obsłużone); Otodom = HTTP 410 + `ad.status`.
- ✅ **Zasada 1.3**: dopasowania `dead`/`is_rental` odrzucane NAJPIERW w
  `judge_match`, przed jakąkolwiek analizą geometrii/metrażu.
- ✅ **Zasada 1.4** — świeży, niezależny re-check TUŻ PRZED generowaniem
  raportu (`report_xlsx.effective_matches`/`_final_liveness_check`), nie tylko
  przy pierwszym enrichu. Złapał na żywo **4. przypadek** samodzielnie:
  WNIOSEK/17832/2026 (Otodom), CONFIRMED kilka godzin wcześniej, wygasł zanim
  wygenerowano raport — przepisany na REJECTED z jawnym powodem, lead spadł do
  następnego najlepszego dopasowania (OLX, LIKELY). Realny dowód wartości tego
  kroku, nie tylko teoretyczny.
- ✅ Testy regresyjne z zamockowanym HTML/JSON dla każdego wzorca —
  `tests/test_verify.py`.

### Zadanie 1B — dodatkowe sygnały matchowania

- ✅ **Data ogłoszenia vs data wniosku wzmocniona**: ogłoszenie istotnie
  starsze od wniosku RWDZ teraz jest **twardym pułapem** — dopasowanie nigdy
  nie osiągnie CONFIRMED (`date_caps_confirmed`), nawet z idealną geometrią.
  Celowo NIE hard-reject: legalne wieloetapowe inwestycje mogą mieć wcześniejsze
  ogłoszenia innych budynków na tej samej dużej działce.
- ❌ **Numer działki/KW wprost w treści ogłoszenia** — sprawdzone na żywo na
  4 realnych ogłoszeniach (3 różne portale): nigdzie nie występuje wprost.
  Odrzucone jako niewykonalne przy obecnym stanie treści ogłoszeń na tych
  portalach.
- ❌ **Porównanie snapshotów tego samego URL-a między cyklami recheck** —
  odrzucone świadomie: architektura już odtwarza fakty od nowa przy każdym
  sprawdzeniu (Zadanie 1.4), więc obawa "URL recyklingowany przez portal dla
  innej oferty" jest w dużej mierze już zaadresowana przez samą świeżość
  danych, a dodatkowa warstwa snapshotów dodałaby złożoność bez wyraźnej
  dodatkowej wartości.
- ❌ **Szukanie po nazwie inwestycji/osiedla** — RWDZ nie ma takiego pola
  (tylko `nazwa_zamierzenia_bud`, opis typu budynku, NIE nazwa marketingowa).
  Niewykonalne bez zewnętrznego źródła nazw inwestycji.

### Zadanie 2 — alternatywne źródło danych firmowych (KRS/PRS)

- ❌ **PRS (prs.ms.gov.pl/ci)** sprawdzone na żywo: to Angular SPA, którego
  kafelek "Wyszukiwarka KRS" linkuje wprost do TEGO SAMEGO chronionego
  Incapsulą `wyszukiwarka-krs.ms.gov.pl` (nadal HTTP 403 na żywo) — NIE jest
  niezależnym obejściem. Zgadywane endpointy `/api/prs/...` = 404. Zostaje
  wyłączone, zgodnie z wcześniejszą decyzją.
- ✅ Potwierdzone na żywo: pole inwestora w RWDZ **nigdy** nie zawiera numeru
  KRS (0/320 070 sprawdzonych wartości).
- ✅ `company_lookup.lookup_krs_by_number()` — nowa funkcja, działa na żywo
  przeciw `api-krs.ms.gov.pl/api/krs/OdpisAktualny/{numer}` (potwierdzone np.
  na numerze 0000250912 — pełne dane TOP INVESTMENT). Gotowa do użycia, gdy
  tylko pojawi się skądś numer KRS (obecnie: nigdzie w pipeline, bo RWDZ go
  nie ma — patrz wyżej).
- ✅ CEIDG bez tokenu: już wcześniej działało poprawnie (pomija wzbogacenie
  bez błędu), potwierdzone testem.

### Zadanie 3 — wyszukiwanie strony dewelopera (`src/developer_search.py`)

- ✅ Nowy moduł: pomija osoby fizyczne całkowicie (te same sygnały co
  `filters.looks_like_company`, odwrócone), do 3 wariantów zapytania do Brave
  Search (przerywa na pierwszym wystarczająco dobrym wyniku), blokuje domeny
  6 portali + krótką listę agregatorów/mediów, Facebook/LinkedIn/Instagram to
  ZAWSZE tylko `kandydat_niepewny`.
- ⚠️ **Poważny fałszywy pozytyw złapany na PIERWSZYM żywym teście**:
  `"TOP INVESTMENT Sp. z o.o."` trafiło (najwyższą pewnością!) w
  `companiesmarketcap.com/.../largest-investment-companies-by-market-cap/` —
  kompletnie niezwiązaną stronę o rynkach finansowych, bo fraza "top
  investment" naturalnie występuje w angielskim tekście o inwestycjach.
  Nawet wymóg sąsiedztwa słów (nie tylko niezależnej obecności) tego NIE
  złapał. **Naprawione przeprojektowaniem zasady pewności**: JEDYNYM
  sygnałem wystarczającym do `potwierdzona`/`prawdopodobna` jest teraz dowód
  DOMENOWY (wszystkie długie tokeny marki w nazwie domeny kandydata — i dla
  nazw jednowyrazowych dodatkowy próg długości ≥4 znaki, żeby krótkie,
  generyczne słowo samo nie wystarczyło). Samo wystąpienie nazwy w
  tytule/opisie wyniku wyszukiwania ląduje WYŁĄCZNIE jako `kandydat_niepewny`
  — nigdy wyżej, niezależnie od walidacji treści strony. Walidacja NIP w
  treści strony pozostaje jedynym sposobem podniesienia dowodu domenowego do
  `potwierdzona` (10-cyfrowy numer to wystarczająco swoisty sygnał, w
  odróżnieniu od samej nazwy).
- ✅ Ten sam typ bugu ("M4 Sp. z o. o." z dodatkową spacją nie dopasowywał się
  do sygnału "sp. z o.o." przez zwykły substring) znaleziony i naprawiony
  identycznie w TRZECH miejscach: `filters.looks_like_company`,
  `company_lookup._looks_like_krs_company`, `developer_search.is_individual`
  — realny, wcześniej istniejący bug wpływający na klasyfikację
  osoba/spółka w produkcyjnej logice, nie tylko na nowy kod Zadania 3.
  Naprawa: `_norm_tight()` (dodatkowo usuwa kropki/spacje przed porównaniem).
- ✅ Cache trwały SQLite (`data/developer_search_cache.sqlite3`) — wynik
  pozytywny bez wygasania, "nie znaleziono" z TTL 30 dni.
- ✅ Wpięte do `main.py::step_enrich` (NIP z `company_lookup`, jeśli akurat
  znany, wzmacnia walidację) i do nowych kolumn DB (`dev_site_url`,
  `dev_site_status`, `dev_site_matched_on` — migracja w `db.py`).
  CSV eksportuje te kolumny automatycznie (bez zmiany nazw, tak jak reszta
  CSV — surowe nazwy kolumn DB).
- ✅ Nowe kolumny w Excelu: "Strona dewelopera" (klikalny link TYLKO dla
  `potwierdzona`/`prawdopodobna`; dla `kandydat_niepewny` URL pokazany jako
  zwykły, NIEklikalny tekst do ręcznej weryfikacji, żeby nie sugerować
  pewności, której nie ma) + "Status strony" (kolorowanie: zielony =
  potwierdzona, niebieski/żółty = prawdopodobna/kandydat_niepewny, szary =
  brak/nie znaleziono).
- ✅ Testy: `tests/test_developer_search.py` (21 testów — filtrowanie domen,
  ranking kandydatów, regresja na dokładnym przypadku TOP INVESTMENT,
  walidacja NIP, pominięcie osób fizycznych, cache hit/miss + TTL) +
  `tests/test_report_xlsx.py::test_build_writes_dev_site_columns`
  (end-to-end na zbudowanym pliku xlsx: hiperłącze obecne/nieobecne zgodnie
  ze statusem).
- ⚠️ **Nieprzetestowane na żywo w tej sesji** (brak dostępnego klucza
  `BRAVE_SEARCH_API_KEY` w środowisku tej konkretnej sesji — był dostępny
  wcześniej w tej samej rundzie prac, ale nie przetrwał do tego momentu):
  poprawka na `TOP INVESTMENT`/`M4 Sp. z o. o.` zweryfikowana WYŁĄCZNIE
  testami jednostkowymi z zamockowanym `_search_brave`/`requests.get`,
  dokładnie odtwarzającymi złapany na żywo przypadek (patrz
  `test_rank_candidate_regression_top_investment_false_positive` i
  `test_find_developer_site_regression_top_investment_caps_at_uncertain`).
  Zalecane: ponowny przebieg na żywo z realnym kluczem Brave przy najbliższej
  okazji, żeby potwierdzić że nowa logika faktycznie znajduje PRAWDZIWĄ
  stronę topinvestment.pl (o ile istnieje) zamiast tylko poprawnie odrzucać
  fałszywy trop.

### Podsumowanie ograniczeń, które pozostają po tej rundzie

- Budżet Brave Search dla pełnych 884 leadów wciąż nierozstrzygnięty z
  Adamem (punkt 7) — Zadanie 3 dokłada kolejne zapytania do tego samego
  budżetu (do 3 na inwestora, z cache ograniczającym powtórki).
- Cron dzienny — nadal jedyny punkt z pierwotnej listy CLAUDE.md niezrobiony
  (wymaga trwałej infrastruktury Adama, nie da się z tej sesji).
- Walidacja Zadania 3 nie ma dostępu do numeru KRS w praktyce (RWDZ go nie
  ma — patrz Zadanie 2), więc w tej chwili realnie korzysta tylko z NIP z
  CEIDG (gdy token ustawiony) — status `potwierdzona` będzie w praktyce
  rzadszy niż mógłby być, gdyby KRS był łatwiej dostępny.

### Dodatek — Google Places API jako sygnał podstawowy (po rundzie Zadań 0-4)

`developer_search.lookup_website_via_places()` sprawdza Google Places API
(New) Text Search PRZED Brave Search — zapytanie `"{inwestor} {miejscowość}"`,
`fieldMask` ograniczony do `id,displayName,websiteUri,formattedAddress`.
Niepuste `websiteUri` (po odfiltrowaniu domen portali/agregatorów) daje od
razu `potwierdzona`, BEZ dodatkowej walidacji NIP/tekstu — Google już
zweryfikował powiązanie firma↔strona przez Google Moja Firma, więc to
mocniejszy dowód niż cokolwiek wyciągalne z wyników wyszukiwarki tekstowej.
Brak klucza / błąd sieciowy / brak wyniku → `None`, `find_developer_site`
spada na dotychczasową ścieżkę Brave bez żadnej zmiany w jej logice.

- ✅ Klucz przez `GOOGLE_PLACES_API_KEY`, pipeline działa dalej bez niego
  (ten krok jest po prostu pomijany) — zweryfikowane testem
  (`test_lookup_website_via_places_no_key_returns_none_without_network`).
- ✅ Osobny cache SQLite (`places_lookup`, tabela w tym samym pliku co cache
  Brave) kluczowany po `nazwa+miejscowość` (Places jest zapytywane per
  lokalizacja, w odróżnieniu od cache wyniku końcowego, kluczowanego samą
  nazwą) — ten sam wzorzec TTL co reszta modułu: `potwierdzona` bez
  wygasania, "brak wyniku" z TTL 30 dni.
- ⚠️ **Nieprzetestowane na żywo** — brak dostępnego klucza
  `GOOGLE_PLACES_API_KEY` w tej sesji. Zweryfikowane wyłącznie testami
  jednostkowymi z zamockowanym `_search_places`
  (`tests/test_developer_search.py`, sekcja "Google Places: sygnał
  podstawowy" — 9 nowych testów, w tym przypadek z `websiteUri` → potwierdzona,
  przypadek bez wyniku → fallback do Brave, filtrowanie domen portali,
  błąd sieciowy nie trafia do cache, TTL). Zalecane: pierwszy żywy przebieg
  z realnym kluczem, żeby potwierdzić rzeczywisty format odpowiedzi Places
  API (New) zgadza się z założeniami z dokumentacji Google użytymi tutaj.
