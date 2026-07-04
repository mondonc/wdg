"""
Resolve a user's effective access from their group membership, and allocate
tunnel addresses. This is the heart of the group-driven entry/exit routing.
"""

import ipaddress

from django.contrib.auth.models import User

from .models import Device, Gateway, Network


def access_for_user(user: User) -> dict:
    """
    Union, over the user's groups, of the entry gateways and exit networks.

    Returns ``{"gateways": [Gateway], "networks": [Network]}`` (active gateways
    only). Empty lists mean the user has no VPN access.
    """
    groups = user.wdg_groups.all()
    gateways = Gateway.objects.filter(groups__in=groups, is_active=True).distinct()
    networks = Network.objects.filter(groups__in=groups).distinct()
    return {"gateways": list(gateways), "networks": list(networks)}


def gateways_for_user(user: User) -> list[Gateway]:
    return access_for_user(user)["gateways"]


def networks_via_gateway(user: User, gateway: Gateway) -> list["Network"]:
    """
    Exit networks a user may reach *through this gateway*: the networks their
    groups grant, intersected with the networks the gateway can actually route.
    """
    granted = {n.pk for n in access_for_user(user)["networks"]}
    return [n for n in gateway.networks.all() if n.pk in granted]


def allowed_ips_for_user(user: User, gateway: Gateway | None = None) -> list[str]:
    """
    AllowedIPs to push into the client conf.

    With a gateway, scope to what that gateway can route (entry/exit coherence);
    without one, the full set of granted networks (used by tests/overview).
    """
    if gateway is not None:
        return [n.cidr for n in networks_via_gateway(user, gateway)]
    return [n.cidr for n in access_for_user(user)["networks"]]


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
