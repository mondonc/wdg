"""The configuration planes actually gate what an instance serves."""

from django.test import TestCase

from wdg_server.urls import plane_urlpatterns


def _routes(patterns):
    # Route strings exist on URLPattern and URLResolver alike, so a pattern
    # that loses its name= can't silently drop out of the assertions.
    return {str(p.pattern) for p in patterns}


class PlaneSplitTests(TestCase):
    def test_external_plane_has_no_admin_and_no_sync(self):
        routes = _routes(plane_urlpatterns(["external"]))
        self.assertIn("auth/cas/login", routes)
        self.assertIn("api/config/", routes)
        self.assertNotIn("api/gateways/sync/", routes)
        self.assertNotIn("admin/", routes)

    def test_internal_plane_serves_sync_only(self):
        routes = _routes(plane_urlpatterns(["internal"]))
        self.assertIn("api/gateways/sync/", routes)
        self.assertNotIn("admin/", routes)
        self.assertNotIn("auth/cas/login", routes)
        self.assertNotIn("api/peers/register/", routes)

    def test_admin_plane_serves_only_the_admin(self):
        routes = _routes(plane_urlpatterns(["admin"]))
        self.assertIn("admin/", routes)
        self.assertNotIn("api/gateways/sync/", routes)
        self.assertNotIn("auth/cas/login", routes)
        self.assertNotIn("api/peers/register/", routes)

    def test_healthz_is_on_every_plane(self):
        for planes in (["external"], ["internal"], ["admin"],
                       ["external", "internal", "admin"]):
            self.assertIn("healthz", _routes(plane_urlpatterns(planes)))

    def test_default_serves_every_plane(self):
        # The dev/demo single-instance behaviour: everything on one port.
        routes = _routes(plane_urlpatterns(["external", "internal", "admin"]))
        for expected in ("auth/cas/login", "api/peers/register/",
                         "api/gateways/sync/", "admin/"):
            self.assertIn(expected, routes)
