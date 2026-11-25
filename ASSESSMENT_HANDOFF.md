# Spotter assessment handoff

The public archive defaults to a reproducible synthetic trip with 620 modeled miles, 12 gallons purchased, and a purchase cost of $36.00. For an actual driving route, use the authorized data setup below. The synthetic route is for demonstration only.

## Windows setup

Open PowerShell in the extracted project folder. Install Python 3.12 or later and Git only if you plan to publish the source. The demo can run directly from the extracted folder. The commands below use the virtual environment's Python without changing PowerShell's script execution policy.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m pip check
& .\.venv\Scripts\python.exe manage.py test
```

Replace `-3.12` with the installed version selector if using a newer Python.

### Synthetic mode

In the first PowerShell window, start the local routing fixture.

```powershell
& .\.venv\Scripts\python.exe -m scripts.demo_provider
```

In a second PowerShell window opened at the project root, start Django on loopback.

```powershell
Remove-Item Env:PILOT_CSV,Env:PRICE_CSV,Env:OSRM_URL -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

Open http://127.0.0.1:8000/, select **Use demo coordinates**, and click **Calculate Route**. The demo should show the **Synthetic demo** badge. The `--insecure` flag serves static files during local development with `DEBUG=0`. Keep the server on loopback for the demo.

### Authorized real-data mode

Place these two exact files in the ignored `private-data/` directory, using copies you are authorized to use.

| File | Role | SHA-256 of the tested input |
|---|---|---|
| `fuel-prices-for-be-assessment.csv` | Original assessment OPIS prices | `c704371f141ded9c54df6c32d488a0ba2ceb589f88c936c967daa5330e0cd241` |
| `verified_stations.csv` | Prepared station coordinates and provenance. The tested snapshot has 505 verified US stations. | `1354f0c27470c6f49b2702f5f47ea983814d88a78ae67d5bba18bbbddc613d43` |

Neither input is in the ZIP. Those two inputs suffice for the runtime demonstration. The offline rebuild in [README.md](README.md) requires authorized operator feed and page snapshots and the applicable pilot reviews to reproduce the historical catalog. Census and OpenStreetMap evidence are used in the documented preparation workflows. Use the same authorized snapshots for an exact historical rebuild.

**Private evaluator sharing remains conditional.** The supplied OPIS file had no express redistribution grant in the material provided. The coordinate catalog combines OPIS-linked records with operator-derived data. The reviewed Love's and TA site terms restrict reuse or distribution. An evaluator who already has the authorized OPIS export can use their own copy. Before sending either restricted file privately, obtain written permission or confirm that an existing license expressly covers the evaluator, files, and intended assessment use. A private link alone does not establish redistribution rights. [Love's terms](https://www.loves.com/terms-of-use) · [TA terms](https://www.ta-petro.com/terms-conditions-web/)

Stop the synthetic Django server before switching. The synthetic provider is unnecessary in real-data mode.

```powershell
New-Item -ItemType Directory -Force .\private-data | Out-Null
# Place the authorized files in private-data before running the following commands.
Get-FileHash .\private-data\fuel-prices-for-be-assessment.csv -Algorithm SHA256
Get-FileHash .\private-data\verified_stations.csv -Algorithm SHA256
$env:PILOT_CSV = (Resolve-Path .\private-data\verified_stations.csv).Path
$env:PRICE_CSV = (Resolve-Path .\private-data\fuel-prices-for-be-assessment.csv).Path
$env:OSRM_URL = 'https://router.project-osrm.org'
$env:SPOTTER_LOG_PROVIDER_REQUESTS = '1'
& .\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000 --noreload --insecure
```

The page should show **Authorized real data**. OSRM is a shared demo provider. Census is called for street addresses, and OpenStreetMap tiles are used for the basemap when reachable.

## Real-route request examples

Paste this into a separate PowerShell window while authorized mode is running. It sends the exact audited coordinate pairs to the existing endpoint.

```powershell
$routes = @(
  @{ label='Tulsa to Cincinnati'; start=@{latitude=36.154; longitude=-95.9928}; finish=@{latitude=39.1031; longitude=-84.512} }
  @{ label='Albuquerque to Las Vegas'; start=@{latitude=35.0844; longitude=-106.6504}; finish=@{latitude=36.1699; longitude=-115.1398} }
  @{ label='San Francisco to Salt Lake City'; start=@{latitude=37.7749; longitude=-122.4194}; finish=@{latitude=40.7608; longitude=-111.8910} }
  @{ label='Atlanta to Baton Rouge'; start=@{latitude=33.749; longitude=-84.388}; finish=@{latitude=30.4515; longitude=-91.1871} }
)
foreach ($route in $routes) {
  $body = @{ start=$route.start; finish=$route.finish } | ConvertTo-Json -Depth 3
  $plan = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/fuel-routes/' -ContentType 'application/json' -Body $body
  [pscustomobject]@{
    Route = $route.label
    BaseMiles = $plan.route_miles
    ModeledMiles = $plan.total_miles_estimate
    Stops = @($plan.fuel_stops).Count
    GallonsPurchased = ($plan.fuel_stops | Measure-Object -Property gallons_purchased -Sum).Sum
    PurchaseCostUSD = $plan.estimated_fuel_purchases_usd
  }
}
```

Observed results from the authorized assessment run. Live provider routes and catalog revisions can change these values.

| Journey | Base miles | With estimated detours | Stops | Gallons purchased | Purchase cost |
|---|---:|---:|---:|---:|---:|
| Tulsa to Cincinnati | 743.053 | 743.525 | 1 | 24.3525 | $80.38 |
| Albuquerque to Las Vegas | 571.512 | 571.925 | 1 | 7.1925 | $24.72 |
| San Francisco to Salt Lake City | 736.142 | 736.706 | 2 | 23.6706 | $88.11 |
| Atlanta to Baton Rouge | 526.629 | 527.025 | 1 | 2.7025 | $8.50 |

## Interpretation of total fuel cost

The original requirement says **“Calculate the total estimated fuel expenditure.”** The API returns `estimated_fuel_purchases_usd` for the gallons bought at the selected stops. It starts with 50 gallons and places no dollar value on that starting inventory. A drive within the starting tank's capacity can therefore consume fuel and show $0.00 in additional purchases.

The estimated value of **all fuel consumed** would include the portion of the starting fuel consumed plus the value of fuel purchased and consumed along the way. It would need a starting fuel price and a stated valuation method. The API meets the expenditure requirement if it means purchases during the journey. It does not fully satisfy an interpretation that requires the dollar value of all fuel consumed. The submission should disclose this assumption.

Station detours are geometric estimates, the catalog is partial, and the model permits zero estimated fuel at arrival. These affect interpretation of the live examples. Windows commands are documented. The final test suite was executed on Linux.
