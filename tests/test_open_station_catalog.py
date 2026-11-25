from unittest import TestCase

from shapely.geometry import box

from scripts.open_station_catalog import StateIndex, match


class OpenStationMatchingTests(TestCase):
    station = {"Truckstop Name": "Example Fuel #24", "City": "Example City",
               "State": "MO", "Address": "I-44, EXIT 189"}
    tags = {"name": "Example Fuel", "addr:city": "Example City"}

    def index(self, *sites):
        snapshot = {"sha256": "fixture", "fuel": sites, "places": [],
                    "exits": [["189", -91.7, 38.0, ["I44"]]]}
        return StateIndex(snapshot, box(-92, 37, -91, 39))

    def test_matching_operator_at_correct_linked_exit(self):
        site = ["node", 1, -91.7, 38.0, self.tags]
        matched, why = match([self.station], self.index(site), None)
        self.assertEqual(matched, site)
        self.assertIn("interstate exit", why)
        wrong_route = {**self.station, "Address": "I-70, EXIT 189"}
        self.assertIsNone(match([wrong_route], self.index(site), None)[0])

    def test_conflicting_store_number_or_locality_is_not_verified(self):
        for tags in ({**self.tags, "ref": "25"}, {**self.tags, "addr:city": "Other City"}):
            with self.subTest(tags=tags):
                self.assertIsNone(match([self.station], self.index(["node", 1, -91.7, 38.0, tags]), None)[0])

    def test_distinct_candidate_sites_are_rejected(self):
        sites = (["node", 1, -91.7, 38.0, self.tags],
                 ["node", 2, -91.69, 38.0, self.tags])
        self.assertEqual(match([self.station], self.index(*sites), None),
                         (None, "multiple_distinct_sites"))

    def test_exact_census_needs_station_identity_and_returns_poi_coordinates(self):
        row = {**self.station, "Address": "123 Sample Street"}
        site = ["node", 1, -91.7, 38.0, self.tags]
        self.assertIsNone(match([row], self.index(), (-91.701, 38.0))[0])
        matched, why = match([row], self.index(site), (-91.701, 38.0))
        self.assertEqual(matched, site)
        self.assertIn("Census Exact", why)

    def test_private_fuel_feature_is_excluded(self):
        site = ["node", 1, -91.7, 38.0, {**self.tags, "access": "private"}]
        self.assertIsNone(match([self.station], self.index(site), None)[0])
