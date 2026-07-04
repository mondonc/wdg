from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core import resolve, sync
from core.models import Device, Gateway, Group, Network


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
        self.assertEqual(sorted(g.name for g in access["gateways"]), ["gw-a", "gw-b"])
        self.assertEqual(
            sorted(resolve.allowed_ips_for_user(alice)),
            ["10.0.0.0/24", "192.168.20.0/24", "192.168.30.0/24"],
        )

    def test_plain_user_is_limited_to_common_network(self):
        bob = User.objects.create(username="bob")
        sync.sync_membership(bob, ["vpn-users", "research-lab-b"])
        access = resolve.access_for_user(bob)
        self.assertEqual(sorted(g.name for g in access["gateways"]), ["gw-a", "gw-b"])
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
        self.assertEqual([g.name for g in access["gateways"]], ["gw-a"])


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
