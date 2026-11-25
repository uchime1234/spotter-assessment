# Five-minute Loom script

Start `python -m scripts.demo_provider` in one terminal. In another, run `python manage.py runserver 127.0.0.1:8000 --noreload --insecure`. On Windows, use the [PowerShell quickstart](../README.md#run-the-synthetic-demo). Open the planner at http://127.0.0.1:8000/. Keep the recording in synthetic mode for public sharing.

| Time | Screen and narration |
|---|---|
| 0:00–0:45 | Introduce the planner and show the **Synthetic demo** badge, start and destination fields, and vehicle assumptions. “The planner accepts US addresses in authorized live mode and coordinates in latitude–longitude order. The vehicle starts with a full 50-gallon tank.” |
| 0:45–1:45 | Click **Use demo coordinates**, then **Calculate Route**. Pan or zoom the map and open the fuel stop marker. “The route line is the GeoJSON returned by the API. The marker shows the station name, per-gallon price, and how much to buy.” |
| 1:45–2:35 | Show the trip summary and fuel stops. “This fictional route models 620 miles and purchases 12 gallons for $36.00. Detour mileage is an estimate. The synthetic route is for demonstration only.” |
| 2:35–3:25 | Enter an invalid latitude such as `95, -95.9928` and calculate again to show the error. Restore the demo coordinates and use the browser’s responsive view to show the stacked layout. |
| 3:25–4:20 | Show the existing `POST /api/v1/fuel-routes/` request in Postman. Point out `fuel_routes/serializers.py`, the routing and optimizer services, and the template and static files. “The browser calls the same API as Postman. The backend remains responsible for selecting stations and calculating cost.” |
| 4:20–5:00 | Show the test results and README. Explain where an authorized evaluator configures live data and remind viewers that route and detour estimates depend on that catalog. |

Keep the OpenStreetMap attribution visible while recording the map.
