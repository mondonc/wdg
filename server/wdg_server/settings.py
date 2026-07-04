"""
Django settings for the WDG control plane.

Configuration is read from the environment so the same image runs in dev
(docker-compose) and production. See ``deploy/`` for concrete values.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env_list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


SECRET_KEY = os.environ.get("WDG_SECRET_KEY", "dev-insecure-change-me")
DEBUG = os.environ.get("WDG_DEBUG", "1") == "1"
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
# CAS attribute names that carry group / affiliation membership.
CAS_GROUP_ATTRIBUTES = _env_list("WDG_CAS_GROUP_ATTRIBUTES", "memberOf")

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
