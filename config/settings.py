import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_BOUNDARIES_PATH = (
    BASE_DIR / "fuel_routes" / "static"
    / "fuel_routes" / "geo" / "us-states.geojson"
)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or get_random_secret_key()
DEBUG = os.getenv("DJANGO_DEBUG") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
DATA_UPLOAD_MAX_MEMORY_SIZE = 4096
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "rest_framework",
    "fuel_routes.apps.FuelRoutesConfig",
]

SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
}]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}
if bool(os.getenv("PILOT_CSV")) != bool(os.getenv("PRICE_CSV")):
    raise ImproperlyConfigured("Set both PILOT_CSV and PRICE_CSV together.")
SYNTHETIC_CATALOG = not os.getenv("PILOT_CSV")
PILOT_CSV = BASE_DIR / Path(os.getenv("PILOT_CSV") or "fixtures/synthetic-stations.csv")
PRICE_CSV = BASE_DIR / Path(os.getenv("PRICE_CSV") or "fixtures/synthetic-prices.csv")
OSRM_URL = ("http://127.0.0.1:8767" if SYNTHETIC_CATALOG
            else os.getenv("OSRM_URL") or "https://router.project-osrm.org")

if os.getenv("SPOTTER_LOG_PROVIDER_REQUESTS") == "1":
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "loggers": {"spotter.providers": {"handlers": ["console"], "level": "INFO", "propagate": False}},
    }
