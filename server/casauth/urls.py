from django.urls import path

from . import views

# Served on every plane (liveness probes).
health_urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
]

# External plane: what the clients (browser + CLI) talk to.
auth_urlpatterns = [
    path("auth/cas/login", views.cas_login, name="cas_login"),
    path("auth/cas/callback", views.cas_callback, name="cas_callback"),
    path("auth/cas/exchange", views.cas_exchange, name="cas_exchange"),
    path("api/whoami/", views.whoami, name="whoami"),
]

# No module-level `urlpatterns` on purpose: routes are mounted per-plane by
# wdg_server.urls — an include("casauth.urls") would bypass WDG_PLANES, so
# it must fail loudly instead.
