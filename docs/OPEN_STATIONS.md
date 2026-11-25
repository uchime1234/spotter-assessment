# Rebuild the open-source station catalog

The open-source pipeline uses US Census Geocoder as a locator for numbered street addresses and OpenStreetMap for station coordinates. It uses the supplied Spotter CSV only on your machine. Protected operator feeds and snapshots are unnecessary. The app, route API and optimizer consume the resulting CSV without code changes.

## Windows quick start

Extract the rebuild kit **into the extracted Spotter project root** so the existing `scripts`, `tests`, and `docs` directories merge. The kit includes normalized OpenStreetMap snapshots under `private-data/open-osm`. The snapshots contain no OPIS rows, station-to-OPIS crosswalk, or Census requests. Install the same dependencies as in the project README, place your already-authorized Spotter CSV in `private-data`, and run:

```powershell
$python = '.\.venv\Scripts\python.exe'
$prices = 'private-data/fuel-prices-for-be-assessment.csv'
$snapshots = @(Get-ChildItem .\private-data\open-osm\??.json | Sort-Object Name | ForEach-Object { $_.FullName })

& $python -m scripts.geocode $prices private-data/open_census_pilot.csv --cache private-data/open-census-cache
if ($LASTEXITCODE -ne 0) { throw 'The Census batch failed. Check its output and rerun.' }

& $python -m scripts.open_station_catalog $prices private-data/verified_stations.csv private-data/open_station_audit.csv --osm @snapshots --census-pilot private-data/open_census_pilot.csv
if ($LASTEXITCODE -ne 0) { throw 'The catalog rebuild failed.' }

Get-FileHash .\private-data\verified_stations.csv -Algorithm SHA256
$env:PILOT_CSV = (Resolve-Path .\private-data\verified_stations.csv).Path
$env:PRICE_CSV = (Resolve-Path $prices).Path
$env:OSRM_URL = 'https://router.project-osrm.org'
& $python manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

Use `curl.exe` on PATH for the Census batch; modern Windows includes it. The script invokes `curl` as an executable. Run `manage.py test` in the same virtual environment. The original synthetic setup still works when both CSV environment variables are cleared. If Census is unavailable, omit `--census-pilot` to build from OSM evidence alone; that run may have slightly lower coverage.

## Source and matching rules

1. The numbered-street heuristic finds four suitable street-format inputs in the supplied CSV. Submit them in one official Census multipart batch using `Public_AR_Current`. The script retains empty ZIP columns and caches the response. Two Census responses were `Exact` address-range matches. An address-range match is only a lead. It contributes to verification when a matching OSM fuel feature is within 0.25 miles and meets the locality checks. Use the OSM feature's coordinate.
2. The OSM extraction reads local Geofabrik PBFs. It indexes `amenity=fuel` nodes and closed fuel ways, place nodes, and `highway=motorway_junction` references linked to interstate refs on connected motorway ways. Closed fuel ways use a representative point inside the mapped footprint. The tool does not infer coordinates from exits or locality centers.
3. Verification requires a matching operator or facility label and corroborating locality. Locality comes from the OSM address city or a like-named OSM locality within ten miles. Evidence must also include a linked interstate and exit within 1.5 miles, a corresponding store number, a matching numbered street address, or Census corroboration. When the price row has an interstate and exit, a matching linked exit is required. Conflicting explicit store numbers, explicitly private fuel features, multiple distinct results at the strongest evidence level, and the same OSM feature claimed by multiple OPIS IDs are rejected.
4. The compatible output includes OSM feature URLs and PBF fingerprints. The price file is never submitted to an OSM provider. The pipeline makes no public Nominatim requests.

To regenerate a normalized extract, install `requirements-osm.txt`, download the state PBF and checksum from Geofabrik, verify its checksum, then run:

```powershell
& $python -m pip install -r requirements-osm.txt
& $python -m scripts.open_station_sources private-data/open-osm/NM.json --pbf NM private-data/new-mexico-latest.osm.pbf
```

The bundled JSON is the pinned normalized source for this assessment run. It records the SHA-256 of the PBF it came from. New Geofabrik extracts or Census benchmarks can change results. [Census API](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html) · [Geofabrik US extracts](https://download.geofabrik.de/north-america/us.html) · [OSM fuel tagging](https://wiki.openstreetmap.org/wiki/Tag:amenity%3Dfuel) · [OSM exit tagging](https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmotorway_junction)

## Licensing and evaluator handoff

The bundled normalized OSM snapshots are © OpenStreetMap contributors and distributed under the Open Database License 1.0. Keep the attribution and license with copies. Follow the applicable ODbL share-alike and access requirements for downstream databases and public use. Census geocoder data is U.S. Census Bureau data. The kit does not include the submitted addresses or Census output records. [OpenStreetMap attribution and license](https://www.openstreetmap.org/copyright) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/)

The open-source snapshots and scripts can be handed off separately from the supplied CSV. A reviewer who already has authorized access to the Spotter CSV can generate the OPIS-linked catalog locally. The combined `verified_stations.csv` and row-level audit contain OPIS-linked data. The supplied CSV had no express redistribution grant in the materials provided. Confirm applicable OPIS rights and ODbL obligations before distributing those joined outputs. The rebuild kit does not include them.

## Measured coverage and live routes

| Metric | Count |
|---|---:|
| Distinct US station IDs in Spotter input | 6,626 |
| IDs in the 11 loaded extract states | 1,475 |
| Verified matches | 253 |
| Unmatched | 6,373 |
| Unmatched because a state extract was not loaded | 5,151 |
| Unmatched with insufficient matching evidence | 1,195 |
| Unmatched because of competing distinct sites | 21 |
| Unmatched because multiple OPIS IDs claimed one feature | 6 |

Coverage was **3.82% nationwide in the supplied US IDs** and **17.15% in the loaded states**. There was one Census-corroborated match, 13 store-number matches and 239 interstate-exit matches. `verified` here denotes a reproducible evidence rule, not a surveyed ground-truth accuracy figure. Operator changes, incomplete OSM tags, same-brand sites close to exits, and locality differences can cause errors or missed matches. Non-interstate exits and OSM relation-only fuel objects were outside this extraction. Fuel availability, vehicle access, and actual detour distances are unverified.

| Journey | Start latitude, longitude | Finish latitude, longitude | Base mi | Modeled mi incl. detours | Stops | Gallons | Purchases |
|---|---|---|---:|---:|---:|---:|---:|
| Tulsa to Cincinnati | 36.154, -95.9928 | 39.1031, -84.512 | 743.053 | 744.380 | 2 | 24.4380 | $71.35 |
| Albuquerque to Las Vegas | 35.0844, -106.6504 | 36.1699, -115.1398 | 571.512 | 572.091 | 1 | 7.2091 | $23.24 |
| San Francisco to Salt Lake City | 37.7749, -122.4194 | 40.7608, -111.8910 | 736.142 | 736.875 | 2 | 23.6875 | $80.81 |
| Atlanta to Baton Rouge | 33.749, -84.388 | 30.4515, -91.1871 | 526.629 | 527.293 | 1 | 2.7293 | $8.07 |

These are live HTTP results with the same model and the replacement catalog. All four returned HTTP 200 with one OSRM request each. The fuel and prices were independently replayed. The resulting `verified_stations.csv` SHA-256 was `6c73e570e64086aebdb62b51204f6b0d78f3f9331e8c5bc0010dbcd586343d4c`. The checksum is for the pinned snapshots and observed Census result. Native Windows execution was not tested in the cloud.
