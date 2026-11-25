"""Build a verified station catalog from saved operator evidence, without network calls."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from os import path
from pathlib import Path
import re

from shapely.geometry import Point, shape

from .geocode import FIELDS, STATES, address_type, atomic_write, csv_bytes

ROOT = Path(__file__).resolve().parent.parent
LOVES_FEED = "https://www.loves.com/api/fetch_stores"
STATE_CODES = dict(zip(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(),
    "01 02 04 05 06 08 09 10 11 12 13 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42 44 45 46 47 48 49 50 51 53 54 55 56".split(),
))
NUMBERED = re.compile(r"#\s*0*(\d+)\b")


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def city_key(city):
    return normalize(re.sub(r"\b(ST|FT)\.?\s+", lambda m: {"ST": "Saint ", "FT": "Fort "}[m[1].upper()], city, flags=re.I))


def interchange(text):
    text = text.upper()
    roads = {f"I{int(number)}" for number in re.findall(r"\bI[ -]*(\d+)\b", text)}
    exits = {str(int(number)) + suffix for number, suffix in re.findall(
        r"\bEXIT\s*#?\s*(\d+)(?:[ -]?([A-Z])\b)?", text)}
    return roads, exits


def ta_name(text):
    return normalize(re.sub(r"#\s*\d+|\bTRAVEL CENT(?:ER|RE)S?\b", "", text, flags=re.I))


def identity(name):
    identifier = NUMBERED.search(name)
    operator = re.match(r"\s*LOVE['’]?S\b", name, re.I)
    if operator and identifier:
        return "loves", identifier[1]
    if re.match(r"\s*(TA|PETRO)\b", name, re.I):
        return "ta", ta_name(name)
    return None


def operator_snapshot(loves_file, ta_files):
    records = []
    sources = {}
    if loves_file:
        data = loves_file.read_bytes()
        sources[LOVES_FEED] = hashlib.sha256(data).hexdigest()
        for row in json.loads(data)["stores"]:
            if row["state"] not in STATES or not row["isLoveStore"]:
                continue
            if row["facilitySubtypeName"] != "Travel Stop":
                continue
            records.append({
                "operator": "loves", "key": str(row["number"]), "city": row["city"],
                "state": row["state"], "latitude": row["latitude"], "longitude": row["longitude"],
                "access": f"{row['highway'] or ''} Exit {row['exitNumber'] or ''}",
                "street": row["address1"], "source": LOVES_FEED,
            })
    for url, filename in ta_files:
        if not url.startswith("https://www.ta-petro.com/location/"):
            raise ValueError("Expected an official TA location URL")
        data = Path(filename).read_bytes()
        sources[url] = hashlib.sha256(data).hexdigest()
        for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', data.decode(), re.S):
            record = json.loads(block)
            if not isinstance(record, dict) or not {"geo", "address", "description", "name"} <= record.keys():
                continue
            address, geo = record["address"], record["geo"]
            records.append({
                "operator": "ta", "key": ta_name(record["name"]), "city": address["addressLocality"],
                "state": address["addressRegion"], "latitude": geo["latitude"], "longitude": geo["longitude"],
                "access": record["description"], "street": address["streetAddress"], "source": url,
            })
            break
        else:
            raise ValueError(f"No TA station coordinates found in {filename}")
    return {"records": records, "source_sha256": sources}


def state_shapes():
   
    path = ( ROOT / "fuel_routes" / "static" / "fuel_routes" / "geo" / "us-states.geojson")
    features = json.loads( path.read_text(encoding="utf-8") )["features"]
    return {feature["properties"]["STATE"]: shape(feature["geometry"]) for feature in features}


def match(station, candidates, shapes):
    key = identity(station["Truckstop Name"])
    if not key:
        return None, "no_supported_operator_identity"
    candidates = [record for record in candidates if (record["operator"], record["key"]) == key]
    if not candidates:
        return None, "operator_record_unavailable"
    state = station["State"]
    locality = [r for r in candidates if r["state"] == state
                and city_key(r["city"]) == city_key(station["City"])]
    if not locality:
        return None, "operator_city_or_state_conflict"
    if len(locality) != 1:
        return None, "multiple_operator_records"
    record = locality[0]
    roads, exits = interchange(station["Address"])
    source_roads, source_exits = interchange(record["access"])
    if ((roads and source_roads and roads.isdisjoint(source_roads))
            or (exits and source_exits and exits.isdisjoint(source_exits))):
        return None, "highway_or_exit_conflict"
    if key[0] == "ta" and not (roads & source_roads and exits & source_exits):
        return None, "named_site_needs_highway_and_exit"
    try:
        lat, lon = float(record["latitude"]), float(record["longitude"])
        valid = (math.isfinite(lat) and math.isfinite(lon)
                 and -90 <= lat <= 90 and -180 <= lon <= 180
                 and shapes[STATE_CODES[state]].covers(Point(lon, lat)))
    except (TypeError, ValueError, KeyError):
        valid = False
    if not valid:
        return None, "invalid_or_out_of_state_coordinate"
    return record, "verified"


def audit_reason(row, raw, status):
    if status != "no_supported_operator_identity":
        return status
    if row["match_status"] == "matched_unverified":
        return "census_address_range_without_station_identity"
    kind = row["address_type"]
    if kind == "street":
        return "census_no_match_and_no_operator_record"
    if kind == "highway_exit":
        if NUMBERED.search(raw["Truckstop Name"]):
            return "exit_and_store_number_without_supported_operator_feed"
        return "exit_without_verified_station_identity"
    if NUMBERED.search(raw["Truckstop Name"]):
        return "numbered_site_without_supported_operator_feed"
    if re.search(r"&|\bJCT\b|\bCORNER\b|\bAT\b", raw["Address"], re.I):
        return "intersection_without_verified_station"
    return "route_or_local_description_without_verified_station"


def osm_evidence(station, extract):
    if extract is None:
        return "extract_not_tested"
    name = normalize(station["Truckstop Name"])
    roads, exits = interchange(station["Address"])
    near_exits = [r for r in extract["exits"] if r["ref"].upper() in exits
                  and roads.intersection(r["interstates"])]
    evidence = []
    for site in extract["fuel"]:
        names = {normalize(site.get("name")), normalize(site.get("brand"))}
        if name and name in names:
            evidence.append(site["id"] + ":name")
        elif any(math.hypot((site["latitude"] - ramp["latitude"]) * 69.1,
                            (site["longitude"] - ramp["longitude"]) * 69.1 *
                            math.cos(math.radians(ramp["latitude"]))) <= 1.5
                 for ramp in near_exits):
            evidence.append(site["id"] + ":near_exit")
    if evidence:
        return ";".join(evidence)
    return "no_name_or_exit_candidate_in_tested_extract"


def run(prices, pilot, snapshot, output, audit, osm=None):
    raw = defaultdict(list)
    with prices.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            if row["State"] in STATES:
                raw[row["OPIS Truckstop ID"]].append(row)
    with pilot.open(newline="", encoding="utf-8-sig") as stream:
        baseline = {row["opis_station_id"]: row for row in csv.DictReader(stream)}
    source = json.loads(snapshot.read_text(encoding="utf-8"))
    indexed = defaultdict(list)
    for record in source["records"]:
        indexed[(record["operator"], record["key"])].append(record)
    shapes = state_shapes()
    expanded = dict(baseline)
    audit_rows = []
    proposed = defaultdict(list)
    diagnostics = {}
    osm_catalog = json.loads(osm.read_text(encoding="utf-8")) if osm else {}
    for key, rows in raw.items():
        identified = {identity(row["Truckstop Name"]) for row in rows} - {None}
        options = indexed[next(iter(identified))] if len(identified) == 1 else []
        matched, status = match(rows[0], options, shapes)
        if len(identified) > 1:
            matched, status = None, "conflicting_opis_operator_aliases"
        elif identified and identity(rows[0]["Truckstop Name"]) is None:
            alias = next(row for row in rows if identity(row["Truckstop Name"]))
            matched, status = match(alias, options, shapes)
        diagnostics[key] = status
        if matched:
            site = (matched["operator"], matched["key"], matched["state"], city_key(matched["city"]))
            proposed[site].append((key, matched))
    for group in proposed.values():
        if len(group) != 1:
            for key, _ in group:
                diagnostics[key] = "operator_site_shared_by_multiple_opis_ids"
            continue
        key, record = group[0]
        if baseline.get(key, {}).get("match_status") == "verified":
            continue
        row = raw[key][0]
        expanded[key] = dict(zip(FIELDS, [
            key, row["Truckstop Name"], row["Address"], row["City"], row["State"],
            record["latitude"], record["longitude"], record["source"], "verified", "high",
            address_type(row["Address"]),
            f"Operator {record['operator']} identity {record['key']} in {record['city'].strip()}, "
            f"{record['state']}. Published address {record['street']}. Published access {record['access']}. "
            f"Source SHA-256 {source['source_sha256'][record['source']]}",
        ]))
    for key, row in baseline.items():
        station = raw[key][0]
        current = expanded[key]["match_status"]
        reason = ("preexisting_operator_verification" if row["match_status"] == "verified" else
                  "new_operator_verification" if current == "verified" else
                  audit_reason(row, station, diagnostics[key]))
        osm_status = osm_evidence(station, osm_catalog.get(station["State"]))
        number = NUMBERED.search(station["Truckstop Name"])
        roads, exits = interchange(station["Address"])
        audit_rows.append((key, station["Truckstop Name"], station["Address"], station["City"], station["State"],
                           row["address_type"], number[1] if number else "", " ".join(sorted(roads)),
                           " ".join(sorted(exits)), row["match_status"], current, reason, osm_status))
    atomic_write(output, csv_bytes([FIELDS] + [[row[field] for field in FIELDS] for row in expanded.values()]))
    atomic_write(audit, csv_bytes([["opis_station_id", "station_name", "original_address", "city", "state",
                                    "address_type", "store_number", "interstates", "exits", "original_status",
                                    "new_status", "reason", "osm_review_candidates"]]
                                  + audit_rows))
    return Counter(row["match_status"] for row in expanded.values())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("snapshot")
    prepare.add_argument("output", type=Path)
    prepare.add_argument("--loves", type=Path)
    prepare.add_argument("--ta", nargs=2, action="append", default=[], metavar=("URL", "HTML"))
    build = commands.add_parser("build")
    for name in ("prices", "pilot", "snapshot", "output", "audit"):
        build.add_argument(name, type=Path)
    build.add_argument("--osm", type=Path)
    args = parser.parse_args()
    if args.command == "snapshot":
        atomic_write(args.output, (json.dumps(operator_snapshot(args.loves, args.ta), indent=2) + "\n").encode())
    else:
        print(dict(run(args.prices, args.pilot, args.snapshot, args.output, args.audit, args.osm)))
