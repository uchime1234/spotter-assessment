from django.urls import path

from .views import fuel_route

urlpatterns = [path("fuel-routes/", fuel_route, name="fuel-route")]
