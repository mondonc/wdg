"""
Resolve a user's effective access from their group membership, and allocate
tunnel addresses.

Two generations coexist here (see docs/DESIGN-MULTITUNNEL.md):

- The **plan** resolver (:func:`plan_for_user`): grants are services +
  networks; the relay graph is walked to find which networks each entry
  service reaches, and overlaps are partitioned deterministically so the
  client's tunnels never claim the same route twice.
- The **legacy** helpers (:func:`gateways_for_user`,
  :func:`networks_via_gateway`, …) still back ``/api/config/`` and the
  gateway sync API. They see *direct* legs only — relayed networks enter the
  runtime path in M9 (agent support).
"""

import ipaddress
from dataclasses import dataclass, field

from django.contrib.auth.models import User

from .models import Device, Gateway, Network, Service, Site


def granted_services(user: User) -> list[Service]:
    return list(Service.objects.filter(groups__in=user.wdg_groups.all()).distinct())


def granted_networks(user: User) -> list[Network]:
    return list(Network.objects.filter(groups__in=user.wdg_groups.all()).distinct())


def user_site(user: User) -> Site | None:
    profile = getattr(user, "wdg_profile", None)
    return profile.site if profile else None


def access_for_user(user: User) -> dict:
    """
    The gateways a client may connect to (active instances of granted
    entry services) and the networks their groups grant.
    """
    gateways = (
        Gateway.objects.filter(
            service__groups__in=user.wdg_groups.all(),
            service__accepts_clients=True,
            is_active=True,
        )
        .select_related("service", "site")
        .distinct()
    )
    return {"gateways": list(gateways), "networks": granted_networks(user)}


def gateways_for_user(user: User) -> list[Gateway]:
    return access_for_user(user)["gateways"]


def networks_via_gateway(user: User, gateway: Gateway) -> list["Network"]:
    """
    Exit networks a user may reach *directly through this gateway*: the
    networks their groups grant, intersected with the gateway's direct legs.
    (Relay-reachable networks are not included: the runtime path for them
    lands in M9.)
    """
    granted = {n.pk for n in granted_networks(user)}
    return [n for n in gateway.networks.all() if n.pk in granted]


def networks_via_gateway_bulk(user_ids: set[int], gateway: Gateway) -> dict[int, list[str]]:
    """
    Batch variant of :func:`networks_via_gateway` for the sync API: the CIDRs
    each user may reach through this gateway, computed in two queries instead
    of several per user.
    """
    granted: dict[int, set[int]] = {uid: set() for uid in user_ids}
    pairs = Network.objects.filter(groups__members__in=user_ids).values_list(
        "pk", "groups__members"
    )
    for network_pk, user_id in pairs:
        granted[user_id].add(network_pk)
    gateway_networks = list(gateway.networks.all())
    return {
        uid: [n.cidr for n in gateway_networks if n.pk in granted[uid]]
        for uid in user_ids
    }


def allowed_ips_for_user(user: User, gateway: Gateway | None = None) -> list[str]:
    """
    AllowedIPs to push into the client conf (legacy single-tunnel path).

    With a gateway, scope to what that gateway can route (entry/exit coherence);
    without one, the full set of granted networks (used by tests/overview).
    """
    if gateway is not None:
        return [n.cidr for n in networks_via_gateway(user, gateway)]
    return [n.cidr for n in granted_networks(user)]


# --- Multi-tunnel plan -------------------------------------------------------


def reachable_gateways(entry: Gateway, allowed_service_ids: set[int]) -> list[Gateway]:
    """
    Walk the relay graph from ``entry``: follow RelayLink edges, but only into
    active gateways whose service is granted (a relay hop is a privilege).
    Cycle-safe. Returns entry + every reachable relay gateway.
    """
    visited: dict[int, Gateway] = {entry.pk: entry}
    queue = [entry]
    while queue:
        gateway = queue.pop(0)
        links = gateway.relays_out.select_related("to_gateway__service", "to_gateway__site")
        for link in links:
            nxt = link.to_gateway
            if nxt.pk in visited or not nxt.is_active:
                continue
            if nxt.service_id not in allowed_service_ids:
                continue
            visited[nxt.pk] = nxt
            queue.append(nxt)
    return list(visited.values())


def _reachable_cidrs(entry: Gateway, allowed_service_ids: set[int], granted_net_pks: dict[int, str]) -> list[str]:
    """Granted CIDRs reachable from ``entry`` (direct legs + relay walk), stable order."""
    cidrs: list[str] = []
    for gateway in reachable_gateways(entry, allowed_service_ids):
        for network in gateway.networks.all():
            cidr = granted_net_pks.get(network.pk)
            if cidr is not None and cidr not in cidrs:
                cidrs.append(cidr)
    return cidrs


@dataclass
class PlanTunnel:
    service: Service
    allowed_ips: list[str]
    # Active instances in failover order: the user's site first, then by name.
    instances: list[Gateway] = field(default_factory=list)


def plan_for_user(user: User) -> list[PlanTunnel]:
    """
    Compute the user's multi-tunnel plan.

    One tunnel per granted entry service that reaches at least one granted
    network (or carries the default route). Tunnels are ordered specific-first,
    default-route last; overlapping networks are assigned to exactly one
    tunnel (deterministic partition), so AllowedIPs never collide client-side.
    """
    services = granted_services(user)
    service_ids = {s.pk for s in services}
    granted_net_pks = {n.pk: n.cidr for n in granted_networks(user)}
    site = user_site(user)

    entry_services = sorted(
        (s for s in services if s.accepts_clients),
        key=lambda s: (s.default_route, s.name),
    )

    claimed: set[str] = set()
    tunnels: list[PlanTunnel] = []
    for service in entry_services:
        instances = sorted(
            service.instances.filter(is_active=True).select_related("site"),
            key=lambda g: (0 if (site and g.site_id == site.pk) else 1, g.name),
        )
        if not instances:
            continue

        # Union over instances: a failover instance may route a superset; its
        # own egress rules still constrain what is actually reachable.
        cidrs: list[str] = []
        for gateway in instances:
            for cidr in _reachable_cidrs(gateway, service_ids, granted_net_pks):
                if cidr not in cidrs:
                    cidrs.append(cidr)

        if service.default_route:
            allowed = ["0.0.0.0/0"]
        else:
            allowed = [c for c in cidrs if c not in claimed]
            claimed.update(allowed)
            if not allowed:
                continue  # nothing left for this tunnel to route

        tunnels.append(PlanTunnel(service=service, allowed_ips=allowed, instances=instances))

    return tunnels


# --- Address allocation ------------------------------------------------------


def allocate_address(gateway: Gateway) -> str:
    """
    Allocate the next free host address in the gateway's tunnel subnet.

    The first usable host is reserved for the gateway itself; devices take the
    rest. Raises :class:`RuntimeError` when the subnet is exhausted.
    """
    net = ipaddress.ip_network(gateway.tunnel_subnet, strict=False)
    hosts = net.hosts()
    gateway_ip = next(hosts, None)  # reserved for the gateway
    used = set(
        Device.objects.filter(gateway=gateway).values_list("address", flat=True)
    )
    used.add(str(gateway_ip))
    for host in hosts:
        candidate = str(host)
        if candidate not in used:
            return candidate
    raise RuntimeError(f"gateway {gateway.name}: tunnel subnet exhausted")
