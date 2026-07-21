# Audyt Dev Scout — co zmienić, żeby mieć najświeższe i najtrafniejsze leady

Stan na lipiec 2026, po weryfikacji całego pipeline'u na żywych danych RWDZ
(woj. mazowieckie, 680 815 wierszy). Punkty ułożone od największego wpływu.
"✅ zrobione" = już w kodzie na tym branchu, reszta = rekomendacje.

---

## 1. Świeżość danych — jak mieć „najnowsze" informacje

| Co | Status | Uwagi |
|---|---|---|
| **Cykliczne uruchamianie (cron dzienny)** | do zrobienia (zadanie 4 z CLAUDE.md) | RWDZ/GUNB aktualizuje plik **co noc**. Bez crona pracujemy na starym zrzucie. Rekomendacja: `run → enrich → score → export` raz dziennie o 4:00. |
| **Filtr „tylko od 2024"** | ✅ zrobione | `date_filter.min_data` w config. Odcięło leady sprzed 2024 (inwestycja dawno sprzedana/porzucona). Zawęź do np. „ostatnie 90 dni", gdy zależy Ci wyłącznie na świeżych zgłoszeniach. |
| **Re-check portali co N dni** | ✅ mechanika jest (`recheck_after_days: 14`) | Trzeba jeszcze dopiąć w `enrich`, żeby faktycznie ponawiał sprawdzenie leadów starszych niż N dni (dziś enrich bierze tylko `status='new'`). To domyka ideę „okna czasu": lead czysty dziś, na portalu za 3 tygodnie. |
| **CEIDG endpoint `/zmiana`** | do rozważenia | Zwraca listę firm zmienionych danego dnia — można wykrywać **nowo zarejestrowane firmy budowlane** w gminach docelowych, jeszcze przed pozwoleniem. |

---

## 2. Trafność wzbogacania firmowego — największy pojedynczy unlock

- **Token CEIDG (Profil Zaufany)** — kod `company_lookup.py` jest **gotowy**,
  brakuje tylko tokenu JWT. To Ty musisz się zalogować na
  `biznes.gov.pl` (Profil Zaufany/mObywatel) i wygenerować klucz, potem ustawić
  `export CEIDG_API_TOKEN=...`. Od tego momentu leady będące jednoosobową
  działalnością dostają NIP, adres, telefon, www — **bez zmian w kodzie**.
  Dotyczy dużej części inwestorów (patrz niżej).
- **59% zgłoszeń z 2024+ ma puste pole inwestora** — GUNB anonimizuje osoby
  fizyczne w zrzucie masowym. To znaczy: widoczne nazwy to głównie firmy, a
  „pusty inwestor" jest sam w sobie sygnałem „raczej osoba prywatna". Warto to
  wykorzystać w scoringu (dziś nie jest).
- **KRS po nazwie** — nadal brak legalnej drogi (oficjalne API tylko po numerze,
  wyszukiwarki za ochroną anty-bot). **Alternatywa: GUS BIR1 (REGON API)** —
  darmowy klucz, ma **wyszukiwanie po nazwie** i zwraca REGON/NIP/PKD/adres dla
  firm i spółek. Rekomendacja: dodać `gus_lookup.py` jako drugie źródło obok
  CEIDG (pokryłoby spółki, których CEIDG nie obejmuje).

---

## 3. Trafność filtrów — co jeszcze doprecyzować

- ✅ **Odcięcie instalacji/sieci/przyłączy** (`exclude_keywords`) — usunęło
  „kwiatki" typu „budowa instalacji gazowej … w zabudowie szeregowej".
- ✅ **Tylko budowa nowego budynku** (`require_new_construction`) — odcięło
  rozbiórki, rozbudowy, nadbudowy i „wykonanie robót innych".
- ✅ **Liczba budynków z tekstu** (`extract_building_count`) — ożywiło
  scoring „mała skala" i filtr górnego limitu (cięcie >40 budynków).
- ⚠️ **Domy wolnostojące = ~397 leadów, głównie osoby prywatne.** Dołączone na
  Twoje życzenie, ale to największe źródło szumu. **Jeden przełącznik**:
  `scale_filter.min_budynkow: 2` odetnie pojedyncze domy „buduję dla siebie" i
  zostawi tylko realne inwestycje wielobudynkowe. Rozważ też: wolnostojące
  wpuszczać **tylko gdy inwestor wygląda na firmę** (hybryda).
