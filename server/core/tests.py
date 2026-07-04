from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core import resolve, sync
from core.models import (
    Device,
    Gateway,
    Group,
    Network,
    RelayLink,
    Service,
    Site,
    UserProfile,
)


class SeededTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo")


class MembershipSyncTests(SeededTestCase):
    def test_cas_names_map_to_seeded_groups(self):
        alice = User.objects.create(username="alice")
        groups = sync.sync_membership(alice, ["vpn-users", "vpn-admins", "research-lab-a"])
        self.assertEqual(
            sorted(g.name for g in groups),
            ["research-lab-a", "vpn-admins", "vpn-users"],
        )
        # No duplicate groups were created for known CAS names.
        self.assertEqual(Group.objects.filter(name="vpn-users").count(), 1)

    def test_unknown_cas_name_autocreates_group(self):
        bob = User.objects.create(username="bob")
        sync.sync_membership(bob, ["brand-new-group"])
        self.assertTrue(Group.objects.filter(name="brand-new-group").exists())

    def test_resync_replaces_membership(self):
        u = User.objects.create(username="carol")
        sync.sync_membership(u, ["vpn-users"])
        sync.sync_membership(u, ["vpn-admins"])
        self.assertEqual(
            sorted(g.name for g in u.wdg_groups.all()), ["vpn-admins"]
        )


class MembershipResilienceTests(SeededTestCase):
    def test_dn_value_maps_to_group_via_cas_names(self):
        user = User.objects.create(username="dave")
        groups = sync.sync_membership(user, ["cn=vpn-admins,ou=groups,dc=example,dc=org"])
        self.assertEqual([g.name for g in groups], ["vpn-admins"])

    def test_affiliation_value_maps_to_group(self):
        user = User.objects.create(username="dave")
        groups = sync.sync_membership(user, ["staff"])
        self.assertEqual([g.name for g in groups], ["staff-network"])

    def test_empty_cas_preserves_manual_membership(self):
        user = User.objects.create(username="manual")
        user.wdg_groups.add(Group.objects.get(name="vpn-users"))
        # CAS released no group attributes → do not clobber the admin assignment.
        sync.sync_membership(user, [])
        self.assertEqual([g.name for g in user.wdg_groups.all()], ["vpn-users"])

    def test_empty_cas_can_be_authoritative_when_requested(self):
        user = User.objects.create(username="manual")
        user.wdg_groups.add(Group.objects.get(name="vpn-users"))
        sync.sync_membership(user, [], replace_when_empty=True)
        self.assertEqual(list(user.wdg_groups.all()), [])


class AccessResolutionTests(SeededTestCase):
    def test_admin_reaches_all_networks_via_two_gateways(self):
        alice = User.objects.create(username="alice")
        sync.sync_membership(alice, ["vpn-users", "vpn-admins", "research-lab-a"])
        access = resolve.access_for_user(alice)
        # gw-dc is relay-only (accepts_clients=False): never a client gateway.
        self.assertEqual(
            sorted(g.name for g in access["gateways"]), ["gw-a", "gw-a2", "gw-b"]
        )
        self.assertEqual(
            sorted(resolve.allowed_ips_for_user(alice)),
            ["10.0.0.0/24", "192.168.20.0/24", "192.168.30.0/24", "192.168.40.0/24"],
        )

    def test_plain_user_is_limited_to_common_network(self):
        bob = User.objects.create(username="bob")
        sync.sync_membership(bob, ["vpn-users", "research-lab-b"])
        access = resolve.access_for_user(bob)
        self.assertEqual(
            sorted(g.name for g in access["gateways"]), ["gw-a", "gw-a2", "gw-b"]
        )
        self.assertEqual(
            sorted(resolve.allowed_ips_for_user(bob)),
            ["10.0.0.0/24", "192.168.30.0/24"],
        )
        # bob has no access to lab A's network.
        self.assertNotIn("192.168.20.0/24", resolve.allowed_ips_for_user(bob))

    def test_user_without_groups_has_no_access(self):
        nobody = User.objects.create(username="nobody")
        access = resolve.access_for_user(nobody)
        self.assertEqual(access["gateways"], [])
        self.assertEqual(access["networks"], [])

    def test_inactive_gateway_is_excluded(self):
        alice = User.objects.create(username="alice")
        sync.sync_membership(alice, ["vpn-admins"])
        Gateway.objects.filter(name="gw-b").update(is_active=False)
        access = resolve.access_for_user(alice)
        self.assertEqual([g.name for g in access["gateways"]], ["gw-a", "gw-a2"])


