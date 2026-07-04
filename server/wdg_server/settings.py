"""
Django settings for the WDG control plane.

Configuration is read from the environment so the same image runs in dev
(docker-compose) and production. See ``deploy/`` for concrete values.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = os.environ.get("WDG_DEBUG", "0") == "1"

# Outside dev, refuse to start with the well-known fallback key: a signed-token
# scheme with a public SECRET_KEY is no authentication at all.
SECRET_KEY = os.environ.get("WDG_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("WDG_SECRET_KEY must be set when WDG_DEBUG is off")
    SECRET_KEY = "dev-insecure-change-me"
ALLOWED_HOSTS = _env_list("WDG_ALLOWED_HOSTS", "*") or ["*"]

# --- CAS / SSO -------------------------------------------------------------
# Base URL of the Apereo CAS server (override via WDG_CAS_BASE_URL).
CAS_BASE_URL = os.environ.get("WDG_CAS_BASE_URL", "https://cas.example.org").rstrip("/")
# Public base URL of *this* control plane, as reached by the user's browser.
# It is the CAS "service" root and must be registered with the CAS operator.
PUBLIC_BASE_URL = os.environ.get("WDG_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
# Where the CLI client listens for the loopback redirect carrying the WDG token.
# Only loopback destinations are accepted, to avoid an open redirector.
ALLOWED_CLIENT_REDIRECT_HOSTS = ("localhost", "127.0.0.1")
# Lifetime of an issued WDG session token (seconds).
WDG_TOKEN_MAX_AGE = int(os.environ.get("WDG_TOKEN_MAX_AGE", str(12 * 3600)))
# Lifetime of the one-time code handed to the loopback redirect (seconds).
# Only needs to cover the client turning around and POSTing /auth/cas/exchange.
WDG_AUTH_CODE_MAX_AGE = int(os.environ.get("WDG_AUTH_CODE_MAX_AGE", "60"))
# CAS attribute names that carry group / affiliation membership.
CAS_GROUP_ATTRIBUTES = _env_list("WDG_CAS_GROUP_ATTRIBUTES", "memberOf")
# CAS attribute carrying the user's home site/centre (see core.models.Site).
WDG_CAS_SITE_ATTRIBUTE = os.environ.get("WDG_CAS_SITE_ATTRIBUTE", "ou")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "casauth",
    "provisioning",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Protects the session-authenticated admin. Token-authenticated API POSTs
    # are individually @csrf_exempt (bearer tokens are not sent by browsers).
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "wdg_server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wdg_server.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "wdg"),
        "USER": os.environ.get("POSTGRES_USER", "wdg"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "wdg"),
        "HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Behind the PQ reverse proxy (see M5), trust the forwarded scheme.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
