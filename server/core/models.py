"""
WDG authorization & topology model.

The mapping that drives everything: a **Group** grants a set of entry
**Gateways** and a set of exit **Networks**. A user's effective access is the
union over the groups they belong to (see ``core.resolve``). Group membership is
mirrored from CAS attributes at login, but can also be managed by hand in the
admin (resilience when the IdP doesn't release attributes).
"""

from django.contrib.auth.models import User
from django.db import models


class Gateway(models.Model):
    """A WireGuard egress node the client connects to (the tunnel entry point)."""

    name = models.CharField(max_length=64, unique=True)
    # Public [Peer] Endpoint the client dials, e.g. "gw-a.vpn.example.com:51820".
    endpoint = models.CharField(max_length=255)
    public_key = models.CharField(max_length=64, blank=True)
    # Tunnel subnet from which client addresses are allocated, e.g. "10.10.0.0/24".
    tunnel_subnet = models.CharField(max_length=64)
    # Shared secret the gateway agent presents to the sync API.
    sync_token = models.CharField(max_length=128, blank=True)
    # Exit networks this gateway can route to. A user's AllowedIPs on this
    # gateway are their granted networks intersected with these.
    networks = models.ManyToManyField("Network", related_name="gateways", blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


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
    An authorization group: grants entry gateways + exit networks to its members.

    ``cas_names`` lists the CAS attribute values (e.g. ``memberOf`` entries) that
    map onto this group; several CAS names can converge on one WDG group.
    """

    name = models.CharField(max_length=128, unique=True)
    description = models.CharField(max_length=255, blank=True)
    cas_names = models.JSONField(default=list, blank=True)

    gateways = models.ManyToManyField(Gateway, related_name="groups", blank=True)
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