class PerGatewayScopingTests(SeededTestCase):
    def test_networks_are_scoped_to_the_gateway(self):
        alice = User.objects.create(username="alice")
        sync.sync_membership(alice, ["vpn-users", "vpn-admins", "research-lab-a"])
        gw_a = Gateway.objects.get(name="gw-a")
        gw_b = Gateway.objects.get(name="gw-b")
        # gw-a routes net-common + net-lab-a; net-lab-b is only behind gw-b.
        self.assertEqual(
            sorted(resolve.allowed_ips_for_user(alice, gw_a)),
            ["10.0.0.0/24", "192.168.20.0/24"],
        )
        self.assertEqual(
            sorted(resolve.allowed_ips_for_user(alice, gw_b)),
            ["10.0.0.0/24", "192.168.30.0/24"],
        )

    def test_gateway_only_exposes_networks_the_user_is_granted(self):
        bob = User.objects.create(username="bob")
        sync.sync_membership(bob, ["vpn-users", "research-lab-b"])
        gw_a = Gateway.objects.get(name="gw-a")
        # bob is granted net-common + net-lab-b; via gw-a only net-common applies
        # (gw-a doesn't route net-lab-b, and bob lacks net-lab-a).
        self.assertEqual(resolve.allowed_ips_for_user(bob, gw_a), ["10.0.0.0/24"])


class SiteMappingTests(SeededTestCase):
    def test_site_set_from_cas_value(self):
        user = User.objects.create(username="alice")
        site = sync.sync_site(user, ["centre-a"])
        self.assertEqual(site.name, "site-a")
        self.assertEqual(resolve.user_site(user).name, "site-a")

    def test_site_name_matches_too(self):
        user = User.objects.create(username="bob")
        self.assertEqual(sync.sync_site(user, ["site-b"]).name, "site-b")

    def test_unknown_value_is_ignored_never_autocreated(self):
        user = User.objects.create(username="carol")
        before = Site.objects.count()
        self.assertIsNone(sync.sync_site(user, ["mars"]))
        self.assertEqual(Site.objects.count(), before)

    def test_empty_release_preserves_manual_assignment(self):
        user = User.objects.create(username="manual")
        UserProfile.objects.create(user=user, site=Site.objects.get(name="site-a"))
        self.assertEqual(sync.sync_site(user, []).name, "site-a")


