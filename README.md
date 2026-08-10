# LAKES

Mobile-first website for finding the perfect bathing lake in Berlin & Brandenburg —
water quality, temperature, visibility, hazards, amenities, on an interactive map.

## Structure

- `docs/DATA-SOURCES.md` — full inventory of data sources, fields, gaps, v1 plan
- `data/berlin/` — LaGeSo snapshots (letzte.csv = sites + latest values, History.csv = season time series)
- `data/brandenburg/` — Badestellen portal exports (KML/XML, ~250 sites)
- `scripts/fetch_data.py` — downloads/refreshes all raw data (`python scripts/fetch_data.py`)
- `scripts/fetch_bb_details.py` — pulls Brandenburg per-site lab values (E. coli, enterococci)
  from the detail pages → `data/brandenburg/messwerte.csv`, plus full remark texts
  → `data/brandenburg/bemerkungen.csv` (the KML export truncates remarks at 35 chars);
  runs weekly via Actions (license: DL-DE-BY-2.0, source LAVG)

## Status (2026-07-19)

- [x] Data source exploration (Berlin + Brandenburg verified live)
- [x] Build script: normalize sources → `site/data/lakes.geojson`
- [x] Mobile-first Leaflet map (`site/index.html`)
- [x] GitHub Actions: daily data refresh + Pages deploy (`.github/workflows/deploy.yml`)
- [ ] Fetch Brandenburg raw data (`python scripts/fetch_data.py`), refine KML parser if needed
- [ ] Later: temperature history, VBB transport, OSM surroundings, GIS analysis

## Run locally

    python scripts/fetch_data.py       # pull latest raw data
    python scripts/build_geojson.py    # build site/data/lakes.geojson
    python -m http.server -d site      # open http://localhost:8000

## Deploy to GitHub Pages

1. Create a GitHub repo, push this folder (`git init && git add -A && git commit && git push`)
2. Repo Settings → Pages → Source: **GitHub Actions**
3. Done — the workflow deploys on every push and refreshes data daily at 06:00 Berlin time

## Data licenses

Berlin: CC-BY 4.0 (attribution: Geoportal Berlin / LaGeSo). Brandenburg: see
badestellen.brandenburg.de/nutzungsbedingungen before publishing.
