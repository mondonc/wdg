"""
Root URLconf, assembled from the *configuration planes* this instance serves
(``WDG_PLANES``, see settings):

- ``external`` — client-facing: CAS auth + provisioning APIs. The only plane
  exposed to the outside (behind nginx-pq).
- ``internal`` — Django admin and the gateway sync API. Never exposed
  externally; the single admin interface lives here.

The same image runs every role: one deployment can serve both planes (dev,
small sites), or dedicated instances split them across network exposures.
Deployment details, including the optional "amont" tier (an additional
*external*-plane instance published further downstream): docs/DEPLOYMENT.md.
"""

from django.conf import settings
from django.contrib import admin
from django.urls import path

from casauth.urls import auth_urlpatterns, health_urlpatterns
from provisioning.urls import client_urlpatterns, sync_urlpatterns

admin.site.site_header = "WDG — WireGuard Distributed Gateways"
admin.site.site_title = "WDG"
admin.site.index_title = "Control plane administration"


def plane_urlpatterns(planes):
    """URL patterns for a given set of planes (pure: unit-testable)."""
    patterns = [*health_urlpatterns]
    if "external" in planes:
        patterns += auth_urlpatterns + client_urlpatterns
    if "internal" in planes:
        patterns += [path("admin/", admin.site.urls)] + sync_urlpatterns
    return patterns


urlpatterns = plane_urlpatterns(settings.WDG_PLANES)
