import math

from rest_framework import serializers


class Coordinates(serializers.Serializer):
    latitude = serializers.FloatField(min_value=-90, max_value=90)
    longitude = serializers.FloatField(min_value=-180, max_value=180)

    def to_internal_value(self, data):
        try:
            return super().to_internal_value(data)
        except OverflowError as exc:
            raise serializers.ValidationError("Coordinates are out of range.") from exc

    def validate(self, attrs):
        if not all(math.isfinite(value) for value in attrs.values()):
            raise serializers.ValidationError("Coordinates must be finite.")
        return attrs


class Endpoint(serializers.Field):
    def to_internal_value(self, value):
        if isinstance(value, str) and 0 < len(value.strip()) <= 250:
            return value.strip()
        if isinstance(value, dict):
            fields = Coordinates(data=value)
            fields.is_valid(raise_exception=True)
            return fields.validated_data
        raise serializers.ValidationError("Provide a US street address or a latitude/longitude object.")


class Journey(serializers.Serializer):
    start = Endpoint()
    finish = Endpoint()
