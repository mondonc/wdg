"""
Device provisioning: pick the user's entry gateway, allocate an address and a
per-device PSK, and (idempotently) register the client's public key.

M2 provisions a single primary gateway per user (first active allowed gateway,
by name). Multi-gateway provisioning is added in M4.
"""

import base64
import secrets

from django.contrib.auth.models import User
from django.db import transaction

from core import resolve
from core.models import Device, Gateway


def generate_psk() -> str:
    """A fresh WireGuard preshared key (32 random bytes, base64)."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def primary_gateway(user: User) -> Gateway | None:
    gateways = resolve.access_for_user(user)["gateways"]
    return gateways[0] if gateways else None


def _register_on(user: User, gateway: Gateway, public_key: str) -> Device:
    device = (
        Device.objects.select_for_update()
        .filter(user=user, gateway=gateway)
        .first()
    )
    if device is None:
        return Device.objects.create(
            user=user,
            gateway=gateway,
            public_key=public_key,
            address=resolve.allocate_address(gateway),
            preshared_key=generate_psk(),
        )

    changed = []
    if device.public_key != public_key:
        device.public_key = public_key
        changed.append("public_key")
    if not device.is_active:
        device.is_active = True
        changed.append("is_active")
    if changed:
        device.save(update_fields=changed)
    return device


@transaction.atomic
def register_devices(user: User, public_key: str) -> list[Device]:
    """
    Register (or update) the user's device on *every* gateway they may use.

    One keypair is reused across gateways; each gateway gets its own address and
    PSK, both stable across re-registration. Returns the list of devices (empty
    if the user has no VPN access).
    """
    return [
        _register_on(user, gateway, public_key)
        for gateway in resolve.gateways_for_user(user)
    ]