class RelayTopologyTestCase(TestCase):
    """
    The design's reference topology: two sites, an internet-egress
    (default-route) service, an SI entry service, and a relay chain
    si → dc → core.
    """

    @classmethod
    def setUpTestData(cls):
        cls.site_a = Site.objects.create(name="site-a", cas_values=["centre-a"])
        cls.site_b = Site.objects.create(name="site-b", cas_values=["centre-b"])

        cls.svc_inet = Service.objects.create(name="internet-egress", default_route=True)
        cls.svc_si = Service.objects.create(name="si-chercheurs")
        cls.svc_dc = Service.objects.create(name="dc-access", accepts_clients=False)
        cls.svc_core = Service.objects.create(name="core-access", accepts_clients=False)

        def gw(name, svc, site, subnet):
            return Gateway.objects.create(
                name=name, service=svc, site=site,
                endpoint=f"{name}:51820", tunnel_subnet=subnet,
            )

        cls.inet_a = gw("inet-a", cls.svc_inet, cls.site_a, "10.20.0.0/24")
        cls.inet_b = gw("inet-b", cls.svc_inet, cls.site_b, "10.20.1.0/24")
        cls.si_a = gw("si-a", cls.svc_si, cls.site_a, "10.21.0.0/24")
        cls.si_b = gw("si-b", cls.svc_si, cls.site_b, "10.21.1.0/24")
        cls.dc_a = gw("dc-a", cls.svc_dc, cls.site_a, "10.22.0.0/24")
        cls.core_1 = gw("core-1", cls.svc_core, cls.site_a, "10.23.0.0/24")

        cls.net_si = Network.objects.create(name="net-si", cidr="172.16.10.0/24")
        cls.net_dc = Network.objects.create(name="net-dc", cidr="172.16.20.0/24")
        cls.net_core = Network.objects.create(name="net-core", cidr="172.16.30.0/24")
        cls.si_a.networks.add(cls.net_si)
        cls.si_b.networks.add(cls.net_si)
        cls.dc_a.networks.add(cls.net_dc)
        cls.core_1.networks.add(cls.net_core)

        RelayLink.objects.create(from_gateway=cls.si_a, to_gateway=cls.dc_a)
        RelayLink.objects.create(from_gateway=cls.si_b, to_gateway=cls.dc_a)
        RelayLink.objects.create(from_gateway=cls.dc_a, to_gateway=cls.core_1)

        def group(name, services=(), networks=()):
            g = Group.objects.create(name=name)
            g.services.set(services)
            g.networks.set(networks)
            return g

        cls.g_si = group("grp-chercheurs", [cls.svc_si], [cls.net_si])
        cls.g_dc = group("grp-gw-centre", [cls.svc_dc], [cls.net_dc])
        cls.g_core = group("grp-core", [cls.svc_core], [cls.net_core])
        cls.g_inet = group("grp-internet", [cls.svc_inet])
        cls.g_dc_net_only = group("grp-dc-net-only", [], [cls.net_dc])

    def _user(self, name, groups, site=None):
        user = User.objects.create(username=name)
        for g in groups:
            g.members.add(user)
        if site:
            UserProfile.objects.create(user=user, site=site)
        return user


