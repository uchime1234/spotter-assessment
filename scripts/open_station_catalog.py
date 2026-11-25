"""Join the assessor's local price file to Census and OpenStreetMap evidence."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import re

from shapely.geometry import Point

from .geocode import FIELDS, STATES, address_type, atomic_write, csv_bytes
from .station_matching import STATE_CODES, city_key, interchange, normalize, state_shapes

MAX_EXIT_MILES = 1.5
MAX_CITY_MILES = 10
MAX_CENSUS_MILES = 0.25
SAME_SITE_MILES = 0.12
STORE_NUMBER = re.compile(r"#\s*0*(\d+)\b")
GENERIC_WORDS = re.compile(
    r"\b(?:travel (?:stops?|centers?|centres?|plazas?)|truck stops?|"
    r"convenience stores?|country stores?|service stations?|gas stations?)\b",
    re.I,
)
ALIASES = {
    "travelcentersofamerica": "ta",
    "tapetro": "ta",
    "pilottravelcenters": "pilot",
    "caseysgeneralstore": "caseys",
}


def label(value):
    key = normalize(GENERIC_WORDS.sub("", STORE_NUMBER.sub("", value)))
    return ALIASES.get(key, key)


def miles(x, y, other_x, other_y):
    return 69.093 * math.hypot((x - other_x) * math.cos(math.radians((y + other_y) / 2)),
                              y - other_y)


def store_ref(tags):
    refs = set()
    for key in ("ref", "brand:ref"):
        raw = tags.get(key, "").strip()
        if re.fullmatch(r"#?\d+", raw):
            refs.add(int(raw.lstrip("#")))
    number = STORE_NUMBER.search(tags.get("name", ""))
    if number:
        refs.add(int(number[1]))
    return refs


def street_key(value):
    return normalize(re.sub(
        r"\b(ST|RD|AVE|BLVD|HWY|DR)\.?\b",
        lambda m: {"ST": "street", "RD": "road", "AVE": "avenue", "BLVD": "boulevard",
                   "HWY": "highway", "DR": "drive"}[m[1].upper()], value, flags=re.I,
    ))


class StateIndex:
    def __init__(self, snapshot, shape):
        self.shape = shape
        self.digest = snapshot["sha256"]
        self.by_label = defaultdict(list)
        self.places = defaultdict(list)
        self.exits = defaultdict(list)
        for site in snapshot["fuel"]:
            _, _, lon, lat, tags = site
            if tags.get("access") in {"no", "private"} or not self.shape.covers(Point(lon, lat)):
                continue
            labels = {label(tags[key]) for key in ("name", "brand", "operator") if tags.get(key)}
            for key in labels - {""}:
                self.by_label[key].append(site)
        for name, lon, lat in snapshot["places"]:
            if self.shape.covers(Point(lon, lat)):
                self.places[city_key(name)].append((lon, lat))
        for ref, lon, lat, roads in snapshot["exits"]:
            for road in roads:
                self.exits[road, normalize(ref)].append((lon, lat))


def match(rows, index, census):
    station = rows[0]
    city = city_key(station["City"])
    roads, exits = interchange(station["Address"])
    junctions = [point for road in roads for ref in exits for point in index.exits[road, ref]]
    possible = {}
    for row in rows:
        name = row["Truckstop Name"]
        number = STORE_NUMBER.search(name)
        for site in index.by_label.get(label(name), ()):
            kind, osm_id, lon, lat, tags = site
            if tags.get("addr:state", station["State"]).upper() != station["State"]:
                continue
            if tags.get("addr:city"):
                if city_key(tags["addr:city"]) != city:
                    continue
                city_evidence = "OSM address city"
            elif any(miles(lon, lat, *point) <= MAX_CITY_MILES for point in index.places.get(city, ())):
                city_evidence = "near matching OSM locality"
            else:
                continue
            refs = store_ref(tags)
            if number and refs and refs != {int(number[1])}:
                continue
            near_exit = any(miles(lon, lat, *point) <= MAX_EXIT_MILES for point in junctions)
            if roads and exits and not near_exit:
                continue
            osm_address = f"{tags.get('addr:housenumber', '')} {tags.get('addr:street', '')}"
            if census and miles(lon, lat, *census) <= MAX_CENSUS_MILES:
                score, reason = 4, "Census Exact range corroborated by matching OSM fuel feature"
            elif number and refs == {int(number[1])}:
                score, reason = 3, "operator and store number"
            elif address_type(station["Address"].strip()) == "street" and (
                street_key(osm_address) == street_key(station["Address"])
            ):
                score, reason = 2, "operator and exact OSM street address"
            elif near_exit:
                score, reason = 1, "operator and interstate exit"
            else:
                continue
            rank = (score, kind == "node", bool(tags.get("name")))
            if (kind, osm_id) not in possible or rank > possible[kind, osm_id][0]:
                possible[kind, osm_id] = rank, site, f"{reason}; {city_evidence}"
    if not possible:
        return None, "insufficient_independent_evidence"
    best = max(item[0][0] for item in possible.values())
    finalists = [item for item in possible.values() if item[0][0] == best]
    chosen = max(finalists, key=lambda item: (item[0], -item[1][1]))
    _, (_, _, lon, lat, _), evidence = chosen
    if any(miles(lon, lat, item[1][2], item[1][3]) > SAME_SITE_MILES for item in finalists):
        return None, "multiple_distinct_sites"
    return chosen[1], evidence


def census_matches(pilot):
    if pilot is None:
        return {}
    result = {}
    with pilot.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if (row["source"] == "US Census Public_AR_Current"
                    and row["evidence"].startswith("Census Exact address-range result:")):
                key = row["opis_station_id"]
                result[key] = (row["original_address"], row["city"], row["state"],
                               float(row["longitude"]), float(row["latitude"]))
    return result


def build(prices, sources, output, audit, pilot=None):
    by_id = defaultdict(list)
    with prices.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row["State"] in STATES:
                by_id[row["OPIS Truckstop ID"]].append(row)

    shapes = state_shapes()
    indexes = {}
    for path in sources:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        state = snapshot["state"]
        if state in indexes or snapshot["license"] != "ODbL-1.0":
            raise ValueError(f"Unexpected or repeated OSM source state: {state}")
        indexes[state] = StateIndex(snapshot, shapes[STATE_CODES[state]])
    candidates = census_matches(pilot)
    claimed = defaultdict(list)
    matches = {}
    reasons = {}
    for key, rows in by_id.items():
        row = rows[0]
        index = indexes.get(row["State"])
        if not index:
            reasons[key] = "extract_not_loaded"
            continue
        census = candidates.get(key)
        if census and (row["Address"], row["City"], row["State"]) != census[:3]:
            census = None
        site, reason = match(rows, index, census[3:] if census else None)
        reasons[key] = reason
        if site:
            claimed[tuple(site[:2])].append(key)
            matches[key] = site

    for keys in claimed.values():
        if len(keys) > 1:
            for key in keys:
                matches.pop(key)
                reasons[key] = "osm_feature_matches_multiple_opis_ids"

    catalog_rows = [FIELDS]
    audit_rows = [["opis_station_id", "state", "outcome"]]
    for key, rows in by_id.items():
        row = rows[0]
        audit_rows.append([key, row["State"], reasons[key]])
        if key not in matches:
            continue
        kind, osm_id, lon, lat, _ = matches[key]
        source = f"https://www.openstreetmap.org/{kind}/{osm_id}"
        evidence = f"{reasons[key]}; ODbL-1.0; OSM extract SHA-256 {indexes[row['State']].digest}"
        catalog_rows.append([key, row["Truckstop Name"], row["Address"], row["City"], row["State"],
                             lat, lon, source, "verified", "high",
                             address_type(row["Address"].strip()), evidence])
    atomic_write(output, csv_bytes(catalog_rows))
    atomic_write(audit, csv_bytes(audit_rows))
    counts = Counter(reasons[key] for key in by_id if key not in matches)
    return {"us_station_ids": len(by_id), "verified": len(matches),
            "unmatched": len(by_id) - len(matches), "unmatched_by_reason": dict(counts),
            "census_exact_candidates": len(candidates),
            "census_corroborated": sum(reasons[key].startswith("Census Exact") for key in matches),
            "states_loaded": sorted(indexes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prices", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("audit", type=Path)
    parser.add_argument("--osm", type=Path, nargs="+", required=True)
    parser.add_argument("--census-pilot", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.prices, args.osm, args.output, args.audit, args.census_pilot),
                     indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
