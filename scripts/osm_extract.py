"""Extract fuel POIs and exit nodes from local Geofabrik PBFs for manual review."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import osmium
from shapely.geometry import Polygon

from .geocode import STATES, atomic_write


class FuelFeatures(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.fuel = []
        self.exits = {}
        self.road_refs = {}

    def store(self, obj, kind, lat, lon):
        self.fuel.append({
            "id": f"{kind}/{obj.id}", "name": obj.tags.get("name"),
            "brand": obj.tags.get("brand"), "ref": obj.tags.get("ref"),
            "city": obj.tags.get("addr:city"), "website": obj.tags.get("website"),
            "latitude": lat, "longitude": lon,
        })

    def node(self, node):
        if not node.location.valid():
            return
        if node.tags.get("amenity") == "fuel":
            self.store(node, "node", node.location.lat, node.location.lon)
        if node.tags.get("highway") == "motorway_junction" and node.tags.get("ref"):
            self.exits[node.id] = {
                "id": f"node/{node.id}", "ref": node.tags["ref"],
                "latitude": node.location.lat, "longitude": node.location.lon,
            }

    def way(self, way):
        if way.tags.get("highway") in {"motorway", "motorway_link"}:
            refs = re.findall(r"\bI[ -]*(\d+)\b", way.tags.get("ref", ""))
            if refs:
                for node in way.nodes:
                    if node.ref in self.exits:
                        self.road_refs.setdefault(node.ref, set()).update(f"I{int(ref)}" for ref in refs)
        if way.tags.get("amenity") == "fuel" and way.is_closed() and len(way.nodes) >= 4:
            if all(node.location.valid() for node in way.nodes):
                point = Polygon([(node.lon, node.lat) for node in way.nodes]).representative_point()
                self.store(way, "way", point.y, point.x)


def extract(path):
    features = FuelFeatures()
    features.apply_file(str(path), locations=True, idx="flex_mem")
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    for key, entry in features.exits.items():
        entry["interstates"] = sorted(features.road_refs.get(key, set()))
    return {"sha256": checksum, "fuel": features.fuel, "exits": list(features.exits.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pbf", nargs=2, action="append", required=True, metavar=("STATE", "PATH"))
    args = parser.parse_args()
    if any(state not in STATES for state, _ in args.pbf):
        parser.error("Use two-letter US state codes")
    catalog = {state: extract(Path(path)) for state, path in args.pbf}
    atomic_write(args.output, (json.dumps(catalog, separators=(",", ":")) + "\n").encode())
