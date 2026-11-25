"""Deterministic, resumable 100-station geocoding pilot."""
import argparse
from collections import defaultdict
import csv
import hashlib
import io
import math
from pathlib import Path
import re
import subprocess
from tempfile import NamedTemporaryFile

from filelock import FileLock

STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
FIELDS = ["opis_station_id", "station_name", "original_address", "city", "state",
          "latitude", "longitude", "source", "match_status", "confidence",
          "address_type", "evidence"]
CENSUS = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def address_type(address):
    if re.search(r"\bEXIT\b", address, re.I):
        return "highway_exit"
    if re.match(r"^\d+\s+[A-Z]", address, re.I) and not re.search(r"[&/@]|\bCORNER\b", address, re.I):
        return "street"
    return "ambiguous"


def sample(path):
    groups = defaultdict(list)
    seen = set()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            key = row["OPIS Truckstop ID"]
            if row["State"] in STATES and key not in seen:
                seen.add(key)
                groups[address_type(row["Address"])].append(row)
    selected = []
    for kind, quota in [("street", 4), ("highway_exit", 55), ("ambiguous", 41)]:
        ranked = sorted(groups[kind], key=lambda row: hashlib.sha256(
            ("spotter-pilot-v1:" + row["OPIS Truckstop ID"]).encode()).digest())
        if len(ranked) < quota:
            raise ValueError(f"Insufficient records for {kind}")
        selected.extend(ranked[:quota])
    return selected


def csv_bytes(rows):
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue().encode()


def atomic_write(path, payload):
    with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        staging = Path(stream.name)
        stream.write(payload)
    try:
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def parse_batch(payload, expected):
    results = {}
    for row in csv.reader(io.StringIO(payload.decode("utf-8-sig"))):
        if len(row) < 3 or row[0] not in expected or row[0] in results:
            raise ValueError("Unexpected Census response record")
        if row[2] == "Match":
            if len(row) < 8:
                raise ValueError("Incomplete Census match")
            lon, lat = map(float, row[5].split(","))
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("Invalid Census coordinate")
        elif row[2] not in {"No_Match", "Tie"}:
            raise ValueError(f"Unknown Census status: {row[2]}")
        results[row[0]] = row
    if results.keys() != expected:
        raise ValueError("Census returned an incomplete batch")
    return results


def run(source, output, cache, reviews=None):
    selected = sample(source)
    request = [[row["OPIS Truckstop ID"], row["Address"], row["City"].strip(), row["State"], ""]
               for row in selected if address_type(row["Address"]) == "street"]
    payload = csv_bytes(request)
    cache.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(b"Public_AR_Current\0" + payload).hexdigest()[:16]
    submitted = cache / f"{digest}-input.csv"
    saved = cache / f"{digest}-response.csv"
    expected = {row[0] for row in request}
    batch = {}
    failure = None
    try:
        with FileLock(cache / f"{digest}.lock"):
            if saved.exists():
                batch = parse_batch(saved.read_bytes(), expected)
            else:
                atomic_write(submitted, payload)
                response = subprocess.run(
                    ["curl", "--silent", "--show-error", "--fail", "--max-time", "90",
                     "--form", f"addressFile=@{submitted};type=text/csv",
                     "--form", "benchmark=Public_AR_Current", CENSUS],
                    capture_output=True, check=True)
                batch = parse_batch(response.stdout, expected)
                atomic_write(saved, response.stdout)
    except (subprocess.CalledProcessError, ValueError) as exc:
        failure = exc.stderr.decode(errors="replace").strip() if isinstance(
            exc, subprocess.CalledProcessError) else str(exc)
    verified = {}
    if reviews:
        with reviews.open(newline="", encoding="utf-8-sig") as stream:
            for review in csv.DictReader(stream):
                key = review["opis_station_id"]
                if key in verified or key not in {row["OPIS Truckstop ID"] for row in selected}:
                    raise ValueError(f"Invalid review ID: {key}")
                lat, lon = float(review["latitude"]), float(review["longitude"])
                if not (math.isfinite(lat) and math.isfinite(lon) and
                        -90 <= lat <= 90 and -180 <= lon <= 180 and
                        review["source"].startswith("https://") and review["evidence"].strip()):
                    raise ValueError(f"Invalid review evidence: {key}")
                verified[key] = review
    records = []
    for row in selected:
        key = row["OPIS Truckstop ID"]
        kind = address_type(row["Address"])
        record = dict(zip(FIELDS, [key, row["Truckstop Name"], row["Address"],
                                  row["City"], row["State"], "", "", "",
                                  "unresolved", "none", kind, "Manual review required"]))
        if kind == "street":
            record.update(source="US Census Public_AR_Current",
                          evidence="Census request failed" if failure else "Census returned no match")
            match = batch.get(key)
            if match and match[2] == "Match":
                lon, lat = match[5].split(",")
                record.update(latitude=lat, longitude=lon, match_status="matched_unverified",
                              confidence="medium" if match[3] == "Exact" else "low",
                              evidence=f"Census {match[3]} address-range result: {match[4]}")
            elif match and match[2] == "Tie":
                record.update(match_status="uncertain", evidence="Census returned multiple candidates")
        if key in verified:
            record.update({field: verified[key][field] for field in
                           ("latitude", "longitude", "source", "evidence")})
            record.update(match_status="verified", confidence="high")
        records.append(record)
    atomic_write(output, csv_bytes([FIELDS] + [[item[field] for field in FIELDS] for item in records]))
    if failure:
        raise SystemExit(f"Census error: {failure}. CSV saved; rerun to retry.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path, default=Path(".geocode-cache"))
    parser.add_argument("--reviews", type=Path)
    args = parser.parse_args()
    run(args.source, args.output, args.cache, args.reviews)
