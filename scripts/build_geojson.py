"""Build site/data/lakes.geojson from raw data in data/.

Sources (uses whatever is present, skips the rest with a warning):
- data/berlin/letzte.csv (or newest letzte_*.csv)  -> Berlin sites + latest values
- data/brandenburg/badestellen.kml                 -> Brandenburg sites
- data/eu/eea_bw_DE_berlin_brandenburg_1990_2025.csv -> EU classification (joined by proximity)

Usage: python scripts/build_geojson.py
Stdlib only.
"""
import bisect
import csv
import datetime
import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "data" / "lakes.geojson"

EU_CLASS_DE = {
    "1": "ausgezeichnet", "2": "gut", "3": "ausreichend", "4": "mangelhaft",
}
STATUS_LABEL = {
    "green": "Zum Baden geeignet",
    "yellow": "Beanstandet – Warnhinweise beachten",
    "red": "Vom Baden wird abgeraten",
    "ban": "Badeverbot",
    "unknown": "Keine aktuelle Bewertung",
}


def de_float(s):
    """'19,8' -> 19.8; returns None if not parseable."""
    if s is None:
        return None
    s = str(s).strip().replace(",", ".")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def de_date(s):
    """'17.06.2026' -> '2026-06-17'."""
    try:
        return datetime.datetime.strptime(s.strip(), "%d.%m.%Y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def newest(folder, pattern, plain):
    """Prefer plain filename; else newest dated snapshot."""
    p = folder / plain
    if p.exists():
        return p
    cands = sorted(folder.glob(pattern))
    return cands[-1] if cands else None


# --------------------------------------------------------------- Berlin
def load_berlin():
    src = newest(ROOT / "data" / "berlin", "letzte_*.csv", "letzte.csv")
    if not src:
        print("WARN  no Berlin letzte.csv found - skipping Berlin", file=sys.stderr)
        return []
    feats = []
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter=";"):
            lat, lon = de_float(r.get("Latitude")), de_float(r.get("Longitude"))
            if lat is None or lon is None:
                print(f"WARN  Berlin row without coords: {r.get('BadName')}", file=sys.stderr)
                continue
            farbe = (r.get("Farbe") or "").lower()
            if "gruen" in farbe:
                status = "green"
            elif "gelb" in farbe:
                status = "yellow"
            elif "rot" in farbe:
                status = "red"
            else:
                status = "unknown"
            warn = (r.get("Bemerkung") or "").strip()
            info = (r.get("Weitere_Hinweise") or "").strip()
            feats.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
                "properties": {
                    "id": "BE-" + (r.get("BSL") or r.get("BadName", "?")),
                    "name": r.get("BadName", "").strip(),
                    "region": "berlin",
                    "area": r.get("Bezirk", ""),
                    "water": r.get("Profil", ""),
                    "status": status,
                    "status_label": STATUS_LABEL[status],
                    "date": de_date(r.get("Dat", "")),
                    "temp": de_float(r.get("Temp")),
                    "visibility": (r.get("Sicht") or "").strip() or None,
                    "ecoli": (r.get("Eco") or "").strip() or None,
                    "entero": (r.get("Ente") or "").strip() or None,
                    "coliform": (r.get("cb") or "").strip() or None,
                    "warn": warn if warn.lower() != "keine" else None,
                    "info": info if info.lower() != "keine" else None,
                    "forecast": ((r.get("Wasserqualitaet_predict") or "").strip()
                                 if (r.get("Wasserqualitaet_predict") or "").strip()
                                 not in ("", "nicht zutreffend") else None),
                    "eu_class": None,  # filled from EEA join below
                    "link": r.get("BadestelleLink", "").strip() or None,
                },
            })
    print(f"OK    Berlin: {len(feats)} sites from {src.name}")
    return feats


# --------------------------------------------------------- Brandenburg
KML_NS = "{http://www.opengis.net/kml/2.2}"
# evaluation1..5 = portal legend: 1 geeignet, 2 Warnhinweise, 3 Empfehlung nicht
# baden, 4 Badeverbot zeitweilig, 5 Badeverbot dauerhaft; 0 = keine Bewertung
EVAL_STATUS = {"1": "green", "2": "yellow", "3": "red", "4": "ban", "5": "ban",
               "0": "unknown"}
KREIS = {
    "BAR": "Barnim", "BRB": "Brandenburg a.d.H.", "CB": "Cottbus",
    "EE": "Elbe-Elster", "FF": "Frankfurt (Oder)", "HVL": "Havelland",
    "LDS": "Dahme-Spreewald", "LOS": "Oder-Spree", "MOL": "Märkisch-Oderland",
    "OHV": "Oberhavel", "OPR": "Ostprignitz-Ruppin", "OSL": "Oberspreewald-Lausitz",
    "P": "Potsdam", "PM": "Potsdam-Mittelmark", "PR": "Prignitz",
    "SPN": "Spree-Neiße", "TF": "Teltow-Fläming", "UM": "Uckermark",
}


def dash_none(s):
    s = (s or "").strip()
    return None if s in ("", "-") else s


