"""
Pobiera plik zbiorczy RWDZ (Rejestr Wnioskow, Decyzji i Zgloszen) dla wojewodztwa
mazowieckiego i rozpakowuje go lokalnie.

Zrodlo: https://wyszukiwarka.gunb.gov.pl/pobranie.html
Dane sa jawne, darmowe, aktualizowane co noc. Plik per-wojewodztwo jest duzo
mniejszy niz zbior "caly kraj" i wystarczajacy dla promienia 20-30 km od Warszawy.

UWAGA (dla Claude Code): ten skrypt trzeba uruchomic z maszyny z realnym
dostepem do internetu (domena wyszukiwarka.gunb.gov.pl) - sandbox, w ktorym
powstal ten kod, nie mial do niej dostepu, wiec download nie zostal
przetestowany na zywych danych. Przy pierwszym uruchomieniu sprawdz:
  - czy plik faktycznie jest zipem z jednym CSV w srodku
  - czy nazwa pliku wewnatrz zipa jest przewidywalna (ponizej zakladamy,
    ze da sie ja znalezc dynamicznie, wiec to nie powinno wywalic skryptu)
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30))
def download_bytes(url: str, timeout: int = 120) -> bytes:
    log.info("Pobieram %s", url)
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "dev-scout/0.1"})
    resp.raise_for_status()
    return resp.content


def fetch_and_extract(url: str, raw_dir: Path) -> Path:
    """Pobiera zip z RWDZ, rozpakowuje do raw_dir, zwraca sciezke do pliku CSV."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_bytes = download_bytes(url)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_names = [n for n in zf.namelist() if n.lower().endswith((".csv", ".txt"))]
        if not csv_names:
            # jesli w zipie nie ma nic co wyglada na CSV, zrzuc wszystko i pozwol
            # czlowiekowi/Claude Code zobaczyc co naprawde jest w srodku
            zf.extractall(raw_dir)
            raise RuntimeError(
                f"Nie znaleziono pliku CSV w zipie. Zawartosc: {zf.namelist()}. "
                f"Rozpakowano do {raw_dir} — sprawdz recznie."
            )
        target_name = csv_names[0]
        zf.extract(target_name, raw_dir)
        extracted_path = raw_dir / target_name

    log.info("Rozpakowano do %s", extracted_path)
    return extracted_path


if __name__ == "__main__":
    import yaml

    logging.basicConfig(level=logging.INFO)
    cfg = yaml.safe_load(open(Path(__file__).parent.parent / "config.yaml", encoding="utf-8"))
    out_path = fetch_and_extract(
        cfg["rwdz"]["wojewodztwo_zip_url"],
        Path(__file__).parent.parent / cfg["paths"]["raw_dir"],
    )
    print(f"Gotowe: {out_path}")
