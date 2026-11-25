from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIClient

from fuel_routes.services.optimizer import Stop, optimize
from fuel_routes.services.routing import TripError, driving_route, provider_json


class AuditRegressionTests(SimpleTestCase):
    path = "/api/v1/fuel-routes/"
    query = {"start": {"latitude": 36.154, "longitude": -95.9928},
             "finish": {"latitude": 39.1031, "longitude": -84.512}}

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def test_invalid_host_and_oversize_request_are_rejected_before_providers(self):
        with patch("fuel_routes.services.routing.requests.get") as provider:
            bad_host = self.client.post(self.path, self.query, format="json",
                                        HTTP_HOST="unauthorized.example")
            large = self.client.post(self.path, {"start": "a" * 5000}, format="json")
        provider.assert_not_called()
        self.assertEqual(bad_host.status_code, 400)
        self.assertEqual((large.status_code, large.json()["code"]), (413, "request_too_large"))

    def test_overflowing_json_coordinate_is_rejected_before_calling_provider(self):
        query = {**self.query, "start": {"latitude": 10**400, "longitude": -95.9928}}
        with patch("fuel_routes.services.routing.requests.get") as provider:
            response = self.client.post(self.path, query, format="json")
        provider.assert_not_called()
        self.assertEqual(response.status_code, 400)

    def test_malformed_provider_code_returns_structured_error(self):
        with patch("fuel_routes.services.routing.provider_json", return_value={"code": []}):
            response = self.client.post(self.path, self.query, format="json")
        self.assertEqual((response.status_code, response.json()["code"]), (502, "provider_error"))

    def test_osrm_limits_road_snapping_and_uses_a_single_http_request(self):
        response = Mock(status_code=400)
        response.json.return_value = {"code": "NoSegment"}
        with patch("fuel_routes.services.routing.requests.get", return_value=response) as provider:
            with self.assertRaises(TripError) as error:
                driving_route((-95.9928, 36.154), (-84.512, 39.1031))
        self.assertEqual(error.exception.code, "no_driving_route")
        provider.assert_called_once()
        self.assertEqual(provider.call_args.kwargs["params"]["radiuses"], "1000;1000")
        self.assertFalse(provider.call_args.kwargs["allow_redirects"])

    def test_redirect_is_a_provider_error(self):
        with patch("fuel_routes.services.routing.requests.get", return_value=Mock(status_code=302)) as provider:
            with self.assertRaises(TripError) as error:
                provider_json("https://example.invalid/route", {})
        self.assertEqual((error.exception.status, error.exception.code), (502, "provider_error"))
        provider.assert_called_once()

    def test_malformed_verified_station_returns_structured_error(self):
        route = {"code": "Ok", "routes": [{"distance": 856000, "geometry": {
            "type": "LineString", "coordinates": [[-95.9928, 36.154], [-84.512, 39.1031]]}}]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prices = root / "prices.csv"
            prices.write_text("OPIS Truckstop ID,Retail Price\ntest,3.00\n")
            for name, row in (
                ("invalid_coordinate", "Fixture station,NaN"),
                ("empty_name", ",37.0"),
            ):
                with self.subTest(name=name):
                    catalog = root / f"{name}.csv"
                    catalog.write_text("opis_station_id,match_status,source,station_name,latitude,longitude\n"
                                       f"test,verified,https://example.invalid/station,{row},-95.5\n")
                    with self.settings(PILOT_CSV=catalog, PRICE_CSV=prices):
                        with patch("fuel_routes.services.routing.provider_json", return_value=route):
                            response = self.client.post(self.path, self.query, format="json")
                    self.assertEqual((response.status_code, response.json()["code"]),
                                     (503, "catalog_unavailable"))

    def test_plan_skips_a_zero_purchase_visit(self):
        redundant = Stop("redundant", Decimal(200), Decimal(0), Decimal(9))
        needed = Stop("needed", Decimal(450), Decimal(2), Decimal(3))
        cost, plan = optimize(Decimal(650), [redundant, needed])
        self.assertEqual(plan, [(needed, Decimal("15.4"))])
        self.assertEqual(cost, Decimal("46.20"))
