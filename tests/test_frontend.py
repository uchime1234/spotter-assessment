from django.contrib.staticfiles import finders
from django.test import SimpleTestCase, override_settings
from django.urls import reverse


class RoutePlannerPageTests(SimpleTestCase):
    @override_settings(SYNTHETIC_CATALOG=True)
    def test_home_renders_planner_for_the_existing_api(self):
        response = self.client.get(reverse("route-planner"))

        self.assertTemplateUsed(response, "fuel_routes/planner.html")
        self.assertContains(response, f'action="{reverse("fuel-route")}"')
        self.assertContains(response, 'name="start"')
        self.assertContains(response, 'name="finish"')
        self.assertContains(response, 'id="route-map"')
        self.assertContains(response, 'id="load-demo"')
        self.assertContains(response, 'data-mode="synthetic"')
        self.assertContains(response, "Never use for navigation.")

    @override_settings(SYNTHETIC_CATALOG=False)
    def test_home_labels_the_configured_catalog(self):
        response = self.client.get(reverse("route-planner"))

        self.assertContains(response, 'data-mode="configured"')
        self.assertContains(response, "Authorized real data")
        self.assertContains(response, "Detour mileage is estimated.")
        self.assertNotContains(response, "Never use for navigation.")

    def test_planner_static_assets_are_discoverable(self):
        for asset in ("planner.css", "planner.js", "vendor/leaflet/leaflet.css",
                      "vendor/leaflet/leaflet.js", "geo/us-states.geojson"):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(f"fuel_routes/{asset}"))
