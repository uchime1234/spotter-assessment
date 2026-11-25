from django.urls import include, path

from fuel_routes.views import route_planner

urlpatterns = [
    path("", route_planner, name="route-planner"),
    path("api/v1/", include("fuel_routes.urls")),
]
