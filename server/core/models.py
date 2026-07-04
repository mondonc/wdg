"""
WDG authorization & topology model.

The mapping that drives everything: a **Group** grants **Services** (the right
to use their gateways, as entry point or relay hop) and exit **Networks** (the
right to reach). A user's effective access is the union over their groups; the
resolver (``core.resolve``) walks the gateway/relay graph to compute the
multi-tunnel plan. Group membership and the user's home **Site** are mirrored
from CAS attributes at login, but can also be managed by hand in the admin
(resilience when the IdP doesn't release attributes).

See docs/DESIGN-MULTITUNNEL.md for the full design.
"""

from django.contrib.auth.models import User
from django.db import models


class Site(models.Model):
    """
    A physical centre. Gateways belong to a site; a user's home site (mapped
    from a CAS attribute via ``cas_values``, see ``WDG_CAS_SITE_ATTRIBUTE``)
    makes its instances the preferred ones in their plan.
    """

    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    # CAS attribute values that map a user onto this site.
    cas_values = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Service(models.Model):
    """
    A pool of interchangeable gateways rendering one function (one instance
    per site). Users connect to their site's instance and fail over to
    another. Interchangeability is why behaviour flags live here, not on the
    Gateway.
    """

    name = models.CharField(max_length=64, unique=True)
    description = models.CharField(max_length=255, blank=True)
    # Entry service: clients connect directly. Relay-only services (reached
    # through other gateways, e.g. a datacenter hop) set this to False.
    accepts_clients = models.BooleanField(default=True)
    # This service's tunnel captures all traffic not matched elsewhere
    # (0.0.0.0/0) — the traditional full-VPN internet egress.
    default_route = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Gateway(models.Model):
    """A WireGuard node: one site's instance of a service."""

    name = models.CharField(max_length=64, unique=True)
    service = models.ForeignKey(
        Service, on_delete=models.PROTECT, related_name="instances", null=True, blank=True
    )
    site = models.ForeignKey(
        Site, on_delete=models.SET_NULL, related_name="gateways", null=True, blank=True
    )
    # Public [Peer] Endpoint the client dials, e.g. "gw-a.vpn.example.com:51820".
    endpoint = models.CharField(max_length=255)
    public_key = models.CharField(max_length=64, blank=True)
    # Tunnel subnet from which client addresses are allocated, e.g.
    # "10.10.0.0/24". Unique across the fleet: relayed traffic is not NATed
    # between gateways, so client addresses must be unambiguous in the overlay.
    tunnel_subnet = models.CharField(max_length=64, unique=True)
    # Shared secret the gateway agent presents to the sync API.
    sync_token = models.CharField(max_length=128, blank=True)
    # Exit networks this gateway has a direct leg into. Networks further away
    # are reached through RelayLinks.
    networks = models.ManyToManyField("Network", related_name="gateways", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class RelayLink(models.Model):
    """
    A directed inter-gateway WireGuard link: ``from_gateway`` forwards traffic
    toward the networks (and further relays — chains are walked recursively)
    behind ``to_gateway``. Using a relay hop is a privilege: the resolver only
    walks into gateways whose service the user's groups grant.
    """

    from_gateway = models.ForeignKey(
        Gateway, on_delete=models.CASCADE, related_name="relays_out"
    )
    to_gateway = models.ForeignKey(
        Gateway, on_delete=models.CASCADE, related_name="relays_in"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["from_gateway", "to_gateway"], name="unique_relay_link"
            ),
            models.CheckConstraint(
                condition=~models.Q(from_gateway=models.F("to_gateway")),
                name="relay_link_not_self",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_gateway.name} → {self.to_gateway.name}"


class UserProfile(models.Model):
    """WDG per-user state: the home site (CAS-mirrored or admin-assigned)."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wdg_profile")
    site = models.ForeignKey(
        Site, on_delete=models.SET_NULL, related_name="users", null=True, blank=True
    )

    def __str__(self) -> str:
        return f"{self.user.username}@{self.site.name if self.site else '?'}"


class Network(models.Model):
    """A destination network reachable *through* the tunnel (an exit resource)."""

    name = models.CharField(max_length=64, unique=True)
    cidr = models.CharField(max_length=64, help_text="e.g. 192.168.20.0/24")
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.cidr})"


class Group(models.Model):
    """
    An authorization group: grants services (the right to use their gateways,
    as entry or relay hop) + exit networks (the right to reach) to its members.
    The resolver derives the concrete gateways.

    ``cas_names`` lists the CAS attribute values (e.g. ``memberOf`` entries) that
    map onto this group; several CAS names can converge on one WDG group.
    """

    name = models.CharField(max_length=128, unique=True)
    description = models.CharField(max_length=255, blank=True)
    cas_names = models.JSONField(default=list, blank=True)

    services = models.ManyToManyField(Service, related_name="groups", blank=True)
    networks = models.ManyToManyField(Network, related_name="groups", blank=True)
    members = models.ManyToManyField(User, related_name="wdg_groups", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Device(models.Model):
    """A user's enrolled WireGuard peer on a specific gateway."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    gateway = models.ForeignKey(Gateway, on_delete=models.CASCADE, related_name="devices")
    # Not globally unique: a user reuses one keypair across their gateways.
    public_key = models.CharField(max_length=64)
    # Address allocated inside the gateway's tunnel_subnet, e.g. "10.10.0.7".
    address = models.GenericIPAddressField()
    preshared_key = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username", "gateway__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["gateway", "address"], name="unique_address_per_gateway"
            ),
            models.UniqueConstraint(
                fields=["user", "gateway"], name="unique_device_per_user_gateway"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}@{self.gateway.name} ({self.address})"
