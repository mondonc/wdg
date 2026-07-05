"""
Seed a *presentation scenario* into the database, replacing the current
topology, so ``topology_export`` (make doc / doc-scenarios) can render it.

Two scenarios tell the migration story:

- ``sans-wdg``: today's landscape modelled with WDG objects — DGTW access
  boxes (direct, VPN, RDP bastions), one service per box (no pooling, no
  failover), duplicated legs into the VLANs. The generated diagram shows
  the silos.
- ``avec-wdg``: the target — per-centre entry gateways pooled into user and
  admin services (connect-time failover), admin VLANs reached only through
  relay-only gateways.
- ``demo``: restores the standard demo seed (deploy/cas-test users).

WARNING: seeding a scenario WIPES the topology tables (gateways, services,
sites, networks, groups, relay links) and, by cascade, enrolled devices.
Dev/demo stacks only. Users are never touched.

The legacy boxes in ``sans-wdg`` are not WireGuard nodes; the mandatory
``tunnel_subnet`` is filled with 172.31.x.0/24 placeholders (the field is
required and must be unique) and should be read as "n/a" on that diagram.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Gateway, Group, Network, RelayLink, Service, Site

# scenario name -> dict with keys: sites, services, gateways, networks,
# gateway_networks, relay_links, groups (see the two definitions below)
SCENARIOS = {}

# --- Cas 1 : sans WDG — accès actuels en silos ------------------------------
SCENARIOS["sans-wdg"] = {
    "sites": [
        ("centre-a", []),
        ("centre-b", []),
        ("datacenter", []),
    ],
    # One service per box: nothing is interchangeable, so no failover.
    "services": [
        # name, description, accepts_clients, default_route
        ("dgtw-direct-a", "DGTW centre A — accès direct", True, False),
        ("dgtw-direct-b", "DGTW centre B — accès direct", True, False),
        ("vpn-a", "DGTW centre A — concentrateur VPN", True, True),
        ("vpn-b", "DGTW centre B — concentrateur VPN", True, True),
        ("bastion-rdp-a", "Bastion RDP admin centre A", True, False),
        ("bastion-rdp-dc", "Bastion RDP admin datacenter", True, False),
    ],
    "gateways": [
        # name, service, site, endpoint, tunnel_subnet (placeholder: legacy
        # boxes have no WireGuard overlay)
        ("dgtw-a", "dgtw-direct-a", "centre-a", "dgtw-a.example.org", "172.31.1.0/24"),
        ("dgtw-b", "dgtw-direct-b", "centre-b", "dgtw-b.example.org", "172.31.2.0/24"),
        ("vpn-gw-a", "vpn-a", "centre-a", "vpn-a.example.org:1701", "172.31.3.0/24"),
        ("vpn-gw-b", "vpn-b", "centre-b", "vpn-b.example.org:1701", "172.31.4.0/24"),
        ("rdp-a", "bastion-rdp-a", "centre-a", "rdp-a.example.org:3389", "172.31.5.0/24"),
        ("rdp-dc", "bastion-rdp-dc", "datacenter", "rdp-dc.example.org:3389", "172.31.6.0/24"),
    ],
    "networks": [
        ("vlan-users-a", "10.20.10.0/24", "VLAN utilisateurs centre A"),
        ("vlan-users-b", "10.20.20.0/24", "VLAN utilisateurs centre B"),
        ("vlan-metier", "10.30.0.0/23", "Applications métier (partagé)"),
        ("vlan-admin-a", "10.40.10.0/24", "VLAN admin centre A"),
        ("vlan-admin-dc", "10.40.40.0/24", "VLAN admin datacenter"),
    ],
    # Duplicated legs = the silos the diagram must show: the same VLANs are
    # plumbed into several boxes, admin VLANs only behind their own bastion.
    "gateway_networks": {
        "dgtw-a": ["vlan-users-a", "vlan-metier"],
        "dgtw-b": ["vlan-users-b", "vlan-metier"],
        "vpn-gw-a": ["vlan-users-a", "vlan-metier"],
        "vpn-gw-b": ["vlan-users-b", "vlan-metier"],
        "rdp-a": ["vlan-admin-a"],
        "rdp-dc": ["vlan-admin-dc"],
    },
    "relay_links": [],  # nothing talks to anything else: islands
    "groups": [
        # name, cas_names, services, networks
        ("utilisateurs-a", [], ["dgtw-direct-a", "vpn-a"], ["vlan-users-a", "vlan-metier"]),
        ("utilisateurs-b", [], ["dgtw-direct-b", "vpn-b"], ["vlan-users-b", "vlan-metier"]),
        ("admins", [], ["bastion-rdp-a", "bastion-rdp-dc"], ["vlan-admin-a", "vlan-admin-dc"]),
    ],
}

# --- Cas 2 : avec WDG — architecture cible ----------------------------------
SCENARIOS["avec-wdg"] = {
    "sites": [
        ("centre-a", ["centre-a"]),
        ("centre-b", ["centre-b"]),
        ("datacenter", []),
    ],
    # Two entry pools (réservoirs): one per population. Instances per centre
    # are interchangeable -> connect-time failover. Admin VLANs sit behind a
    # relay-only service: no client terminates there directly.
    "services": [
        ("wdg-users", "Réservoir utilisateurs (failover par centre)", True, False),
        ("wdg-admins", "Réservoir admins (failover par centre)", True, False),
        ("relais-admin", "Relais vers les VLANs d'admin", False, False),
    ],
    "gateways": [
        ("gw-users-a", "wdg-users", "centre-a", "gw-users-a.vpn.example.org:51820", "10.10.10.0/24"),
        ("gw-users-b", "wdg-users", "centre-b", "gw-users-b.vpn.example.org:51820", "10.10.20.0/24"),
        ("gw-admins-a", "wdg-admins", "centre-a", "gw-admins-a.vpn.example.org:51820", "10.10.11.0/24"),
        ("gw-admins-b", "wdg-admins", "centre-b", "gw-admins-b.vpn.example.org:51820", "10.10.21.0/24"),
        ("relay-admin-a", "relais-admin", "centre-a", "relay-admin-a.vpn.example.org:51820", "10.10.12.0/24"),
        ("relay-admin-b", "relais-admin", "centre-b", "relay-admin-b.vpn.example.org:51820", "10.10.22.0/24"),
        ("relay-admin-dc", "relais-admin", "datacenter", "relay-admin-dc.vpn.example.org:51820", "10.10.40.0/24"),
    ],
    "networks": [
        ("vlan-users-a", "10.20.10.0/24", "VLAN utilisateurs centre A"),
        ("vlan-users-b", "10.20.20.0/24", "VLAN utilisateurs centre B"),
        ("vlan-metier", "10.30.0.0/23", "Applications métier (partagé)"),
        ("vlan-admin-a", "10.40.10.0/24", "VLAN admin centre A"),
        ("vlan-admin-b", "10.40.20.0/24", "VLAN admin centre B"),
        ("vlan-admin-dc", "10.40.40.0/24", "VLAN admin datacenter"),
    ],
    "gateway_networks": {
        "gw-users-a": ["vlan-users-a", "vlan-metier"],
        "gw-users-b": ["vlan-users-b", "vlan-metier"],
        "gw-admins-a": ["vlan-metier"],
        "gw-admins-b": ["vlan-metier"],
        "relay-admin-a": ["vlan-admin-a"],
        "relay-admin-b": ["vlan-admin-b"],
        "relay-admin-dc": ["vlan-admin-dc"],
    },
    # Both admin entry points reach every admin relay: whichever instance a
    # client fails over to, the admin VLANs stay reachable.
    "relay_links": [
        ("gw-admins-a", "relay-admin-a"),
        ("gw-admins-a", "relay-admin-dc"),
        ("gw-admins-b", "relay-admin-b"),
        ("gw-admins-b", "relay-admin-dc"),
    ],
    "groups": [
        ("utilisateurs", ["vpn-users"], ["wdg-users"],
         ["vlan-users-a", "vlan-users-b", "vlan-metier"]),
        ("admins", ["vpn-admins"], ["wdg-admins", "relais-admin"],
         ["vlan-metier", "vlan-admin-a", "vlan-admin-b", "vlan-admin-dc"]),
    ],
}


def wipe_topology():
    """Delete the whole topology (and, by cascade, enrolled devices)."""
    RelayLink.objects.all().delete()
    Gateway.objects.all().delete()  # cascades Device
    Service.objects.all().delete()
    Network.objects.all().delete()
    Group.objects.all().delete()
    Site.objects.all().delete()


def seed(data):
    for name, cas_values in data["sites"]:
        Site.objects.create(name=name, cas_values=cas_values)
    for name, desc, accepts_clients, default_route in data["services"]:
        Service.objects.create(
            name=name, description=desc,
            accepts_clients=accepts_clients, default_route=default_route,
        )
    for name, svc, site, endpoint, subnet in data["gateways"]:
        Gateway.objects.create(
            name=name,
            service=Service.objects.get(name=svc),
            site=Site.objects.get(name=site),
            endpoint=endpoint,
            tunnel_subnet=subnet,
        )
    for name, cidr, desc in data["networks"]:
        Network.objects.create(name=name, cidr=cidr, description=desc)
    for gw_name, net_names in data["gateway_networks"].items():
        Gateway.objects.get(name=gw_name).networks.set(
            Network.objects.filter(name__in=net_names)
        )
    for from_name, to_name in data["relay_links"]:
        RelayLink.objects.create(
            from_gateway=Gateway.objects.get(name=from_name),
            to_gateway=Gateway.objects.get(name=to_name),
        )
    for name, cas_names, svc_names, net_names in data["groups"]:
        group = Group.objects.create(name=name, cas_names=cas_names)
        group.services.set(Service.objects.filter(name__in=svc_names))
        group.networks.set(Network.objects.filter(name__in=net_names))


class Command(BaseCommand):
    help = (
        "Replace the topology with a presentation scenario "
        "(sans-wdg | avec-wdg | demo). Destructive: wipes gateways, "
        "services, sites, networks, groups and enrolled devices."
    )

    def add_arguments(self, parser):
        parser.add_argument("scenario", choices=[*SCENARIOS, "demo"])

    def handle(self, *args, **options):
        scenario = options["scenario"]
        # All-or-nothing: a failure mid-seed rolls the wipe back too.
        with transaction.atomic():
            wipe_topology()
            if scenario == "demo":
                call_command("seed_demo", stdout=self.stdout)
            else:
                seed(SCENARIOS[scenario])
        self.stdout.write(self.style.WARNING(
            "Topology replaced: enrolled devices were removed (gateway cascade)."
        ))
        if scenario != "demo":
            self.stdout.write(self.style.SUCCESS(f"Scenario '{scenario}' seeded."))
