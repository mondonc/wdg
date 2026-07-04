from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "WDG — WireGuard Distributed Gateways"
admin.site.site_title = "WDG"
admin.site.index_title = "Control plane administration"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("casauth.urls")),
    path("", include("provisioning.urls")),
]
