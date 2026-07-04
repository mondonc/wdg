"""
Idempotent demo seed: sites, services, gateways, exit networks, and groups
wired to match the mock-CAS users (see deploy/cas-test/users.json). Safe to
run repeatedly.
"""

from django.core.management.base import BaseCommand

from core.models import Gateway, Group, Network, RelayLink, Service, Site

SITES = [
    # name, cas_values (values of the WDG_CAS_SITE_ATTRIBUTE attribute)
    ("site-a", ["centre-a"]),
    ("site-b", ["centre-b"]),
]

# One demo entry service per gateway (single instance), plus a relay-only
# datacenter service reached through gw-a; richer multi-site topologies are
# exercised by the unit tests.
SERVICES = [
    # name, accepts_clients, default_route
    ("gw-a", True, False),
    ("gw-b", True, False),
    ("dc-access", False, False),
]

GATEWAYS = [
    # name, service, site, endpoint, tunnel_subnet, sync_token
    # public_key is left blank: the gateway agent self-reports it at sync time.
    ("gw-a", "gw-a", "site-a", "gw-a:51820", "10.10.0.0/24", "gw-a-sync-secret"),
    ("gw-b", "gw-b", "site-b", "gw-b:51820", "10.10.1.0/24", "gw-b-sync-secret"),
    ("gw-dc", "dc-access", "site-a", "gw-dc:51820", "10.10.2.0/24", "gw-dc-sync-secret"),
]

NETWORKS = [
    # net-common's CIDR matches the docker "exitnet" used by the M3 tunnel test,
    # so an authorized client actually reaches the exit-target through gw-a.
    ("net-common", "10.0.0.0/24", "Shared intranet services"),
    ("net-lab-a", "192.168.20.0/24", "Research lab A"),
    ("net-lab-b", "192.168.30.0/24", "Research lab B"),
    # Behind the gw-a → gw-dc relay (no direct leg from any entry gateway).
    ("net-dc", "192.168.40.0/24", "Datacenter network (via relay)"),
]

# name, cas_names, service names (entry or relay hop), network names (exit)
# cas_names shows configurable mapping: a WDG group can be reached from several
# CAS values (a short name AND the full LDAP DN, or an affiliation string).
GROUPS = [
    ("vpn-users", ["vpn-users"], ["gw-a"], ["net-common"]),
    (
        "vpn-admins",
        ["vpn-admins", "cn=vpn-admins,ou=groups,dc=example,dc=org"],
        ["gw-a", "gw-b", "dc-access"],
        ["net-common", "net-lab-a", "net-lab-b", "net-dc"],
    ),
    ("research-lab-a", ["research-lab-a"], ["gw-a"], ["net-lab-a"]),
    ("research-lab-b", ["research-lab-b"], ["gw-b"], ["net-lab-b"]),
    # Driven by the eduPersonAffiliation "staff" attribute rather than memberOf.
    ("staff-network", ["staff"], ["gw-a"], ["net-common"]),
]

# Which exit networks each gateway has a direct leg into.
GATEWAY_NETWORKS = {
    "gw-a": ["net-common", "net-lab-a"],
    "gw-b": ["net-common", "net-lab-b"],
    "gw-dc": ["net-dc"],
}

# from gateway -> to gateway (directed relay links)
RELAY_LINKS = [
    ("gw-a", "gw-dc"),
]


class Command(BaseCommand):
    help = "Seed demo sites, services, gateways, networks and groups (idempotent)."

    def handle(self, *args, **options):
        for name, cas_values in SITES:
            Site.objects.update_or_create(name=name, defaults={"cas_values": cas_values})

        for name, accepts_clients, default_route in SERVICES:
            Service.objects.update_or_create(
                name=name,
                defaults={"accepts_clients": accepts_clients, "default_route": default_route},
            )

        for name, svc_name, site_name, endpoint, subnet, sync_token in GATEWAYS:
            Gateway.objects.update_or_create(
                name=name,
                defaults={
                    "service": Service.objects.get(name=svc_name),
                    "site": Site.objects.get(name=site_name),
                    "endpoint": endpoint,
                    "tunnel_subnet": subnet,
                    "sync_token": sync_token,
                },
            )

        for name, cidr, desc in NETWORKS:
            Network.objects.update_or_create(
                name=name, defaults={"cidr": cidr, "description": desc}
            )

        for name, cas_names, svc_names, net_names in GROUPS:
            group, _ = Group.objects.update_or_create(
                name=name, defaults={"cas_names": cas_names}
            )
            group.services.set(Service.objects.filter(name__in=svc_names))
            group.networks.set(Network.objects.filter(name__in=net_names))

        for gw_name, net_names in GATEWAY_NETWORKS.items():
            gateway = Gateway.objects.get(name=gw_name)
            gateway.networks.set(Network.objects.filter(name__in=net_names))

        for from_name, to_name in RELAY_LINKS:
            RelayLink.objects.get_or_create(
                from_gateway=Gateway.objects.get(name=from_name),
                to_gateway=Gateway.objects.get(name=to_name),
            )

        self.stdout.write(self.style.SUCCESS("Demo data seeded."))
