"""
Idempotent demo seed: gateways, exit networks, and groups wired to match the
mock-CAS users (see deploy/cas-test/users.json). Safe to run repeatedly.
"""

from django.core.management.base import BaseCommand

from core.models import Gateway, Group, Network

GATEWAYS = [
    # name, endpoint, tunnel_subnet, sync_token
    # public_key is left blank: the gateway agent self-reports it at sync time.
    ("gw-a", "gw-a:51820", "10.10.0.0/24", "gw-a-sync-secret"),
    ("gw-b", "gw-b:51820", "10.10.1.0/24", "gw-b-sync-secret"),
]

NETWORKS = [
    # net-common's CIDR matches the docker "exitnet" used by the M3 tunnel test,
    # so an authorized client actually reaches the exit-target through gw-a.
    ("net-common", "10.0.0.0/24", "Shared intranet services"),
    ("net-lab-a", "192.168.20.0/24", "Research lab A"),
    ("net-lab-b", "192.168.30.0/24", "Research lab B"),
]

# name, cas_names, gateway names (entry), network names (exit)
# cas_names shows configurable mapping: a WDG group can be reached from several
# CAS values (a short name AND the full LDAP DN, or an affiliation string).
GROUPS = [
    ("vpn-users", ["vpn-users"], ["gw-a"], ["net-common"]),
    (
        "vpn-admins",
        ["vpn-admins", "cn=vpn-admins,ou=groups,dc=example,dc=org"],
        ["gw-a", "gw-b"],
        ["net-common", "net-lab-a", "net-lab-b"],
    ),
    ("research-lab-a", ["research-lab-a"], ["gw-a"], ["net-lab-a"]),
    ("research-lab-b", ["research-lab-b"], ["gw-b"], ["net-lab-b"]),
    # Driven by the eduPersonAffiliation "staff" attribute rather than memberOf.
    ("staff-network", ["staff"], ["gw-a"], ["net-common"]),
]

# Which exit networks each gateway can actually route to.
GATEWAY_NETWORKS = {
    "gw-a": ["net-common", "net-lab-a"],
    "gw-b": ["net-common", "net-lab-b"],
}


class Command(BaseCommand):
    help = "Seed demo gateways, networks and groups (idempotent)."

    def handle(self, *args, **options):
        for name, endpoint, subnet, sync_token in GATEWAYS:
            Gateway.objects.update_or_create(
                name=name,
                defaults={
                    "endpoint": endpoint,
                    "tunnel_subnet": subnet,
                    "sync_token": sync_token,
                },
            )
        for name, cidr, desc in NETWORKS:
            Network.objects.update_or_create(
                name=name, defaults={"cidr": cidr, "description": desc}
            )
        for name, cas_names, gw_names, net_names in GROUPS:
            group, _ = Group.objects.update_or_create(
                name=name, defaults={"cas_names": cas_names}
            )
            group.gateways.set(Gateway.objects.filter(name__in=gw_names))
            group.networks.set(Network.objects.filter(name__in=net_names))

        for gw_name, net_names in GATEWAY_NETWORKS.items():
            gateway = Gateway.objects.get(name=gw_name)
            gateway.networks.set(Network.objects.filter(name__in=net_names))

        self.stdout.write(self.style.SUCCESS("Demo data seeded."))
