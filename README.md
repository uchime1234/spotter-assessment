# Spotter fuel route assessment

A Django REST API that plans partial fuel purchases along one driving route. The vehicle starts with a full 50-gallon tank, has a 500-mile maximum range at 10 MPG, and has no mandatory arrival reserve. The reported cost covers purchases during the journey.

## Fresh-clone setup

Use Python 3.12 or newer on Windows, Linux, or macOS. Django 6.1.3 and Django REST Framework 3.18.3 are pinned in `requirements.txt`. The tests use generated or bundled synthetic fixtures and mock the network.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python manage.py check
python manage.py test
```

On Windows, run the equivalent commands in PowerShell from the repository root. Calling the virtual environment's Python directly also works when script activation is restricted.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

### Run the synthetic demo

In one terminal, run `python -m scripts.demo_provider`. It listens on loopback port 8767 and serves one fictional route. In a second terminal, start Django using the same virtual environment. Use the PowerShell commands on Windows.

```sh
SPOTTER_LOG_PROVIDER_REQUESTS=1 python manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

On Windows, start the provider in the first terminal with `.\.venv\Scripts\python.exe -m scripts.demo_provider`. Start Django in the second terminal with the following commands.

```powershell
$env:SPOTTER_LOG_PROVIDER_REQUESTS = "1"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

Open **http://127.0.0.1:8000/**, click **Use demo coordinates**, then click **Calculate Route**. The browser draws the API's GeoJSON and lets you click each station for its price and purchase quantity. Enter street addresses in authorized real-data mode, or enter coordinates in `latitude, longitude` order. The default synthetic provider recognizes only the demo coordinate pair.

The development-only `--insecure` flag serves static assets with the project's default `DEBUG=0`. For deployment, run `python manage.py collectstatic` and serve the collected `staticfiles/` directory with your web server. The repository bundles Leaflet 1.9.4 under its BSD license. Basemap tiles come from OpenStreetMap and require internet access. If tiles are unavailable, the map uses the bundled US Census state outlines and still displays the route overlay and fuel plan. [OpenStreetMap attribution](https://www.openstreetmap.org/copyright) · [Tile usage policy](https://operations.osmfoundation.org/policies/tiles/)

To call the API directly, send the fixture request from a third terminal or import `spotter.postman_collection.json`.

```sh
curl -fsS http://127.0.0.1:8000/api/v1/fuel-routes/ \
  -H 'Content-Type: application/json' \
  -d '{"start":{"latitude":36.154,"longitude":-95.9928},"finish":{"latitude":39.1031,"longitude":-84.512}}'
```

In PowerShell, use **Postman** or `Invoke-RestMethod` to avoid shell quoting differences. Import `spotter.postman_collection.json`, keep `base_url` at `http://127.0.0.1:8000`, and send **Synthetic demo — fuel stop** after both processes start.

Expect HTTP 200, `catalog_mode: synthetic`, a GeoJSON LineString, 620 modeled miles, one fictional stop, 12 gallons, and **$36.00**. The length and station are fixture inputs for illustrating the optimizer. They provide no navigation guidance. The loopback provider has only the documented coordinate pair. The Postman collection includes a repeat request, an invalid request, and separately labeled live examples for authorized real-data mode.

## API and project layout

- `config/` holds Django settings, root URL routing, and WSGI and ASGI entry points.
- `fuel_routes/serializers.py` and `fuel_routes/views.py` validate coordinates or complete US street addresses and format the response. Bare city names should be supplied as coordinates. Census address matching is used in live mode.
- `fuel_routes/services/routing.py` resolves endpoints, calls OSRM once on a typical uncached journey, caches successful routes, validates the station catalog, and uses a spatial index to find near-route stations.
- `fuel_routes/services/optimizer.py` compares fuel purchases along ordered, reachable legs. It accounts for the inbound and outbound portion of estimated station detours and accepts fractional purchases.
- Offline modules in `scripts/` support optional, authorized catalog preparation. They are outside the request path.
- `fuel_routes/templates/` and `fuel_routes/static/` contain the planner page, styles, browser code, and Leaflet assets.
- `tests/` contains the automated suite, `fixtures/` holds the synthetic catalog, and `resources/geo/` holds the state boundaries.

GeoJSON uses longitude–latitude order. Its line and base distance come from the routing provider. Station detours use a geometric out-and-back estimate, with each direction 1.5 times the station’s projected offset. The response keeps detours separate and sets `detour_road_verified` to false. Results depend on the selected route, its candidate stations, and the model. The cache is per process. Concurrent misses may make separate provider calls. Routable points are snapped within 1 km of each endpoint. For a given route, the planner considers verified stations within three geometric miles of the route. It uses the median of distinct OPIS `Retail Price` values by station ID, assuming USD per gallon. The supplied CSV has no observation dates or fuel-grade field, so those prices are assessment inputs.

The estimated purchase cost excludes fuel already in the tank. A trip within the initial modeled range can show $0.00 in purchases while still consuming fuel. The planner can arrive with zero estimated gallons. It works within one provider-selected route and a limited station catalog. Road access, current prices, and a practical fuel reserve require separate verification.

## Authorized real-data evaluation

