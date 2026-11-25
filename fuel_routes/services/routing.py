"""Provider adapters and indexed station projection."""
from collections import defaultdict
import csv
from decimal import Decimal
from functools import lru_cache
from hashlib import sha256
import json
import logging
import math
from statistics import median
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
import requests
from shapely import Point, STRtree, box
from shapely.geometry import shape

from .optimizer import Stop

MILES_PER_METER = 1 / 1609.344
CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
CORRIDOR = 3
DETOUR_MULTIPLIER = 1.5
SNAP_RADIUS_METERS = 1000
PROVIDER_LOG = logging.getLogger("spotter.providers")


class TripError(Exception):
    def __init__(self, code, status, message):
        super().__init__(message)
        self.code, self.status = code, status


def provider_json(url, params, handled=()):
    try:
        provider = "census" if url == CENSUS_URL else "osrm"
        PROVIDER_LOG.info("provider_request %s", provider)
        response = requests.get(url, params=params, timeout=(3, 12), allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise TripError("provider_error", 502, "Unexpected provider redirect.")
        if response.status_code not in handled:
            response.raise_for_status()
        return response.json()
    except requests.Timeout as exc:
        raise TripError("provider_timeout", 504, "Location or routing provider timed out.") from exc
    except (requests.RequestException, ValueError) as exc:
        raise TripError("provider_error", 502, "Location or routing provider failed.") from exc


@lru_cache(maxsize=1)
def boundaries():
    source = json.loads(settings.STATE_BOUNDARIES_PATH.read_text(encoding="utf-8"))
    return STRtree([shape(feature["geometry"]) for feature in source["features"]
                    if int(feature["properties"]["STATE"]) < 60])


def resolve(value):
    if isinstance(value, str):
        key = "census:" + sha256(value.casefold().encode()).hexdigest()
        coordinates = cache.get(key)
        if coordinates is None:
            payload = provider_json(CENSUS_URL, {"address": value, "benchmark": "Public_AR_Current",
                                                 "format": "json"})
            try:
                matches = payload["result"]["addressMatches"]
                if not isinstance(matches, list):
                    raise ValueError("Invalid geocoder matches")
                if len(matches) != 1:
                    raise TripError("address_unresolved", 422,
                                    "Provide an unambiguous US street address or coordinates.")
                location = matches[0]["coordinates"]
                coordinates = (float(location["x"]), float(location["y"]))
                if not valid_coordinates(*coordinates):
                    raise ValueError("Invalid geocoder coordinates")
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                raise TripError("provider_error", 502, "Invalid geocoding response.") from exc
            cache.set(key, coordinates, 86400)
    else:
        coordinates = (value["longitude"], value["latitude"])
    if not len(boundaries().query(Point(*coordinates), predicate="intersects")):
        raise TripError("outside_us", 400, "Both endpoints must be in the United States.")
    return coordinates


def valid_coordinates(lon, lat):
    return -180 <= lon <= 180 and -90 <= lat <= 90


def driving_route(start, finish):
    pair = ";".join(f"{lon:.6f},{lat:.6f}" for lon, lat in (start, finish))
    base = settings.OSRM_URL.rstrip("/")
    key = "osrm:" + sha256(f"{base}:{pair}:{SNAP_RADIUS_METERS}".encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        return cached
    payload = provider_json(
        f"{base}/route/v1/driving/{pair}",
        {"overview": "full", "geometries": "geojson",
         "radiuses": f"{SNAP_RADIUS_METERS};{SNAP_RADIUS_METERS}"}, handled=(400,))
    if isinstance(payload, dict) and payload.get("code") in ("NoRoute", "NoSegment"):
        raise TripError("no_driving_route", 422, "No driving route connects the endpoints.")
    try:
        if payload["code"] != "Ok":
            raise ValueError("OSRM non-success code")
        route = payload["routes"][0]
        geometry = route["geometry"]
        distance = float(route["distance"])
        if not (math.isfinite(distance) and distance >= 0 and geometry["type"] == "LineString"
                and len(geometry["coordinates"]) >= 2
                and all(valid_coordinates(x, y) for x, y in geometry["coordinates"])):
            raise ValueError("Invalid route")
    except (KeyError, TypeError, IndexError, ValueError, OverflowError) as exc:
        raise TripError("provider_error", 502, "Invalid routing response.") from exc
    result = geometry, distance * MILES_PER_METER
    cache.set(key, result, 3600)
    return result


@lru_cache(maxsize=4)
def load_catalog(pilot, prices, pilot_version, prices_version):
    with pilot.open(newline="", encoding="utf-8-sig") as stream:
        records = {}
        for row in csv.DictReader(stream):
            if row["match_status"] != "verified":
                continue
            key = row["opis_station_id"]
            source = urlsplit(row["source"])
            if (key in records or not key or not (row["station_name"] or "").strip()
                    or source.scheme != "https" or not source.hostname):
                raise ValueError("Invalid station identity or provenance")
            records[key] = row
    amounts = defaultdict(set)
    with prices.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            key = row["OPIS Truckstop ID"]
            if key in records:
                amount = Decimal(row["Retail Price"])
                if not amount.is_finite() or amount <= 0:
                    raise ValueError("Invalid station price")
                amounts[key].add(amount)
    for key, record in records.items():
        record["latitude"] = float(record["latitude"])
        record["longitude"] = float(record["longitude"])
        if not valid_coordinates(record["longitude"], record["latitude"]):
            raise ValueError("Invalid station coordinate")
        record["price"] = median(sorted(amounts[key]))
    rows = list(records.values())
    return rows, STRtree([Point(row["longitude"], row["latitude"]) for row in rows])


def catalog():
    pilot, prices = settings.PILOT_CSV, settings.PRICE_CSV
    try:
        return load_catalog(pilot, prices, pilot.stat().st_mtime_ns, prices.stat().st_mtime_ns)
    except (OSError, ValueError, ArithmeticError, KeyError, TypeError, csv.Error) as exc:
        raise TripError("catalog_unavailable", 503, "Verified station catalog is unavailable.") from exc


def candidates(geometry, miles, rows, index):
    coordinates = geometry["coordinates"]
    progressed = 0.0
    projections = {}
    for (x1, y1), (x2, y2) in zip(coordinates, coordinates[1:]):
        # Local equirectangular projection is adequate for short OSRM segments.
        xscale = 69.093 * max(math.cos(math.radians((y1 + y2) / 2)), .01)
        yscale = 69.093
        dx, dy = (x2 - x1) * xscale, (y2 - y1) * yscale
        length = math.hypot(dx, dy)
        if not length:
            continue
        padx, pady = CORRIDOR / xscale, CORRIDOR / yscale
        for station_index in index.query(box(min(x1, x2) - padx, min(y1, y2) - pady,
                                             max(x1, x2) + padx, max(y1, y2) + pady)):
            row = rows[station_index]
            px, py = (row["longitude"] - x1) * xscale, (row["latitude"] - y1) * yscale
            fraction = min(1, max(0, (px * dx + py * dy) / length**2))
            offset = math.hypot(px - fraction * dx, py - fraction * dy)
            if offset <= CORRIDOR and (station_index not in projections or
                                       offset < projections[station_index][0]):
                projections[station_index] = offset, progressed + fraction * length
        progressed += length
    if not progressed:
        return []
    return [Stop(rows[i]["opis_station_id"], Decimal(str(min(miles, at / progressed * miles))),
                 Decimal(str(offset * DETOUR_MULTIPLIER)), rows[i]["price"])
            for i, (offset, at) in projections.items()]