- **Deduplikacja tej samej inwestycji.** Dedup działa po `id_sprawy` (numer
  GUNB). Ale ta sama inwestycja bywa w rejestrze pod kilkoma numerami
  (pierwotny + „projekt zamienny" + osobne wnioski na etapy). Rekomendacja:
  dodatkowy dedup „miękki" po `(inwestor + ulica + numer_działki)`, żeby jeden
  lead nie pojawiał się 3×. RWDZ ma kolumnę `numer_dzialki` — idealna do tego.

---

## 4. Sprawdzanie portali — najtrafniejszy sygnał, dwie drogi

- ✅ **Backend browser (Playwright)** dodany dla Otodom + pozostałych. Uruchom
  `enable_browser: true` **z Twojej maszyny** (polskie IP domowe) — z serwerowni
  część portali blokuje IP. Świadomie NIE zbudowałem omijania CAPTCHA / rotacji
  proxy / podszywania fingerprintu (realne ryzyko prawne, niepotrzebne tu).
- 🌟 **Lepsza droga długoterminowo: Search API z filtrem `site:`.** Zamiast
  kruchych scraperów per portal — jedno zapytanie do **Brave Search API** lub
  **Bing/Serper** w stylu
  `"<ulica> <miejscowość>" (site:otodom.pl OR site:olx.pl OR site:rynekpierwotny.pl …)`.
  Zalety: jedno zapytanie pokrywa wszystkie portale naraz, odporne na zmiany
  layoutu, legalne (oficjalne API), tanie (Brave ma darmowy tier). To
  rekomendowany kierunek zamiast rozbudowy scraperów.

---

## 5. Geokodowanie i wydajność

- ✅ Fallback ulica→miejscowość + wybór kandydata najbliżej Warszawy (naprawiony
  bug „Jabłonna 96 km").
- **Cache współrzędnych.** Nominatim ma limit 1 zapytanie/s — przy 884 leadach
  to ~15 min tylko na geokodowanie, przy każdym uruchomieniu od nowa. Dodać
  cache w SQLite (jak dla firm), klucz = „ulica, miejscowość".
- **Dokładniejsze geokodowanie po działce.** RWDZ ma `numer_dzialki` + `terc`
  (TERYT) + `obreb_numer`. Geoportal/ULDK (`uldk.gugik.gov.pl`) zwraca geometrię
  działki po ID — dużo dokładniej niż nazwa ulicy, a dla wielu wsi ulicy w OSM
  po prostu nie ma. Rekomendacja dla precyzji mapy.
- **Skala enrichu.** 884 leady × (geokod ~1.1s + OLX ~1.5s) ≈ 40 min bez
  browsera; z browserem (5 portali × 3s) — kilka godzin. Dlatego: enrich tylko
  `status='new'` (już tak działa) + cache. Przy dziennym cronie to i tak
  kilkanaście–kilkadziesiąt nowych leadów dziennie, nie 884.

---

## 6. Scoring — po realnych danych (zadanie 2c)

Na próbce 44 leadów rozkład wag pokazał:

- `mała_skala` (15 pkt) — **teraz działa** (był martwy: brak kolumny + bug
  `int(str(float))`). Realny sygnał deweloperski.
- `bliska_odległość` (10 pkt) — **prawie nie różnicuje**: wszystkie gminy z
  configu już są w promieniu ≤30 km, więc niemal każdy lead dostaje te punkty.
  Rekomendacja: albo obniżyć wagę, albo przeliczać na gradient (bliżej = więcej),
  a nie próg 0/1.
- `brak_na_portalach` (40 pkt) — dziś liczony z samego OLX. Nabierze wartości
  dopiero po włączeniu browsera/Search API (inaczej „brak na OLX" ≠ „brak
  wszędzie").
- `mała_firma_bez_www` (20 pkt) — **działa dopiero z tokenem CEIDG** (bez tokenu
  poprawnie NIE nalicza, po naprawie bugu z `None`).
- **Propozycja nowej wagi:** „inwestor pusty/osoba prywatna" — skoro 59% to
  osoby fizyczne, rozróżnienie firma/osoba jest mocnym sygnałem jakości leada.

**Rekomendacja:** wag nie ma sensu stroić, dopóki nie ma (a) tokenu CEIDG i
(b) pełnego sprawdzania portali — bo dwa z pięciu kryteriów są wtedy „ślepe".
Najpierw te dwa unlocki, potem strojenie na pełnych danych.

---

## 7. Nowe źródła danych — jeszcze wcześniejszy sygnał

- **Decyzje o warunkach zabudowy (WZ)** i **miejscowe plany (MPZP)** z gmin —
  poprzedzają pozwolenie na budowę o miesiące. Część gmin publikuje rejestry WZ.
  To najwcześniejszy możliwy sygnał „ktoś planuje inwestycję".
- **GUS REGON** — nowe firmy z PKD 41.10/41.20 (realizacja projektów / roboty
  budowlane budynków) rejestrowane w gminach docelowych.
- **Monitor Sądowy i Gospodarczy (MSiG)** — nowo zawiązane spółki celowe (SPV)
  deweloperów.
- **Przetargi na media/drogi** przy nowych osiedlach — sygnał uzbrajania terenu.

---

## Podsumowanie: 3 rzeczy o największym wpływie, gdybyś miał zrobić tylko tyle

1. **Zdobądź token CEIDG** — odblokowuje realne dane firm i wagę
   `mała_firma_bez_www` (kod już czeka).
2. **Włącz sprawdzanie portali** — browser z Twojej maszyny albo (lepiej)
   Search API z `site:`. Dopiero wtedy `brak_na_portalach` (40 pkt!) coś znaczy.
3. **Cron dzienny** — bez tego pracujesz na wczorajszym zrzucie i tracisz
   przewagę czasową, która jest całym sensem narzędzia.
