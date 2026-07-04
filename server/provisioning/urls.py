from django.urls import path

from . import views

urlpatterns = [
    path("api/peers/register/", views.register_peer, name="register_peer"),
    path("api/config/", views.get_config, name="get_config"),
    path("api/configs/", views.list_configs, name="list_configs"),
    path("api/gateways/sync/", views.gateway_sync, name="gateway_sync"),
]
