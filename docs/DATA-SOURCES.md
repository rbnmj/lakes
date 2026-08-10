# LAKES — Data Source Inventory (July 2026)

## Berlin (39 bathing sites) — best starting point

### 1. LaGeSo History CSV ⭐ primary
`https://www.data.lageso.de/baden/00_History_gesamt/History.csv`
- Per site, per sampling date (every ~14 days, season 15 May – 15 Sep), verified live with data through 08.07.2026
- Fields (semicolon-separated): site name; date; **E. coli** (KBE/100ml); **intestinal enterococci**; **coliform bacteria**; **visibility depth (m)**; **cyanobacteria chlorophyll-a (µg/l)**; **water temperature (°C)**; current warnings (text); further info (text); **traffic-light color** (gruen / gelb / rot + prognosis variants)
- Quirks to handle when parsing: values like `<15`, `> 1`, `n.a.`, empty cells; German decimal commas; inconsistent formats (`>2,00` vs `> 2`)
- License: open data (CC-BY-style attribution: LaGeSo)

### 1b. LaGeSo letzte.csv ⭐ master site table
`https://data.lageso.de/baden/0_letzte/letzte.csv`
- One row per site, latest measurement. Verified live (snapshot saved in `data/berlin/`)
- Fields: BadName; **Bezirk** (district); **Profil** (water body); RSS_Name; **Latitude/Longitude** (decimal-comma!); links to Badegewässerprofil + site page; date; visibility; E. coli; enterococci; color icon; site ID (BSL); algae; quality code; coliforms; temperature; season-PDF link; **early-warning forecast** for Unterhavel sites (predicted quality + p2.5–p97.5 percentiles); EU classification
- **Solves the coordinate gap** — no name-matching against WFS needed for v1
- Role: master table (locations + current status); History.csv adds the time series

### 2. GDI Berlin WFS/WMS (geodata)
- WFS (GeoJSON-capable): `https://gdi.berlin.de/services/wfs/badegewaesser`
- WMS: `https://gdi.berlin.de/services/wms/badegewaesser`
- Content: site locations (coordinates, EPSG:25833), sampling points, EU classification, pollution sources in catchment, infrastructure, ÖPNV access
- Format docs: `https://gdi.berlin.de/data/badegewaesser/docs/Datenformatbeschreibung_Badegewaesser.pdf`
- License: CC-BY 4.0

### 3. LaGeSo site pages
`berlin.de/lageso/.../liste-der-badestellen/` — per-site detail pages with photos, EU rating, amenities. Scrapable if WFS lacks something.

## Brandenburg (~250 bathing sites)

### 4. Badestellen portal exports ⭐ primary
- KML: `https://badestellen.brandenburg.de/web/badestellen/badestellen/-/export/badestellen.kml` (verified reachable)
- XML: `https://badestellen.brandenburg.de/web/badestellen/badestellen/-/export/badestellen.xml`
- Content: coordinates + current quality assessment (5 levels: suitable → temporary ban → permanent ban), EU 4-year classification (excellent/good/sufficient/poor/new), visibility depth, algae/cyanobacteria warnings, beach type, infrastructure (DLRG water rescue, gastronomy, sanitary, waste), photos
- Updated **daily** during season
- Note: terms of use page should be checked before republishing (`/nutzungsbedingungen`)

## Supplementary (later phases)

| Need | Source |
|---|---|
| Water temperature (year-round, gauges) | `wasserportal.berlin.de` — API, includes Brandenburg LfU stations |
| Public transport | VBB REST API / GTFS (covers Berlin + Brandenburg) |
| Surroundings (forest, toilets, parking, kiosks) | OpenStreetMap via Overpass API |
| Lake depth/morphology | Berlin Tiefenlinienkarte (Geoportal); Brandenburg LfU |
| EU-wide comparison / long-term history | EEA dataset **already in `data/eu/`** (1990–2025); Berlin+Brandenburg extract: `data/eu/eea_bw_DE_berlin_brandenburg_1990_2025.csv` — 6,736 rows, 281 BB + 39 BE sites, annual EU quality class, coords, bathingWaterIdentifier (DEBB*/DEBE* → stable join key!) |

## Known gaps
- ~~Berlin History CSV has no coordinates~~ → solved: join History↔letzte by BadName (names match)
- Brandenburg has no long-format history file like Berlin's → daily snapshot + own archiving if trends wanted
- Temperature outside bathing season: only via Wasserportal gauges, not per bathing site

## Recommended v1 scope (static site, Leaflet)
1. Build script (Python or Node) fetches Berlin CSV + WFS and Brandenburg KML → normalizes both into one `lakes.geojson` with a shared schema: id, name, region, lat/lon, status (green/yellow/red), EU class, temperature, visibility, warnings, amenities, last_sampled
2. Mobile-first single-page app: full-screen Leaflet map, markers colored by status, bottom-sheet detail card on tap, filter chips (quality / min. temperature / amenities)
3. Host on GitHub Pages/Netlify; refresh data via scheduled GitHub Action (daily during season)
