"""Continuous purchases on a fixed, ordered route with same-point detours."""
from dataclasses import dataclass
from decimal import Decimal

TANK = Decimal(50)
MPG = Decimal(10)


@dataclass(frozen=True)
class Stop:
    id: str
    mile: Decimal
    detour: Decimal  # one way
    price: Decimal


def optimize(miles, candidates):
    if miles <= TANK * MPG:
        return Decimal(0), []
    stations = sorted(candidates, key=lambda stop: (stop.mile, stop.id))
    points = [Stop("", Decimal(0), Decimal(0), Decimal(0)), *stations,
              Stop("", miles, Decimal(0), Decimal(0))]
    # A label is incoming fuel -> (cost, previous index, previous fuel, purchase).
    labels = [{} for _ in points]
    labels[0][TANK] = (Decimal(0), None, None, Decimal(0))
    for index, origin in enumerate(points[:-1]):
        for target_index in range(index + 1, len(points)):
            target = points[target_index]
            distance = target.mile - origin.mile
            if distance > TANK * MPG:
                break
            consumption = (distance + origin.detour + target.detour) / MPG
            if consumption > TANK:
                continue
            future = labels[target_index]
            for incoming, (cost, *_) in labels[index].items():
                # At a cost-minimizing extreme point, any positive purchase
                # can leave either a full tank or zero fuel at the next stop.
                departures = {max(consumption, incoming)}
                if index:
                    departures.add(TANK)
                for outgoing in sorted(departures):
                    purchase = outgoing - incoming
                    # Skipping a visit with no purchase saves its detour and leaves more fuel.
                    if index and not purchase:
                        continue
                    remaining = outgoing - consumption
                    total = cost + purchase * origin.price
                    if remaining not in future or total < future[remaining][0]:
                        future[remaining] = (total, index, incoming, purchase)
    if not labels[-1]:
        return None
    index = len(points) - 1
    fuel = min(labels[index], key=lambda amount: (labels[index][amount][0], amount))
    total = labels[index][fuel][0]
    legs = []
    while index:
        _, previous, incoming, purchase = labels[index][fuel]
        if previous:
            legs.append((points[previous], purchase))
        index, fuel = previous, incoming
    return total, list(reversed(legs))
