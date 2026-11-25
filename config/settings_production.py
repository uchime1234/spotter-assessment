"""Example settings for an HTTPS evaluator deployment with authorized inputs."""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

required = ("DJANGO_SECRET_KEY", "DJANGO_ALLOWED_HOSTS", "PILOT_CSV", "PRICE_CSV", "OSRM_URL")
missing = [name for name in required if not os.getenv(name)]
if missing:
    raise ImproperlyConfigured("Missing deployment settings: " + ", ".join(missing))
if len(os.environ["DJANGO_SECRET_KEY"]) < 50:
    raise ImproperlyConfigured("Use a generated Django secret of at least 50 characters.")
if "*" in ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("Use explicit deployment host names.")

DEBUG = False
MIDDLEWARE = [
    *MIDDLEWARE,  # noqa: F405
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
X_FRAME_OPTIONS = "DENY"
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 3600
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
