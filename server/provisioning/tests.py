from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from core import sync
from core.models import Device

from . import service, wgconf


class ProvisioningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo")

    def _user(self, username, cas_names):
        user = User.objects.create(username=username)
        sync.sync_membership(user, cas_names)
        return user

    def test_register_provisions_a_device_on_every_allowed_gateway(self):
        alice = self._user("alice", ["vpn-users", "vpn-admins", "research-lab-a"])
        devices = service.register_devices(alice, "PUBKEY_ALICE")
        self.assertEqual(sorted(d.gateway.name for d in devices), ["gw-a", "gw-b"])
        # First host of each subnet is the gateway; devices start at .2.
        self.assertEqual({d.gateway.name: d.address for d in devices},
                         {"gw-a": "10.10.0.2", "gw-b": "10.10.1.2"})

    def test_register_is_idempotent_and_rotates_key(self):
        alice = self._user("alice", ["vpn-users"])  # gw-a only
        d1 = service.register_devices(alice, "KEY_1")[0]
        addr, psk = d1.address, d1.preshared_key
        d2 = service.register_devices(alice, "KEY_2")[0]
        self.assertEqual(Device.objects.filter(user=alice).count(), 1)
        self.assertEqual(d2.address, addr)  # stable address
        self.assertEqual(d2.preshared_key, psk)  # stable PSK
        self.assertEqual(d2.public_key, "KEY_2")  # rotated key

    def test_no_access_user_gets_no_device(self):
        carol = self._user("carol", [])
        self.assertEqual(service.register_devices(carol, "KEY"), [])

    def test_public_key_cannot_be_claimed_by_another_user(self):
        alice = self._user("alice", ["vpn-users"])
        mallory = self._user("mallory", ["vpn-users"])
        service.register_devices(alice, "SHARED_KEY")
        with self.assertRaises(service.PublicKeyConflict):
            service.register_devices(mallory, "SHARED_KEY")
        # The legitimate owner can still re-register their own key.
        service.register_devices(alice, "SHARED_KEY")

    def test_plan_endpoint_partitions_and_carries_credentials(self):
        from casauth import tokens

        alice = self._user("alice", ["vpn-users", "vpn-admins", "research-lab-a"])
        service.register_devices(alice, "PUBKEY_ALICE")

        resp = self.client.get(
            "/api/plan/", HTTP_AUTHORIZATION=f"Bearer {tokens.mint(alice)}"
        )
        self.assertEqual(resp.status_code, 200)
        plan = resp.json()

        by_service = {t["service"]: t for t in plan["tunnels"]}
        self.assertEqual(set(by_service), {"gw-a", "gw-b"})
        # gw-a (first in order) claims the shared network; gw-b only routes
        # what is left — no AllowedIPs overlap between tunnels.
        self.assertEqual(
            sorted(by_service["gw-a"]["allowed_ips"]),
            ["10.0.0.0/24", "192.168.20.0/24"],
        )
        self.assertEqual(by_service["gw-b"]["allowed_ips"], ["192.168.30.0/24"])
        for tunnel in plan["tunnels"]:
            for instance in tunnel["instances"]:
                self.assertIsNotNone(instance["address"])
                self.assertIsNotNone(instance["preshared_key"])
                self.assertTrue(instance["endpoint"])

    def test_plan_before_registration_has_null_credentials(self):
        from casauth import tokens

        bob = self._user("bob", ["vpn-users"])
        resp = self.client.get(
            "/api/plan/", HTTP_AUTHORIZATION=f"Bearer {tokens.mint(bob)}"
        )
        self.assertEqual(resp.status_code, 200)
        instance = resp.json()["tunnels"][0]["instances"][0]
        self.assertIsNone(instance["address"])
        self.assertIsNone(instance["preshared_key"])

    def test_plan_without_access_is_403(self):
        from casauth import tokens

        carol = self._user("carol", [])
        resp = self.client.get(
            "/api/plan/", HTTP_AUTHORIZATION=f"Bearer {tokens.mint(carol)}"
        )
        self.assertEqual(resp.status_code, 403)

    def test_config_is_scoped_to_the_gateway(self):
        from core import resolve
        from core.models import Gateway

        bob = self._user("bob", ["vpn-users", "research-lab-b"])
        service.register_devices(bob, "KEY_BOB")
        gw_a = Gateway.objects.get(name="gw-a")
        device = Device.objects.get(user=bob, gateway=gw_a)
        conf = wgconf.build_config(device, gw_a, resolve.allowed_ips_for_user(bob, gw_a))
        self.assertIn("PrivateKey = __PRIVATE_KEY__", conf)
        self.assertIn(f"PresharedKey = {device.preshared_key}", conf)
        self.assertIn("Endpoint = gw-a:51820", conf)
        self.assertIn("10.0.0.0/24", conf)         # net-common (served by gw-a)
        self.assertNotIn("192.168.30.0/24", conf)  # net-lab-b is behind gw-b
        self.assertNotIn("192.168.20.0/24", conf)  # lab A not granted to bob