class PlanTests(RelayTopologyTestCase):
    """Multi-tunnel plan resolver."""

    def test_single_service_plan(self):
        user = self._user("u1", [self.g_si], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].service, self.svc_si)
        self.assertEqual(plan[0].allowed_ips, ["172.16.10.0/24"])
        self.assertEqual([g.name for g in plan[0].instances], ["si-a", "si-b"])

    def test_instances_prefer_the_users_site(self):
        user = self._user("u2", [self.g_si], self.site_b)
        plan = resolve.plan_for_user(user)
        self.assertEqual([g.name for g in plan[0].instances], ["si-b", "si-a"])

    def test_relay_networks_ride_the_entry_tunnel(self):
        user = self._user("u3", [self.g_si, self.g_dc], self.site_a)
        plan = resolve.plan_for_user(user)
        # dc-access accepts no clients: no tunnel of its own, but its network
        # is reachable through the si tunnel via the relay link.
        self.assertEqual(len(plan), 1)
        self.assertIn("172.16.20.0/24", plan[0].allowed_ips)

    def test_relay_hop_is_a_privilege(self):
        # net-dc is granted, but not the dc-access service: the walk must not
        # traverse dc-a, so the network stays unreachable.
        user = self._user("u4", [self.g_si, self.g_dc_net_only], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertNotIn("172.16.20.0/24", plan[0].allowed_ips)

    def test_chained_relays(self):
        user = self._user("u5", [self.g_si, self.g_dc, self.g_core], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertIn("172.16.30.0/24", plan[0].allowed_ips)

    def test_chain_requires_every_hop(self):
        # core is granted but the intermediate dc hop is not: unreachable.
        user = self._user("u6", [self.g_si, self.g_core], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertNotIn("172.16.30.0/24", plan[0].allowed_ips)

    def test_default_route_tunnel_is_last_and_catch_all(self):
        user = self._user("u7", [self.g_si, self.g_inet], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertEqual([t.service.name for t in plan], ["si-chercheurs", "internet-egress"])
        self.assertEqual(plan[-1].allowed_ips, ["0.0.0.0/0"])

    def test_relay_only_grant_yields_no_tunnel(self):
        user = self._user("u8", [self.g_dc], self.site_a)
        self.assertEqual(resolve.plan_for_user(user), [])

    def test_overlapping_networks_are_partitioned(self):
        shared = Network.objects.create(name="net-shared", cidr="172.16.40.0/24")
        svc_x = Service.objects.create(name="aa-x")
        svc_y = Service.objects.create(name="bb-y")
        gx = Gateway.objects.create(
            name="gx", service=svc_x, endpoint="gx:51820", tunnel_subnet="10.24.0.0/24"
        )
        gy = Gateway.objects.create(
            name="gy", service=svc_y, endpoint="gy:51820", tunnel_subnet="10.25.0.0/24"
        )
        gx.networks.add(shared)
        gy.networks.add(shared)
        g = Group.objects.create(name="grp-xy")
        g.services.set([svc_x, svc_y])
        g.networks.set([shared])

        user = self._user("u9", [g], self.site_a)
        plan = resolve.plan_for_user(user)
        # The first service (name order) claims the network; the second tunnel
        # has nothing left to route and is dropped from the plan.
        self.assertEqual([t.service.name for t in plan], ["aa-x"])
        self.assertEqual(plan[0].allowed_ips, ["172.16.40.0/24"])

    def test_inactive_instance_is_excluded(self):
        Gateway.objects.filter(name="si-a").update(is_active=False)
        user = self._user("u10", [self.g_si], self.site_a)
        plan = resolve.plan_for_user(user)
        self.assertEqual([g.name for g in plan[0].instances], ["si-b"])

    def test_clients_never_register_on_relay_gateways(self):
        user = self._user("u11", [self.g_si, self.g_dc], self.site_a)
        names = [g.name for g in resolve.gateways_for_user(user)]
        self.assertEqual(names, ["si-a", "si-b"])  # dc-a accepts no clients


class SyncTopologyTests(RelayTopologyTestCase):
    """
    What the sync API computes for each hop of the si → dc → core chain:
    inter-gateway peers (forward + return AllowedIPs), per-client forward
    rules, and the subnets to MASQUERADE on the legs.
    """

    def test_entry_gateway_relay_peer_covers_the_whole_forward_path(self):
        peers = resolve.relay_peers_for_gateway(self.si_a)
        self.assertEqual([p["name"] for p in peers], ["dc-a"])
        # Networks behind dc-a, including the chained core hop.
        self.assertEqual(
            sorted(peers[0]["allowed_ips"]), ["172.16.20.0/24", "172.16.30.0/24"]
        )

    def test_relay_gateway_peers_both_directions(self):
        peers = {p["name"]: p for p in resolve.relay_peers_for_gateway(self.dc_a)}
        self.assertEqual(set(peers), {"si-a", "si-b", "core-1"})
        # Return path: the client subnets behind each upstream entry gateway.
        self.assertEqual(peers["si-a"]["allowed_ips"], ["10.21.0.0/24"])
        self.assertEqual(peers["si-b"]["allowed_ips"], ["10.21.1.0/24"])
        # Forward path to the next hop.
        self.assertEqual(peers["core-1"]["allowed_ips"], ["172.16.30.0/24"])

    def test_chain_tail_sees_all_upstream_subnets(self):
        peers = {p["name"]: p for p in resolve.relay_peers_for_gateway(self.core_1)}
        self.assertEqual(set(peers), {"dc-a"})
        self.assertEqual(
            sorted(peers["dc-a"]["allowed_ips"]),
            ["10.21.0.0/24", "10.21.1.0/24", "10.22.0.0/24"],
        )

    def test_masquerade_covers_upstream_client_subnets(self):
        self.assertEqual(
            sorted(resolve.masq_subnets_for_gateway(self.dc_a)),
            ["10.21.0.0/24", "10.21.1.0/24", "10.22.0.0/24"],
        )
        self.assertEqual(resolve.masq_subnets_for_gateway(self.si_a), ["10.21.0.0/24"])

    def test_forward_rules_follow_the_path_and_the_grants(self):
        user = self._user("w1", [self.g_si, self.g_dc], self.site_a)
        device = Device.objects.create(
            user=user, gateway=self.si_a, public_key="K1",
            address="10.21.0.2", preshared_key="P1",
        )
        # Entry hop: direct net + relayed net.
        self.assertEqual(
            resolve.forward_rules_for_gateway(self.si_a),
            [
                {"src": "10.21.0.2", "dst": "172.16.10.0/24"},
                {"src": "10.21.0.2", "dst": "172.16.20.0/24"},
            ],
        )
        # Relay hop: only the relayed net (net-core is not granted).
        self.assertEqual(
            resolve.forward_rules_for_gateway(self.dc_a),
            [{"src": "10.21.0.2", "dst": "172.16.20.0/24"}],
        )
        self.assertEqual(resolve.forward_rules_for_gateway(self.core_1), [])
        # The other site's entry instance is not on this client's path.
        self.assertEqual(resolve.forward_rules_for_gateway(self.si_b), [])
        # Revocation: deactivating the device removes every rule.
        device.is_active = False
        device.save(update_fields=["is_active"])
        self.assertEqual(resolve.forward_rules_for_gateway(self.dc_a), [])

    def test_middle_hop_carries_chained_traffic(self):
        user = self._user("w2", [self.g_si, self.g_dc, self.g_core], self.site_a)
        Device.objects.create(
            user=user, gateway=self.si_a, public_key="K2",
            address="10.21.0.3", preshared_key="P2",
        )
        rules = resolve.forward_rules_for_gateway(self.dc_a)
        self.assertIn({"src": "10.21.0.3", "dst": "172.16.30.0/24"}, rules)
        rules = resolve.forward_rules_for_gateway(self.core_1)
        self.assertEqual(rules, [{"src": "10.21.0.3", "dst": "172.16.30.0/24"}])


class GatewayValidationTests(SeededTestCase):
    def _gateway(self, subnet):
        return Gateway(name="new-gw", endpoint="new-gw:51820", tunnel_subnet=subnet)

    def test_invalid_cidr_is_rejected(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            self._gateway("not-a-cidr").clean()

    def test_overlapping_subnet_is_rejected(self):
        from django.core.exceptions import ValidationError

        # 10.10.0.0/16 covers gw-a's 10.10.0.0/24.
        with self.assertRaises(ValidationError):
            self._gateway("10.10.0.0/16").clean()
        with self.assertRaises(ValidationError):
            self._gateway("10.10.1.128/25").clean()  # inside gw-b's /24

    def test_disjoint_subnet_is_accepted(self):
        self._gateway("10.99.0.0/24").clean()

    def test_editing_own_subnet_does_not_self_conflict(self):
        gw = Gateway.objects.get(name="gw-a")
        gw.clean()


class AddressAllocationTests(SeededTestCase):
    def test_allocation_skips_gateway_ip_and_avoids_collisions(self):
        gw = Gateway.objects.get(name="gw-a")
        user = User.objects.create(username="alice")
        first = resolve.allocate_address(gw)
        self.assertEqual(first, "10.10.0.2")  # .1 reserved for the gateway
        Device.objects.create(
            user=user, gateway=gw, public_key="k1", address=first, preshared_key="p1"
        )
        second = resolve.allocate_address(gw)
        self.assertEqual(second, "10.10.0.3")
