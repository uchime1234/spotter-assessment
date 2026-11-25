from collections import Counter
import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts.geocode import address_type, csv_bytes, parse_batch, run, sample

def synthetic_input(path):
    rows = [["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State"]]
    for template, count in (("{n} Example Road", 4), ("I-70, EXIT {n}", 55), ("US-{n}", 41)):
        for number in range(1, count + 1):
            key = f"test-{len(rows)}"
            rows.append([key, f"Fictional Fuel {key}", template.format(n=number), "Fixture City", "MO"])
    rows.extend([rows[1], ["test-ca", "Fictional excluded station", "15 Example Road", "Test", "ON"]])
    path.write_bytes(csv_bytes(rows))


class GeocodingTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "synthetic-input.csv"
        synthetic_input(self.source)

    def test_sample_covers_all_address_types_and_unique_ids(self):
        selected = sample(self.source)
        self.assertEqual(len({row["OPIS Truckstop ID"] for row in selected}), 100)
        self.assertEqual(Counter(address_type(row["Address"]) for row in selected),
                         {"street": 4, "highway_exit": 55, "ambiguous": 41})
        self.assertEqual(selected, sample(self.source))

    def test_batch_rejects_missing_rows_and_invalid_coordinate(self):
        with self.assertRaises(ValueError):
            parse_batch(csv_bytes([["a", "input", "No_Match"]]), {"a", "b"})
        row = ["a", "input", "Match", "Exact", "output", "-98,99", "id", "L"]
        with self.assertRaises(ValueError):
            parse_batch(csv_bytes([row]), {"a"})

    def test_restart_uses_cached_provider_response_and_keeps_misses_blank(self):
        sample_ids = [row["OPIS Truckstop ID"] for row in sample(self.source)
                      if address_type(row["Address"]) == "street"]
        raw = csv_bytes([[key, "input", "No_Match"] for key in sample_ids])
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out.csv"
            with patch("scripts.geocode.subprocess.run") as provider:
                provider.return_value.stdout = raw
                run(self.source, output, root / "cache")
                before = output.read_bytes()
                run(self.source, output, root / "cache")
                self.assertEqual(before, output.read_bytes())
                provider.assert_called_once()
            with output.open(newline="") as stream:
                self.assertTrue(all(not row["latitude"] and not row["longitude"]
                                    for row in csv.DictReader(stream)))