def clean_text(s):
    """Strip stray HTML tags (e.g. '<br />') and collapse whitespace."""
    if not s:
        return s
    return " ".join(re.sub(r"<[^>]+>", " ", s).split())


def load_brandenburg():
    src = newest(ROOT / "data" / "brandenburg", "badestellen_*.kml", "badestellen.kml")
    if not src:
        print("WARN  no Brandenburg badestellen.kml found - skipping Brandenburg "
              "(run scripts/fetch_data.py)", file=sys.stderr)
        return []
    try:
        tree = ET.parse(src)
    except ET.ParseError as e:
        print(f"WARN  cannot parse {src.name}: {e}", file=sys.stderr)
        return []
    feats = []
    for pm in tree.getroot().iter(f"{KML_NS}Placemark"):
        name_el = pm.find(f"{KML_NS}name")
        name = (name_el.text or "").strip() if name_el is not None else ""
        coords = None
        for el in pm.iter(f"{KML_NS}coordinates"):
            if el.text and el.text.strip():
                coords = el.text.strip()
                break
        if not coords:
            continue
        try:
            lon, lat = (float(x) for x in coords.split(",")[:2])
        except ValueError:
            continue
        # ExtendedData key/value pairs
        d = {}
        for data in pm.iter(f"{KML_NS}Data"):
            val = data.find(f"{KML_NS}value")
            if data.get("name") and val is not None:
                d[data.get("name")] = (val.text or "").strip()
        style_el = pm.find(f"{KML_NS}styleUrl")
        style = (style_el.text or "") if style_el is not None else ""
        m = re.search(r"evaluation(\d)", (d.get("smiley") or "") + " " + style)
        status = EVAL_STATUS.get(m.group(1), "unknown") if m else "unknown"
        bnr = dash_none(d.get("bnr"))
        remarks = clean_text(dash_none(d.get("remarks")))
        amenities = {k: v for k, v in {
            "wc": dash_none(d.get("lavatory")),
            "gastro": dash_none(d.get("gastronomy")),
            "rettung": dash_none(d.get("lifeguard")),
            "abfall": dash_none(d.get("wasteDisposal")),
            "strand": dash_none(d.get("beachCharacter")),
        }.items() if v}
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "id": f"BB-{bnr or len(feats)}",
                "name": name or d.get("name") or "Badestelle",
                "region": "brandenburg",
                "area": KREIS.get(d.get("district", ""), d.get("district")) or None,
                "water": dash_none(d.get("bodyOfWater")),
                "status": status,
                "status_label": STATUS_LABEL[status],
                "date": de_date(d.get("lastMeasurementDate", "")),
                "temp": de_float(dash_none(d.get("temperature"))),
                "visibility": (dash_none(d.get("visibilityDepth")) or "")
                              .replace(" m", "").strip() or None,
                "ecoli": None, "entero": None, "coliform": None,
                "bacteriology": dash_none(d.get("bacteriology")),
                "warn": remarks,
                "info": None,
                "forecast": None,
                "eu_class": EU_CLASS_DE.get((d.get("rating") or "").strip()),
                "amenities": amenities or None,
                "link": (f"https://badestellen.brandenburg.de/badestelle/-/details/{bnr}"
                         if bnr else None),
            },
        })
    print(f"OK    Brandenburg: {len(feats)} sites from {src.name}")
    n_unknown = sum(f["properties"]["status"] == "unknown" for f in feats)
    if feats and n_unknown > len(feats) * 0.5:
        print(f"WARN  {n_unknown}/{len(feats)} Brandenburg sites unknown - check parser",
              file=sys.stderr)
    return feats


def merge_bb_measurements(feats):
    """Merge latest lab values from data/brandenburg/messwerte.csv into BB features."""
    src = ROOT / "data" / "brandenburg" / "messwerte.csv"
    if not src.exists():
        print("WARN  no messwerte.csv - Brandenburg lab values not merged "
              "(run scripts/fetch_bb_details.py)", file=sys.stderr)
        return
    latest = {}  # bnr -> row with max datum
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["bnr"] not in latest or r["datum"] > latest[r["bnr"]]["datum"]:
                latest[r["bnr"]] = r
    merged = 0
    for f_ in feats:
        p = f_["properties"]
        if p["region"] != "brandenburg":
            continue
        row = latest.get(p["id"].removeprefix("BB-"))
        if not row:
            continue
        def fmt(v):
            return (v or "").rstrip("0").rstrip(".").replace(".", ",") or None
        p["ecoli"] = fmt(row["ecoli"])
        p["entero"] = fmt(row["entero"])
        if p["temp"] is None and row["temp_c"]:
            p["temp"] = float(row["temp_c"])
        if p["visibility"] is None and row["sicht_m"]:
            p["visibility"] = fmt(row["sicht_m"])
        if p["date"] is None:
            p["date"] = row["datum"]
        merged += 1
    print(f"OK    messwerte merge: lab values on {merged} Brandenburg sites")


