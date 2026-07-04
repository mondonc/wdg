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
from collections import defaultdict
from dataclasses import dataclass, field

from django.contrib.auth.models import User

from .models import Device, Gateway, Network, RelayLink, Service, Site


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


# --- Sync-side topology (what each gateway agent must program) ---------------


def _active_topology():
    """
    The relay graph over active gateways, preloaded in four queries:
    ``(gateways, out_edges, in_edges, gw_networks)`` with pk-keyed dicts.
    """
    gateways = {
        g.pk: g
        for g in Gateway.objects.filter(is_active=True).select_related("service")
    }
    out_edges: dict[int, list[int]] = defaultdict(list)
    in_edges: dict[int, list[int]] = defaultdict(list)
    links = RelayLink.objects.filter(
        from_gateway__in=gateways, to_gateway__in=gateways
    ).values_list("from_gateway", "to_gateway")
    for from_pk, to_pk in links:
        out_edges[from_pk].append(to_pk)
        in_edges[to_pk].append(from_pk)
    gw_networks: dict[int, list[tuple[int, str]]] = defaultdict(list)
    pairs = Network.objects.filter(gateways__pk__in=gateways).values_list(
        "gateways__pk", "pk", "cidr"
    )
    for gw_pk, net_pk, cidr in pairs:
        gw_networks[gw_pk].append((net_pk, cidr))
    return gateways, out_edges, in_edges, gw_networks


def _bfs(start_pk: int, edges: dict[int, list[int]]) -> list[int]:
    visited = [start_pk]
    queue = [start_pk]
    while queue:
        current = queue.pop(0)
        for nxt in edges.get(current, []):
            if nxt not in visited:
                visited.append(nxt)
                queue.append(nxt)
    return visited


def relay_peers_for_gateway(gateway: Gateway) -> list[dict]:
    """
    The inter-gateway WireGuard peers this gateway must program — topology
    only, per-user authorization stays in :func:`forward_rules_for_gateway`.

    Toward a downstream relay, AllowedIPs are the networks living behind it
    (its direct legs and everything further down the chain — the forward
    path). Toward an upstream gateway, AllowedIPs are the client tunnel
    subnets behind it (the return path for un-NATed relayed traffic).
    """
    gateways, out_edges, in_edges, gw_networks = _active_topology()
    peers: dict[int, dict] = {}

    def peer(pk: int) -> dict:
        g = gateways[pk]
        return peers.setdefault(
            pk,
            {
                "name": g.name,
                "public_key": g.public_key,
                "endpoint": g.endpoint,
                "allowed_ips": [],
            },
        )

    for down_pk in out_edges.get(gateway.pk, []):
        entry = peer(down_pk)
        for pk in _bfs(down_pk, out_edges):
            for _net_pk, cidr in gw_networks.get(pk, []):
                if cidr not in entry["allowed_ips"]:
                    entry["allowed_ips"].append(cidr)

    for up_pk in in_edges.get(gateway.pk, []):
        entry = peer(up_pk)
        for pk in _bfs(up_pk, in_edges):
            subnet = gateways[pk].tunnel_subnet
            if subnet not in entry["allowed_ips"]:
                entry["allowed_ips"].append(subnet)

    return sorted(peers.values(), key=lambda p: p["name"])


def masq_subnets_for_gateway(gateway: Gateway) -> list[str]:
    """
    Client tunnel subnets whose traffic may exit through this gateway's legs
    (its own + every upstream gateway's): each needs a MASQUERADE rule on the
    last leg so target networks only ever see the local gateway.
    """
    gateways, _out, in_edges, _nets = _active_topology()
    subnets = []
    for pk in _bfs(gateway.pk, in_edges):
        subnet = gateways[pk].tunnel_subnet
        if subnet not in subnets:
            subnets.append(subnet)
    return subnets


def forward_rules_for_gateway(gateway: Gateway) -> list[dict]:
    """
    Per-client egress permissions this hop must enforce, as
    ``{"src": <client address>, "dst": <network cidr>}`` pairs — local
    clients and relayed ones alike (their addresses belong to other
    gateways' tunnel subnets; no inter-gateway NAT).

    A pair is emitted when this gateway sits on the client's path (BFS tree,
    restricted to the user's granted services) from their entry gateway to
    the gateway carrying the target network.
    """
    gateways, out_edges, _in, gw_networks = _active_topology()

    devices = list(
        Device.objects.filter(
            is_active=True, user__is_active=True, gateway__pk__in=gateways
        )
    )
    user_ids = {d.user_id for d in devices}
    user_services: dict[int, set[int]] = defaultdict(set)
    for svc_pk, uid in Service.objects.filter(groups__members__in=user_ids).values_list(
        "pk", "groups__members"
    ):
        user_services[uid].add(svc_pk)
    user_networks: dict[int, set[int]] = defaultdict(set)
    for net_pk, uid in Network.objects.filter(groups__members__in=user_ids).values_list(
        "pk", "groups__members"
    ):
        user_networks[uid].add(net_pk)

    rules: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for device in devices:
        granted_svc = user_services.get(device.user_id, set())
        granted_net = user_networks.get(device.user_id, set())
        entry = gateways.get(device.gateway_id)
        if (
            entry is None
            or entry.service is None
            or entry.service_id not in granted_svc
            or not entry.service.accepts_clients
        ):
            continue

        # BFS tree from the entry gateway, walking only granted services.
        parents: dict[int, int | None] = {entry.pk: None}
        queue = [entry.pk]
        while queue:
            current = queue.pop(0)
            for nxt in out_edges.get(current, []):
                if nxt in parents or gateways[nxt].service_id not in granted_svc:
                    continue
                parents[nxt] = current
                queue.append(nxt)

        for visited_pk in parents:
            for net_pk, cidr in gw_networks.get(visited_pk, []):
                if net_pk not in granted_net:
                    continue
                node: int | None = visited_pk
                while node is not None and node != gateway.pk:
                    node = parents[node]
                if node != gateway.pk:
                    continue  # this hop is not on the path to that network
                key = (device.address, cidr)
                if key not in seen:
                    seen.add(key)
                    rules.append({"src": device.address, "dst": cidr})
    return rules


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