The uploaded OPIS CSV, operator coordinates, operator snapshots, and previous audit results belong in an authorized private handoff or a directory outside Git. The source checkout contains the code and the fictional dataset. The evaluator needs the OPIS export and permission to use and retain operator snapshots. The original audit found no express public redistribution grant for the supplied price export. Love’s and TA site terms restrict copying or redistributing source material. Obtain clearance before downloading or reusing those sources where required. Keep raw and derived files private. [Love’s terms](https://www.loves.com/terms-of-use) · [TA terms](https://www.ta-petro.com/terms-conditions-web/)

With authorized copies, place the price CSV and any supplied operator feed JSON, TA page HTML, and manual review CSV under `private-data/`. The rebuild uses files on disk. The optional pilot requires `curl` on PATH and uses `filelock` to protect the cache across processes. It calls the US Census batch service for four suitable street records, caches the result by request fingerprint, and leaves unresolved matches out of planning. Add `--reviews private-data/reviews.csv` only if authorized operator evidence is available. [Census geocoding API](https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html)

```sh
mkdir -p private-data
python -m scripts.geocode private-data/fuel-prices-for-be-assessment.csv private-data/pilot.csv \
  --cache private-data/geocode-cache
python -m scripts.station_matching snapshot private-data/operator_snapshot.json \
  --loves private-data/loves-bulk.json \
  --ta https://www.ta-petro.com/location/wa/ta-seattle-east private-data/ta-seattle-east.html \
  --ta https://www.ta-petro.com/location/nv/ta-sparks private-data/ta-sparks.html
python -m scripts.station_matching build private-data/fuel-prices-for-be-assessment.csv private-data/pilot.csv \
  private-data/operator_snapshot.json private-data/verified_stations.csv private-data/pilot_audit.csv
```

The Love’s input is an authorized saved response from its store locator feed at `https://www.loves.com/api/fetch_stores`. TA inputs are saved pages containing station JSON-LD. The TA arguments can be omitted if those snapshots are unavailable. Source files and manual reviews determine the resulting coverage. Reproducing the historical catalog requires the same snapshots and reviews. A provided authorized catalog can also be used directly.

OpenStreetMap extracts are optional review evidence. To prepare them, install `requirements-osm.txt`, download authorized regional Geofabrik PBFs, and run `python -m scripts.osm_extract private-data/osm_evidence.json --pbf NM private-data/new-mexico.osm.pbf`. Pass `--osm private-data/osm_evidence.json` to the build. An OSM proximity candidate by itself never becomes a verified station. The state boundary layer is based on US Census cartographic boundaries. [Geofabrik downloads](https://download.geofabrik.de/) · [OSM attribution and ODbL](https://www.openstreetmap.org/copyright) · [Census boundary conversion](https://eric.clst.org/tech/usgeojson/)

```sh
export PILOT_CSV="$PWD/private-data/verified_stations.csv"
export PRICE_CSV="$PWD/private-data/fuel-prices-for-be-assessment.csv"
export OSRM_URL=https://router.project-osrm.org
python manage.py runserver 127.0.0.1:8000 --insecure
```

Run live smoke journeys separately with `python -m scripts.live_routes`. The public OSRM endpoint is a shared demo service. Use a permitted endpoint for sustained evaluation.

## Local and deployment settings

The default settings are for loopback HTTP and use an ephemeral generated secret. `SPOTTER_LOG_PROVIDER_REQUESTS=1` logs only the provider name. The two catalog paths must be set together to switch to authorized data. `.env.example` documents supported environment variables. Django reads exported variables. In PowerShell, set variables with `$env:NAME = 'value'`. Relative catalog paths are resolved from the repository root. For multiline POSIX examples, use one line in PowerShell or replace each shell continuation with a PowerShell backtick.

| Deployment warning from local settings | HTTPS example in `config/settings_production.py` |
|---|---|
| W002, frame protection | Enables Django frame protection with `DENY`. |
| W003, CSRF middleware | Enables Django CSRF middleware. The current JSON endpoint has no login or cookie-based workflow. Recheck CSRF and auth together before introducing either. |
| W004, HSTS | Sets an initial one-hour policy for a confirmed HTTPS host. |
| W008, HTTPS redirects | Redirects HTTP to HTTPS. Configure trusted proxy TLS signaling only if the proxy strips attacker-supplied forwarding headers and sets its own. |

For an HTTPS deployment, generate a persistent Django secret with `django.core.management.utils.get_random_secret_key()`, store it in the deployment secret store, and inject it as `DJANGO_SECRET_KEY`. Inject the remaining environment values as appropriate for your host.

```sh
export DJANGO_ALLOWED_HOSTS=spotter.example.invalid
export PILOT_CSV=/srv/private/verified_stations.csv
export PRICE_CSV=/srv/private/fuel-prices-for-be-assessment.csv
export OSRM_URL=https://routing.example.invalid
python manage.py check --deploy --settings=config.settings_production
```

Replace the example hosts and paths with your actual values. Use these settings only with an HTTPS-capable deployment. Django's two remaining example warnings are W005 and W021. Enable HSTS for subdomains or request preload only after confirming every affected subdomain supports permanent HTTPS and the domain meets browser preload requirements. Public operation would also need access controls, resource limits and data rights. This project is an assessment demo.

See the [five-minute Loom guide](docs/LOOM_DEMO.md) and [publishing checklist](docs/PUBLISHING.md).
# spotter-assessment