def merge_bb_bemerkungen(feats):
    """Replace KML-truncated remarks (the export caps them at 35 chars, '…xyz...')
    with the full text scraped from the detail pages
    (data/brandenburg/bemerkungen.csv, written by scripts/fetch_bb_details.py)."""
    src = ROOT / "data" / "brandenburg" / "bemerkungen.csv"
    if not src.exists():
        print("WARN  no bemerkungen.csv - truncated Brandenburg remarks stay truncated "
              "(run scripts/fetch_bb_details.py)", file=sys.stderr)
        return
    full = {}
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = clean_text((r.get("bemerkung") or "").strip())
            if t:
                full[r["bnr"]] = t
    n = 0
    for f_ in feats:
        p = f_["properties"]
        if p["region"] != "brandenburg" or not p.get("warn"):
            continue
        if not p["warn"].endswith("..."):
            continue
        t = full.get(p["id"].removeprefix("BB-"))
        # only replace when the full text still matches the truncated prefix
        # (protects against a remark that changed after the last scrape)
        if t and t.lower().startswith(p["warn"][:-3].strip().lower()[:20]):
            p["warn"] = t
            n += 1
    print(f"OK    bemerkungen merge: full warning text on {n} Brandenburg sites")


# ---------------------------------------------------------- percentiles
def add_percentiles(feats):
    """Per-metric percentile rank vs all other assessed lakes (midrank, 0-100).

    pct.ecoli / pct.entero : cleaner than X % of lakes (lower value = higher pct)
    pct.visibility         : clearer than X % of lakes
    pct.temp               : warmer than X % of lakes
    pct_n                  : number of lakes with a value, per metric
    """
    higher_is_better = {"ecoli": False, "entero": False,
                        "visibility": True, "temp": True}
    vals = {m: [] for m in higher_is_better}
    for f_ in feats:
        for m in vals:
            v = de_float(f_["properties"].get(m))
            if v is not None:
                vals[m].append(v)
    for m in vals:
        vals[m].sort()
    for f_ in feats:
        p = f_["properties"]
        pct, pct_n = {}, {}
        for m, hib in higher_is_better.items():
            v, arr = de_float(p.get(m)), vals[m]
            if v is None or len(arr) < 10:
                continue
            lo = bisect.bisect_left(arr, v)
            hi = bisect.bisect_right(arr, v)
            r = (lo + (hi - lo) / 2) / len(arr)  # midrank share below
            pct[m] = round((r if hib else 1 - r) * 100)
            pct_n[m] = len(arr)
        if pct:
            p["pct"], p["pct_n"] = pct, pct_n
    print(f"OK    percentiles: computed on {sum(1 for f_ in feats if f_['properties'].get('pct'))} sites "
          f"(n per metric: { {m: len(v) for m, v in vals.items()} })")


# ----------------------------------------------------------------- EEA
def name_tokens(s):
    """Normalized token set for name matching: 'Wannsee, Strandbad' == 'STRANDBAD WANNSEE'."""
    s = (s or "").upper()
    for a, b in (("Ä", "AE"), ("Ö", "OE"), ("Ü", "UE"), ("ß", "SS")):
        s = s.replace(a, b)
    return frozenset(re.findall(r"[A-Z]+", s))


def eu_join(feats):
    src = ROOT / "data" / "eu" / "eea_bw_DE_berlin_brandenburg_1990_2025.csv"
    if not src.exists():
        print("WARN  no EEA extract - skipping EU classification join", file=sys.stderr)
        return
    latest = {}  # bwid -> (year, quality, lat, lon)
    with open(src, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                year = int(str(r["season"])[:4])
                lat, lon = float(r["lat"]), float(r["lon"])
            except (ValueError, KeyError):
                continue
            q = str(r.get("quality", ""))
            bwid = r["bathingWaterIdentifier"]
            if bwid not in latest or year > latest[bwid][0]:
                latest[bwid] = (year, q, lat, lon, r.get("bathingWaterName", ""))
    joined = 0
    for f_ in feats:
        if f_["properties"]["eu_class"]:
            continue
        flon, flat = f_["geometry"]["coordinates"]
        best, bestd = None, 0.006  # ~500 m
        for year, q, lat, lon, _name in latest.values():
            d = abs(lat - flat) + abs(lon - flon)
            if d < bestd:
                best, bestd = q, d
        if not best:
            # fallback: exact name match (EEA coords can sit >1 km from the
            # beach access point, e.g. Schlachtensee), tokens must be equal
            ftoks = name_tokens(f_["properties"]["name"])
            for year, q, lat, lon, name in latest.values():
                if ftoks and name_tokens(name) == ftoks:
                    best = q
                    break
        if best:
            cls = EU_CLASS_DE.get(best.strip()[:1])
            if cls:
                f_["properties"]["eu_class"] = cls
                joined += 1
    print(f"OK    EEA join: eu_class set on {joined} additional sites")


def main():
    feats = load_berlin() + load_brandenburg()
    if not feats:
        sys.exit("ERROR no features built - no input data found")
    merge_bb_measurements(feats)
    merge_bb_bemerkungen(feats)
    eu_join(feats)
    add_percentiles(feats)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fc = {
        "type": "FeatureCollection",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "features": feats,
    }
    OUT.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"OK    wrote {OUT.relative_to(ROOT)} ({len(feats)} features)")


if __name__ == "__main__":
    main()
