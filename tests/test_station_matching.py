import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.geocode import FIELDS, csv_bytes
from scripts.station_matching import identity, match, osm_evidence, run, state_shapes

ROOT = Path(__file__).resolve().parent
STATION = {"OPIS Truckstop ID": "123", "Truckstop Name": "LOVE'S TRAVEL STOP #0999999",
           "Address": "I-44, EXIT 189", "City": "Fixture City ", "State": "MO"}
SOURCE = "https://www.loves.com/api/fetch_stores"
RECORD = {"operator": "loves", "key": "999999", "state": "MO", "city": "FIXTURE CITY",
          "latitude": 38.0, "longitude": -92.0, "access": "I-44 Exit 189",
          "street": "100 Test Road", "source": SOURCE}


class StationMatchingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shapes = state_shapes()

    def test_operator_number_locality_and_exit(self):
        self.assertEqual(identity(STATION["Truckstop Name"]), ("loves", "999999"))
        self.assertEqual(match(STATION, [RECORD], self.shapes), (RECORD, "verified"))
        self.assertEqual(match(STATION, [{**RECORD, "key": "999998"}], self.shapes)[1],
                         "operator_record_unavailable")
        self.assertEqual(match(STATION, [{**RECORD, "city": "Springfield"}], self.shapes)[1],
                         "operator_city_or_state_conflict")
        for access in ["I-44 Exit 190", "I-70 Exit 189"]:
            self.assertEqual(match(STATION, [{**RECORD, "access": access}], self.shapes)[1],
                             "highway_or_exit_conflict")

    def test_ta_name_without_number_needs_route_and_exit(self):
        station = {**STATION, "Truckstop Name": "TA Fixture City Travel Center"}
        candidate = {**RECORD, "operator": "ta", "key": "tafixturecity", "access": "I-44"}
        self.assertEqual(match(station, [candidate], self.shapes)[1],
                         "named_site_needs_highway_and_exit")
        self.assertEqual(match(station, [{**candidate, "access": "I-44 Exit 189"}], self.shapes)[1],
                         "verified")

    def test_bad_and_out_of_state_coordinates(self):
        for lat, lon in [(None, -91), ("nan", -91), (91, -91), (39.1, -84.5),
                         (-92.0, 38.0)]:
            with self.subTest(lat=lat, lon=lon):
                candidate = {**RECORD, "latitude": lat, "longitude": lon}
                self.assertEqual(match(STATION, [candidate], self.shapes)[1],
                                 "invalid_or_out_of_state_coordinate")

    def test_multiple_candidates_rejected(self):
        self.assertEqual(match(STATION, [RECORD, RECORD], self.shapes)[1],
                         "multiple_operator_records")

    def test_osm_exit_proximity_is_evidence_only(self):
        extract = {"fuel": [{"id": "node/1", "latitude": 38.0, "longitude": -92.0}],
                   "exits": [{"ref": "189", "interstates": ["I44"], "latitude": 38.0, "longitude": -92.0}]}
        self.assertEqual(osm_evidence(STATION, extract), "node/1:near_exit")
        self.assertIsNone(match(STATION, [], self.shapes)[0])
        extract["exits"][0]["interstates"] = ["I70"]
        self.assertEqual(osm_evidence(STATION, extract), "no_name_or_exit_candidate_in_tested_extract")

    def test_catalog_contains_provenance_and_refuses_duplicate_opis_mapping(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prices, pilot, snapshot, output, audit = [root / name for name in
                                                        ("prices", "pilot", "snapshot", "output", "audit")]
            pilot.write_bytes(csv_bytes([FIELDS]))
            checksum = "a" * 64
            snapshot.write_text(json.dumps({"records": [RECORD], "source_sha256": {SOURCE: checksum}}))
            rows = [list(STATION), list(STATION.values())]
            prices.write_bytes(csv_bytes(rows))
            self.assertEqual(run(prices, pilot, snapshot, output, audit)["verified"], 1)
            with output.open(newline="") as stream:
                result = next(csv.DictReader(stream))
            self.assertEqual(result["source"], SOURCE)
            self.assertTrue(result["evidence"].endswith(checksum))
            prices.write_bytes(csv_bytes(rows + [list({**STATION, "OPIS Truckstop ID": "456"}.values())]))
            self.assertEqual(run(prices, pilot, snapshot, output, audit)["verified"], 0)
