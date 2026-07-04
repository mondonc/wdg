from django.urls import path

from . import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("auth/cas/login", views.cas_login, name="cas_login"),
    path("auth/cas/callback", views.cas_callback, name="cas_callback"),
    path("auth/cas/exchange", views.cas_exchange, name="cas_exchange"),
    path("api/whoami/", views.whoami, name="whoami"),
]
