"""Exercise Django against real routing and measure cold and warm request times."""
import argparse
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings
from django.core.cache import cache
from django.test.utils import override_settings
from rest_framework.test import APIClient

JOURNEYS = {
    "Tulsa to Cincinnati": ((36.154, -95.9928), (39.1031, -84.512)),
    "Albuquerque to Las Vegas": ((35.0844, -106.6504), (36.1699, -115.1398)),
    "San Francisco to Salt Lake City": ((37.7749, -122.4194), (40.7608, -111.8910)),
    "Atlanta to Baton Rouge": ((33.749, -84.388), (30.4515, -91.1871)),
    "Honolulu to Los Angeles": ((21.3069, -157.8583), (34.0522, -118.2437)),
}


def run(baseline_catalog=None):
    if settings.SYNTHETIC_CATALOG:
        raise SystemExit("Configure authorized PILOT_CSV and PRICE_CSV before live smoke tests.")
    client = APIClient()
    results = []
    with override_settings(ALLOWED_HOSTS=["testserver"]):
        for title, (start, finish) in JOURNEYS.items():
            cache.clear()
            payload = {key: dict(zip(("latitude", "longitude"), point))
                       for key, point in (("start", start), ("finish", finish))}
            durations = []
            for _ in range(6):
                began = perf_counter()
                response = client.post("/api/v1/fuel-routes/", payload, format="json")
                durations.append((perf_counter() - began) * 1000)
                if response.status_code != 200:
                    break
            result = response.json()
            comparison = {}
            if baseline_catalog is not None:
                with override_settings(PILOT_CSV=baseline_catalog):
                    baseline = client.post("/api/v1/fuel-routes/", payload, format="json")
                baseline_result = baseline.json()
                comparison = {
                    "baseline_status": baseline.status_code,
                    "baseline_code": baseline_result.get("code"),
                    "baseline_cost_usd": baseline_result.get("estimated_fuel_purchases_usd"),
                }
            results.append({
                "journey": title, "http_status": response.status_code, "code": result.get("code"),
                "cold_ms": round(durations[0], 1),
                "warm_median_ms": round(median(durations[1:]), 1) if len(durations) > 1 else None,
                "route_miles": result.get("route_miles"),
                "total_miles_estimate": result.get("total_miles_estimate"),
                "catalog_verified_stations": result.get("catalog_verified_stations"),
                "estimated_fuel_purchases_usd": result.get("estimated_fuel_purchases_usd"),
                "fuel_stops": [stop["station_name"] for stop in result.get("fuel_stops", [])],
                **comparison,
            })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.baseline), indent=2))
