from decimal import Decimal
from itertools import combinations
from random import Random
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient
import requests

from fuel_routes.services.optimizer import Stop, optimize


def stop(key, mile, price, detour=0):
    return Stop(key, Decimal(mile), Decimal(detour), Decimal(price))


class OptimizerTests(SimpleTestCase):
    def test_cheapest_reachable_can_cost_more(self):
        # The cheapest station adds a 20-mile round trip that outweighs its price advantage.
        result = optimize(Decimal(900), [stop("early", 200, "2.99", 10),
                                         stop("bridge", 450, 3),
                                         stop("last", 700, 10)])
        self.assertEqual(result, (Decimal(120), [(stop("bridge", 450, 3), Decimal(40))]))

    def test_exact_range_and_detour_misses(self):
        self.assertEqual(optimize(Decimal(500), []), (Decimal(0), []))
        self.assertIsNone(optimize(Decimal(501), []))
        self.assertIsNone(optimize(Decimal(600), [stop("too_far", 495, 1, 6)]))

    def test_matches_exhaustive_small_integer_fuel_oracle(self):
        random = Random(13)
        for _ in range(25):
            miles = Decimal(850)
            stations = [stop(str(i), i * 150, random.randint(1, 7), random.choice([0, 10, 50]))
                        for i in range(1, 5)]
            best = None
            for count in range(len(stations) + 1):
                for subset in combinations(stations, count):
                    journey = [stop("start", 0, 0), *subset, stop("end", miles, 0)]
                    costs = {50: Decimal(0)}
                    for origin, target in zip(journey, journey[1:]):
                        burn = int((target.mile - origin.mile + origin.detour + target.detour) / 10)
                        future = {}
                        for arrival, cost in costs.items():
                            limit = 50 if origin.id != "start" else arrival
                            for departure in range(max(arrival, burn), limit + 1):
                                balance = departure - burn
                                amount = cost + (departure - arrival) * origin.price
                                future[balance] = min(future.get(balance, amount), amount)
                        costs = future
                    for amount in costs.values():
                        best = amount if best is None else min(best, amount)
            result = optimize(miles, stations)
            self.assertEqual(None if result is None else result[0], best)
            if result:
                fuel, previous = Decimal(50), stop("start", 0, 0)
                for target, gallons in result[1] + [(stop("end", miles, 0), Decimal(0))]:
                    fuel -= (target.mile - previous.mile + previous.detour + target.detour) / 10
                    self.assertGreaterEqual(fuel, 0)
                    fuel += gallons
                    self.assertLessEqual(fuel, 50)
                    previous = target


class APITests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        fixtures = settings.BASE_DIR / "fixtures"
        context = self.settings(PILOT_CSV=fixtures / "synthetic-stations.csv",
                                PRICE_CSV=fixtures / "synthetic-prices.csv",
                                SYNTHETIC_CATALOG=True)
        context.enable()
        self.addCleanup(context.disable)
    path = "/api/v1/fuel-routes/"
    query = {"start": {"latitude": 36.154, "longitude": -95.9928},
             "finish": {"latitude": 39.1031, "longitude": -84.512}}

    def test_verified_stop_geometry_and_cache(self):
        coordinates = [[-95.9928, 36.154], [-91.5, 38.0], [-84.512, 39.1031]]
        payload = {"code": "Ok", "routes": [{
            "distance": 743 * 1609.344,
            "geometry": {"type": "LineString", "coordinates": coordinates},
        }]}
        with patch("fuel_routes.services.routing.provider_json", return_value=payload) as route:
            first = self.client.post(self.path, self.query, format="json")
            second = self.client.post(self.path, self.query, format="json")
        route.assert_called_once()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["catalog_mode"], "synthetic")
        self.assertEqual(first.json()["geometry"]["coordinates"], coordinates)
        self.assertEqual([s["opis_station_id"] for s in first.json()["fuel_stops"]], ["fixture-001"])

    def test_no_route_and_timeout(self):
        with patch("fuel_routes.services.routing.provider_json", return_value={"code": "NoRoute"}):
            response = self.client.post(self.path, self.query, format="json")
        self.assertEqual((response.status_code, response.json()["code"]), (422, "no_driving_route"))
        with patch("fuel_routes.services.routing.requests.get", side_effect=requests.Timeout):
            response = self.client.post(self.path, self.query, format="json")
        self.assertEqual((response.status_code, response.json()["code"]), (504, "provider_timeout"))

    def test_no_feasible_plan(self):
        payload = {"code": "Ok", "routes": [{"distance": 2000 * 1609.344,
            "geometry": {"type": "LineString", "coordinates": [[-95.9928, 36.154], [-84.512, 39.1031]]}}]}
        with patch("fuel_routes.services.routing.provider_json", return_value=payload):
            response = self.client.post(self.path, self.query, format="json")
        self.assertEqual((response.status_code, response.json()["code"]),
                         (422, "no_feasible_fuel_plan"))

    def test_invalid_and_non_us_coordinates_fail_before_routing(self):
        with patch("fuel_routes.services.routing.provider_json") as provider:
            invalid = self.client.post(self.path, {}, format="json")
            outside = self.client.post(self.path, {
                **self.query, "start": {"latitude": 43.65, "longitude": -79.38}}, format="json")
        provider.assert_not_called()
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(outside.json()["code"], "outside_us")

    def test_text_address_and_coordinate_can_be_mixed(self):
        address = {"result": {"addressMatches": [{"coordinates": {"x": -95.99, "y": 36.15}}]}}
        route = {"code": "Ok", "routes": [{"distance": 400 * 1609.344,
            "geometry": {"type": "LineString", "coordinates": [[-95.99, 36.15], [-84.512, 39.1031]]}}]}
        with patch("fuel_routes.services.routing.provider_json", side_effect=[address, route]) as provider:
            response = self.client.post(self.path, {
                **self.query, "start": "Example full address, Tulsa, OK"}, format="json")
        self.assertEqual(provider.call_count, 2)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["estimated_fuel_purchases_usd"], "0.00")
