"""Render a WireGuard ``.conf`` for a provisioned device.

The private key is never known to the server: the client substitutes the
``__PRIVATE_KEY__`` placeholder locally before handing the file to WireGuard.
"""

from core.models import Device, Gateway


def build_config(device: Device, gateway: Gateway, allowed_ips: list[str]) -> str:
    aips = ", ".join(allowed_ips)
    return (
        "[Interface]\n"
        "PrivateKey = __PRIVATE_KEY__\n"
        f"Address = {device.address}/32\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {gateway.public_key}\n"
        f"PresharedKey = {device.preshared_key}\n"
        f"Endpoint = {gateway.endpoint}\n"
        f"AllowedIPs = {aips}\n"
        "PersistentKeepalive = 25\n"
    )
