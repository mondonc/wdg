"""Unit tests for the multi-tunnel orchestration (run: python3 -m unittest)."""

import unittest

from wg_client import plan

PLAN = {
    "site": "site-a",
    "tunnels": [
        {
            "service": "si-chercheurs",
            "default_route": False,
            "allowed_ips": ["172.16.10.0/24", "172.16.20.0/24"],
            "instances": [
                {
                    "gateway": "si-a", "site": "site-a", "endpoint": "si-a:51820",
                    "public_key": "PKA", "address": "10.21.0.2", "preshared_key": "PSKA",
                },
                {
                    "gateway": "si-b", "site": "site-b", "endpoint": "si-b:51820",
                    "public_key": "PKB", "address": "10.21.1.2", "preshared_key": "PSKB",
                },
            ],
        },
        {
            "service": "internet-egress",
            "default_route": True,
            "allowed_ips": ["0.0.0.0/0"],
            "instances": [
                {
                    "gateway": "inet-a", "site": "site-a", "endpoint": "inet-a:51820",
                    "public_key": "PKI", "address": "10.20.0.2", "preshared_key": "PSKI",
                },
            ],
        },
    ],
}


class Recorder:
    def __init__(self, refuse_handshake=()):
        self.refuse = set(refuse_handshake)
        self.ups: list[tuple[str, str]] = []
        self.downs: list[str] = []
        self.current: dict[str, str] = {}  # iface -> gateway endpoint

    def up(self, name, conf):
        gateway = next(
            line.split("= ")[1] for line in conf.splitlines() if line.startswith("Endpoint")
        )
        self.ups.append((name, gateway))
        self.current[name] = gateway

    def down(self, name):
        self.downs.append(name)
        self.current.pop(name, None)

    def wait(self, name):
        return self.current.get(name) not in self.refuse


class BuildConfTests(unittest.TestCase):
    def test_conf_carries_plan_and_instance_fields(self):
        conf = plan.build_conf("PRIV", PLAN["tunnels"][0], PLAN["tunnels"][0]["instances"][0])
        self.assertIn("PrivateKey = PRIV", conf)
        self.assertIn("Address = 10.21.0.2/32", conf)
        self.assertIn("PublicKey = PKA", conf)
        self.assertIn("PresharedKey = PSKA", conf)
        self.assertIn("AllowedIPs = 172.16.10.0/24, 172.16.20.0/24", conf)
        self.assertIn("PersistentKeepalive = 25", conf)


class ConnectPlanTests(unittest.TestCase):
    def test_every_tunnel_comes_up_on_preferred_instance(self):
        rec = Recorder()
        states = plan.connect_plan(PLAN, "PRIV", up=rec.up, down=rec.down, wait=rec.wait)
        self.assertEqual(
            [(s["iface"], s["service"], s["gateway"]) for s in states],
            [("wdg0", "si-chercheurs", "si-a"), ("wdg1", "internet-egress", "inet-a")],
        )
        self.assertEqual(rec.downs, [])

    def test_failover_to_next_instance_when_no_handshake(self):
        rec = Recorder(refuse_handshake={"si-a:51820"})
        states = plan.connect_plan(PLAN, "PRIV", up=rec.up, down=rec.down, wait=rec.wait)
        self.assertEqual(states[0]["gateway"], "si-b")
        # The dead instance was brought down before trying the next one.
        self.assertEqual(rec.downs, ["wdg0"])

    def test_all_instances_dead_tears_everything_down(self):
        rec = Recorder(refuse_handshake={"inet-a:51820"})
        with self.assertRaises(plan.TunnelError):
            plan.connect_plan(PLAN, "PRIV", up=rec.up, down=rec.down, wait=rec.wait)
        # wdg1 failed and was downed; the already-up wdg0 was rolled back too.
        self.assertIn("wdg0", rec.downs)
        self.assertEqual(rec.current, {})

    def test_up_failure_is_a_failover_case(self):
        # A dead instance can fail at bring-up (e.g. unresolvable hostname).
        rec = Recorder()
        real_up = rec.up

        def flaky_up(name, conf):
            if "si-a:51820" in conf:
                raise RuntimeError("Temporary failure in name resolution")
            real_up(name, conf)

        states = plan.connect_plan(PLAN, "PRIV", up=flaky_up, down=rec.down, wait=rec.wait)
        self.assertEqual(states[0]["gateway"], "si-b")

    def test_unregistered_instance_is_skipped(self):
        broken = {
            "site": None,
            "tunnels": [
                {
                    "service": "si",
                    "default_route": False,
                    "allowed_ips": ["172.16.10.0/24"],
                    "instances": [
                        {"gateway": "g1", "endpoint": "g1:1", "public_key": "PK1",
                         "address": None, "preshared_key": None},
                        {"gateway": "g2", "endpoint": "g2:1", "public_key": "PK2",
                         "address": "10.0.0.2", "preshared_key": "PSK"},
                    ],
                }
            ],
        }
        rec = Recorder()
        states = plan.connect_plan(broken, "PRIV", up=rec.up, down=rec.down, wait=rec.wait)
        self.assertEqual(states[0]["gateway"], "g2")

    def test_iface_names_are_linux_safe(self):
        self.assertLessEqual(len(plan.iface_name(99)), 15)


if __name__ == "__main__":
    unittest.main()
