from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.shortcuts import render
from django.views.decorators.http import require_safe
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .serializers import Journey
from .services.optimizer import MPG, TANK, optimize
from .services.routing import TripError, candidates, catalog, driving_route, resolve


@require_safe
def route_planner(request):
    return render(request, "fuel_routes/planner.html", {
        "synthetic_catalog": settings.SYNTHETIC_CATALOG,
        "tank_gallons": int(TANK),
        "initial_gallons": int(TANK),
        "miles_per_gallon": int(MPG),
        "vehicle_range": int(TANK * MPG),
    })


@api_view(["POST"])
def fuel_route(request):
    try:
        # Let Django check the body size before DRF reads the JSON stream.
        request.body
    except RequestDataTooBig:
        return Response({"code": "request_too_large", "detail": "Request body exceeds 4096 bytes."},
                        status=413)
    query = Journey(data=request.data)
    query.is_valid(raise_exception=True)
    try:
        start = resolve(query.validated_data["start"])
        finish = resolve(query.validated_data["finish"])
        geometry, miles = driving_route(start, finish)
        rows, index = catalog()
        nearby = candidates(geometry, miles, rows, index) if miles > TANK * MPG else []
        result = optimize(Decimal(str(miles)), nearby)
        if result is None:
            raise TripError("no_feasible_fuel_plan", 422,
                            "No feasible fueling plan with the available verified stations.")
    except TripError as exc:
        return Response({"code": exc.code, "detail": str(exc)}, status=exc.status)
    cost, plan = result
    records = {row["opis_station_id"]: row for row in rows}
    stops = []
    for station, gallons in plan:
        row = records[station.id]
        stops.append({
            "opis_station_id": station.id,
            "station_name": row["station_name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "source": row["source"],
            "route_mile": round(station.mile, 3),
            "round_trip_detour_miles_estimate": round(2 * station.detour, 3),
            "gallons_purchased": round(gallons, 4),
            "price_per_gallon_usd": str(station.price),
        })
    detours = sum((2 * stop.detour for stop, _ in plan), Decimal(0))
    return Response({
        "geometry": geometry,
        "route_miles": round(miles, 3),
        "total_miles_estimate": round(Decimal(str(miles)) + detours, 3),
        "estimated_fuel_purchases_usd": str(cost.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)),
        "tank_gallons": int(TANK),
        "initial_gallons": int(TANK),
        "miles_per_gallon": int(MPG),
        "catalog_verified_stations": len(rows),
        "catalog_mode": "synthetic" if settings.SYNTHETIC_CATALOG else "configured",
        "detour_model": "estimated_out_and_back",
        "detour_road_verified": False,
        "fuel_stops": stops,
    })
