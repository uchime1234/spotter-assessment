"""Normalize local OpenStreetMap PBFs into an ODbL source snapshot."""
import argparse
import hashlib
import json
from pathlib import Path

from .geocode import STATES, atomic_write
from .station_matching import interchange

PLACES = ("city", "town", "village", "hamlet", "suburb", "locality")
TAGS = (
    ("amenity", "fuel"),
    ("highway", "motorway_junction"),
    ("highway", "motorway"),
    ("highway", "motorway_link"),
    *(("place", value) for value in PLACES),
)
FUEL_TAGS = ("name", "brand", "operator", "ref", "brand:ref", "addr:city",
             "addr:state", "addr:housenumber", "addr:street", "access", "hgv")


def extract(path):
    import osmium
    from shapely.geometry import Polygon

    fuel, places = [], []
    exits, roads = {}, {}
    processor = (osmium.FileProcessor(str(path)).with_locations("flex_mem")
                 .with_filter(osmium.filter.TagFilter(*TAGS)))
    for obj in processor:
        tags = obj.tags
        if obj.is_node() and obj.location.valid():
            lon, lat = obj.location.lon, obj.location.lat
            if tags.get("place") in PLACES and tags.get("name"):
                places.append([tags["name"], lon, lat])
            if tags.get("highway") == "motorway_junction" and tags.get("ref"):
                exits[obj.id] = [tags["ref"], lon, lat]
            if tags.get("amenity") == "fuel":
                fuel.append(["node", obj.id, lon, lat,
                             {tag: tags[tag] for tag in FUEL_TAGS if tag in tags}])
        elif obj.is_way():
            if tags.get("highway") in {"motorway", "motorway_link"}:
                refs, _ = interchange(tags.get("ref", ""))
                if refs:
                    for node in obj.nodes:
                        if node.ref in exits:
                            roads.setdefault(node.ref, set()).update(refs)
            if tags.get("amenity") == "fuel" and obj.is_closed() and len(obj.nodes) >= 4:
                if all(node.location.valid() for node in obj.nodes):
                    polygon = Polygon([(node.lon, node.lat) for node in obj.nodes])
                    if polygon.is_valid and polygon.area > 0:
                        point = polygon.representative_point()
                        fuel.append(["way", obj.id, point.x, point.y,
                                     {tag: tags[tag] for tag in FUEL_TAGS if tag in tags}])
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "license": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "source": "https://download.geofabrik.de/north-america/us.html",
        "sha256": digest,
        "fuel": fuel,
        "places": places,
        "exits": [[*entry, sorted(roads[key])] for key, entry in exits.items() if key in roads],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pbf", nargs=2, metavar=("STATE", "PATH"), required=True)
    args = parser.parse_args()
    state, path = args.pbf
    if state not in STATES:
        parser.error("Use a two-letter US state code.")
    snapshot = extract(Path(path))
    snapshot["state"] = state
    atomic_write(args.output, json.dumps(snapshot, separators=(",", ":")).encode())
    print(f"{state}: {len(snapshot['fuel'])} fuel features, {len(snapshot['exits'])} linked exits")


if __name__ == "__main__":
    main()
