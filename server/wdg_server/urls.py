"""
Root URLconf, assembled from the *configuration planes* this instance serves
(``WDG_PLANES``, see settings):

- ``external`` — client-facing: CAS auth + provisioning APIs. The only plane
  exposed to the outside (behind nginx-pq).
- ``internal`` — the gateway/relay sync API: what the fleet pulls its state
  from. Never exposed externally.
- ``admin`` — the single Django admin interface (topology & grants). Runs on
  exactly one instance in the target layout (srv-admin, docs/DAT.md).

The same image runs every role: one deployment can serve all planes (dev,
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
        patterns += sync_urlpatterns
    if "admin" in planes:
        patterns += [path("admin/", admin.site.urls)]
    return patterns


urlpatterns = plane_urlpatterns(settings.WDG_PLANES)
