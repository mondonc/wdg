"""
Multi-tunnel orchestration: turn the control plane's plan (``/api/plan/``)
into simultaneous WireGuard tunnels, with connect-time failover between a
service's instances.

The plan arrives ordered (specific tunnels first, the default-route one
last) with disjoint AllowedIPs, so tunnels never fight over a route. For
each tunnel, instances are tried in the server-given order (the user's home
site first): an instance that does not complete a WireGuard handshake within
``HANDSHAKE_TIMEOUT`` seconds is torn down and the next one is tried.
PersistentKeepalive makes the handshake start immediately after ``up``.

Platform specifics (wg-quick / wireguard.exe) live in :mod:`wg_client.tunnel`;
they are injectable here so the failover logic is unit-testable.
"""

import time

from wg_client import tunnel
from wg_client.i18n import _

HANDSHAKE_TIMEOUT = 12  # seconds
_POLL = 0.5


class TunnelError(RuntimeError):
    """No instance of a service could be brought up."""


def _quiet_down(down, name: str):
    """Tear down a half-up tunnel; the interface may not even exist."""
    try:
        down(name)
    except Exception:
        pass


def iface_name(index: int) -> str:
    """Short, index-based interface names (Linux caps names at 15 chars)."""
    return f"wdg{index}"


def build_conf(private_key: str, tunnel_plan: dict, instance: dict) -> str:
    """The WireGuard .conf for one instance of one planned tunnel."""
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {instance['address']}/32\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {instance['public_key']}\n"
        f"PresharedKey = {instance['preshared_key']}\n"
        f"Endpoint = {instance['endpoint']}\n"
        f"AllowedIPs = {', '.join(tunnel_plan['allowed_ips'])}\n"
        "PersistentKeepalive = 25\n"
    )


def wait_handshake(name: str, timeout: float = HANDSHAKE_TIMEOUT, handshake_age=None) -> bool:
    """True once the tunnel has completed a handshake, False on timeout."""
    handshake_age = handshake_age or tunnel.handshake_age
    deadline = time.time() + timeout
    while time.time() < deadline:
        age = handshake_age(name)
        if age is not None:
            return True
        time.sleep(_POLL)
    return False


def connect_plan(plan: dict, private_key: str, up=None, down=None, wait=None) -> list[dict]:
    """
    Bring up every tunnel of the plan, trying each instance in failover
    order. Returns the active tunnels as
    ``[{"iface", "service", "gateway", "allowed_ips"}]``; raises
    :class:`TunnelError` (after tearing down what was already up) when no
    instance of a service answers.
    """
    up = up or tunnel.up
    down = down or tunnel.down
    wait = wait or wait_handshake

    active: list[dict] = []
    try:
        for index, tunnel_plan in enumerate(plan["tunnels"]):
            name = iface_name(index)
            connected = None
            for instance in tunnel_plan["instances"]:
                if not instance.get("address") or not instance.get("public_key"):
                    continue  # not registered there / gateway key unknown yet
                print(_("Connecting {service} via {gateway}...").format(
                    service=tunnel_plan["service"], gateway=instance["gateway"]))
                try:
                    up(name, build_conf(private_key, tunnel_plan, instance))
                except Exception as exc:
                    # A dead instance can fail at bring-up already (e.g. its
                    # hostname no longer resolves): that IS the failover case.
                    print(_("Bringing up {gateway} failed ({error}), trying next instance.").format(
                        gateway=instance["gateway"], error=exc))
                    _quiet_down(down, name)
                    continue
                if wait(name):
                    connected = instance
                    break
                print(_("No handshake with {gateway}, trying next instance.").format(
                    gateway=instance["gateway"]))
                _quiet_down(down, name)
            if connected is None:
                raise TunnelError(
                    _("No reachable instance for service '{service}'.").format(
                        service=tunnel_plan["service"])
                )
            active.append({
                "iface": name,
                "service": tunnel_plan["service"],
                "gateway": connected["gateway"],
                "allowed_ips": tunnel_plan["allowed_ips"],
            })
    except BaseException:
        for state in active:
            try:
                down(state["iface"])
            except Exception:
                pass
        raise
    return active


def disconnect_all(states: list[dict], down=None) -> list[str]:
    """Bring down the recorded tunnels; returns the interfaces brought down."""
    down = down or tunnel.down
    closed = []
    for state in states:
        try:
            down(state["iface"])
            closed.append(state["iface"])
        except Exception:
            pass
    return closed
