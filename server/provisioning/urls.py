from django.urls import path

from . import views

# External plane: client-facing provisioning APIs.
client_urlpatterns = [
    path("api/peers/register/", views.register_peer, name="register_peer"),
    path("api/config/", views.get_config, name="get_config"),
    path("api/plan/", views.get_plan, name="get_plan"),
    path("api/configs/", views.list_configs, name="list_configs"),
]

# Internal plane: the gateway agents pull their peers here.
sync_urlpatterns = [
    path("api/gateways/sync/", views.gateway_sync, name="gateway_sync"),
]

# No module-level `urlpatterns` on purpose: routes are mounted per-plane by
# wdg_server.urls — an include("provisioning.urls") would bypass WDG_PLANES,
# so it must fail loudly instead.
