"""Fetch per-site measurement tables from badestellen.brandenburg.de detail pages.

Writes data/brandenburg/messwerte.csv (full season, all sites, long format):
    bnr,name,datum,ecoli,entero,temp_c,sicht_m

Also writes data/brandenburg/bemerkungen.csv (bnr,name,bemerkung) with the FULL
remark text per site - the KML export truncates remarks at 35 characters.

Site list is read from the local KML (run scripts/fetch_data.py first).
Data license: Datenlizenz Deutschland - Namensnennung 2.0, source: LAVG.

Usage: python scripts/fetch_bb_details.py [--limit N]
Stdlib only. ~250 requests with a polite delay; takes a few minutes.
"""
import csv
import datetime
import html as html_mod
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KML = ROOT / "data" / "brandenburg" / "badestellen.kml"
OUT = ROOT / "data" / "brandenburg" / "messwerte.csv"
OUT_BEM = ROOT / "data" / "brandenburg" / "bemerkungen.csv"
NS = "{http://www.opengis.net/kml/2.2}"
URL = "https://badestellen.brandenburg.de/badestelle/-/details/{bnr}"
HEADERS = {"User-Agent": "LAKES-project/0.1 (personal, non-commercial; polite weekly fetch)"}
DELAY_S = 0.7


class TableParser(HTMLParser):
    """Collect all <table> elements as lists of rows of cell text."""

    def __init__(self):
        super().__init__()
        self.tables, self._rows, self._row, self._cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def num(s):
    """German number string -> float or None. Keeps '<15' as 15 (detection limit)."""
    if not s:
        return None
    m = re.search(r"-?\d+(?:,\d+)?", s)
    return float(m.group().replace(",", ".")) if m else None


def parse_measurements(html_text):
    p = TableParser()
    p.feed(html_text)
    for rows in p.tables:
        if not rows or not any("Escherichia" in c for c in rows[0]):
            continue
        out = []
        for row in rows[1:]:
            if len(row) < 5:
                continue
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", row[0])
            if not m:
                continue  # empty trailing row
            d, mo, y = m.groups()
            out.append({
                "datum": f"{y}-{mo}-{d}",
                "ecoli": num(row[1]),
                "entero": num(row[2]),
                "temp_c": num(row[3]),
                "sicht_m": num(row[4]),
            })
        return out
    return []


def parse_bemerkungen(html_text):
    """Full remark text from the 'Bemerkungen' section (KML truncates at 35 chars)."""
    m = re.search(r"Bemerkungen\s*</h\d>(.*?)(?:<h\d|<table|<footer)",
                  html_text, re.S | re.I)
    if not m:
        return None
    txt = re.sub(r"<[^>]+>", " ", m.group(1))
    txt = " ".join(html_mod.unescape(txt).split())
    txt = re.sub(r"Keine Messwerte gefunden\.?", "", txt).strip()
    return txt or None


def site_list():
    sites = []
    for pm in ET.parse(KML).getroot().iter(f"{NS}Placemark"):
        d = {}
        for data in pm.iter(f"{NS}Data"):
            v = data.find(f"{NS}value")
            if data.get("name") and v is not None:
                d[data.get("name")] = (v.text or "").strip()
        name_el = pm.find(f"{NS}name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        if d.get("bnr", "").isdigit():
            sites.append((d["bnr"], name))
    return sites


def main():
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    if not KML.exists():
        sys.exit("ERROR data/brandenburg/badestellen.kml missing - run scripts/fetch_data.py first")
    sites = site_list()[:limit]
    print(f"fetching {len(sites)} detail pages ...")
    rows, bems, failed = [], [], []
    delay = DELAY_S
    for i, (bnr, name) in enumerate(sites, 1):
        got = None
        for attempt in (1, 2):
            try:
                req = urllib.request.Request(URL.format(bnr=bnr), headers=HEADERS)
                with urllib.request.urlopen(req, timeout=12) as r:
                    page = r.read().decode("utf-8", "replace")
                got = parse_measurements(page)
                bem = parse_bemerkungen(page)
                if bem:
                    bems.append({"bnr": bnr, "name": name, "bemerkung": bem})
                delay = max(DELAY_S, delay * 0.8)  # recover speed after good response
                break
            except Exception as e:
                if attempt == 2:
                    failed.append((bnr, str(e)))
                    print(f"  FAIL  {i}/{len(sites)} bnr {bnr}: {e}", flush=True)
                else:
                    delay = min(5.0, delay * 2)  # back off if server is throttling
                    time.sleep(delay)
        for m in got or []:
            rows.append({"bnr": bnr, "name": name, **m})
        if i % 10 == 0:
            print(f"  {i}/{len(sites)} ({len(rows)} measurements, {len(failed)} failed)",
                  flush=True)
        time.sleep(delay)
    if not rows:
        sys.exit("ERROR no measurements parsed at all - page structure may have changed")
    rows.sort(key=lambda r: (int(r["bnr"]), r["datum"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bnr", "name", "datum", "ecoli", "entero",
                                          "temp_c", "sicht_m"])
        w.writeheader()
        w.writerows(rows)
    print(f"OK    wrote {OUT.relative_to(ROOT)}: {len(rows)} measurements, "
          f"{len({r['bnr'] for r in rows})} sites, {len(failed)} failures")
    bems.sort(key=lambda r: int(r["bnr"]))
    with open(OUT_BEM, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["bnr", "name", "bemerkung"])
        w.writeheader()
        w.writerows(bems)
    print(f"OK    wrote {OUT_BEM.relative_to(ROOT)}: {len(bems)} sites with remarks")
    for bnr, err in failed[:10]:
        print(f"WARN  bnr {bnr}: {err}", file=sys.stderr)


if __name__ == "__main__":
    main()
