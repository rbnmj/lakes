"""Fetch all LAKES raw data sources into data/.

Usage:  python scripts/fetch_data.py
Requires: Python 3.8+ (standard library only).
Files are saved date-stamped, plus a "latest" copy without date.
"""
import datetime
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TODAY = datetime.date.today().isoformat()

SOURCES = [
    # (url, subfolder, base filename)
    ("https://www.data.lageso.de/baden/00_History_gesamt/History.csv",
     "berlin", "History.csv"),
    ("https://data.lageso.de/baden/0_letzte/letzte.csv",
     "berlin", "letzte.csv"),
    ("https://badestellen.brandenburg.de/web/badestellen/badestellen/-/export/badestellen.kml",
     "brandenburg", "badestellen.kml"),
    ("https://badestellen.brandenburg.de/web/badestellen/badestellen/-/export/badestellen.xml",
     "brandenburg", "badestellen.xml"),
]

HEADERS = {"User-Agent": "LAKES-project/0.1 (personal, non-commercial)"}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main() -> None:
    for url, sub, name in SOURCES:
        out_dir = ROOT / "data" / sub
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            data = fetch(url)
        except Exception as e:
            print(f"FAILED  {url}: {e}")
            continue
        stem, dot, ext = name.rpartition(".")
        dated = out_dir / f"{stem}_{TODAY}.{ext}"
        latest = out_dir / name
        dated.write_bytes(data)
        latest.write_bytes(data)
        print(f"OK      {dated.relative_to(ROOT)}  ({len(data):,} bytes)")


if __name__ == "__main__":
    main()
