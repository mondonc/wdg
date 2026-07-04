"""
WDG gateway agent.

Runs on each egress node. It loads (or generates once) a persistent WireGuard
keypair, brings up the tunnel interface, and then continuously reconciles its
peers against the control plane's sync API: peers the control plane authorizes
are programmed with `wg set`; peers that disappear are removed. It also
installs the NAT/forwarding rules that let authorized tunnel traffic egress to
the protected networks.

Kernel WireGuard is used (``ip link add type wireguard``); the container only
needs NET_ADMIN.
"""

import os
import subprocess
import sys
import tempfile
import time

import requests

CONTROL_PLANE = os.environ["WDG_CONTROL_PLANE"].rstrip("/")
SYNC_TOKEN = os.environ["WDG_GATEWAY_TOKEN"]
IFACE = os.environ.get("WDG_WG_IFACE", "wg0")
POLL_INTERVAL = int(os.environ.get("WDG_POLL_INTERVAL", "5"))
# The private key persists here so a restart keeps the public key the clients'
# configs point at (an ephemeral key would silently break every tunnel).
STATE_DIR = os.environ.get("WDG_STATE_DIR", "/var/lib/wdg")


def run(cmd: list[str], check: bool = True, capture: bool = False) -> str:
    result = subprocess.run(cmd, check=check, text=True, capture_output=capture)
    return result.stdout if capture else ""


def log(msg: str):
    print(f"[agent] {msg}", flush=True)


# --- WireGuard key management ---------------------------------------------

def load_or_create_keypair() -> tuple[str, str]:
    key_file = os.path.join(STATE_DIR, "wg-private.key")
    if os.path.exists(key_file):
        with open(key_file) as fh:
            private = fh.read().strip()
    else:
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        private = subprocess.run(
            ["wg", "genkey"], check=True, text=True, capture_output=True
        ).stdout.strip()
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(private)
    public = subprocess.run(
        ["wg", "pubkey"], input=private, check=True, text=True, capture_output=True
    ).stdout.strip()
    return private, public


def _write_secret(value: str) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as fh:
        fh.write(value)
    return path


# --- Interface + NAT setup -------------------------------------------------

def iface_exists() -> bool:
    return subprocess.run(["ip", "link", "show", IFACE], capture_output=True).returncode == 0


def _set_private_key(private_key: str, listen_port: int):
    key_path = _write_secret(private_key)
    try:
        run(["wg", "set", IFACE, "private-key", key_path, "listen-port", str(listen_port)])
    finally:
        os.unlink(key_path)


def ensure_interface(private_key: str, public_key: str, address: str, prefixlen: int, listen_port: int):
    if iface_exists():
        # A pre-existing interface (agent restart on a live host) may carry a
        # different key than the one we advertise to the control plane.
        current = run(["wg", "show", IFACE, "public-key"], capture=True).strip()
        if current != public_key:
            log(f"interface {IFACE} key out of sync, reinstalling private key")
            _set_private_key(private_key, listen_port)
        return
    log(f"creating interface {IFACE} ({address}/{prefixlen}, port {listen_port})")
    run(["ip", "link", "add", "dev", IFACE, "type", "wireguard"])
    _set_private_key(private_key, listen_port)
    run(["ip", "addr", "add", f"{address}/{prefixlen}", "dev", IFACE])
    run(["ip", "link", "set", IFACE, "up"])


FWD_CHAIN = "WDG_FWD"


def _iptables_ensure(rule: list[str], table: str | None = None):
    # The table option (-t) must come before -C/-A, hence the explicit prefix.
    base = ["iptables"] + (["-t", table] if table else [])
    if subprocess.run([*base, "-C", *rule], capture_output=True).returncode != 0:
        run([*base, "-A", *rule])


def ensure_forwarding():
    """One-time forwarding scaffolding. Per-client egress lives in FWD_CHAIN."""
    # Best-effort: compose also sets this sysctl.
    subprocess.run(["sysctl", "-w", "net.ipv4.ip_forward=1"], capture_output=True)

    # A dedicated chain holds the per-client egress rules (rebuilt each sync).
    subprocess.run(["iptables", "-N", FWD_CHAIN], capture_output=True)
    _iptables_ensure(["FORWARD", "-i", IFACE, "-j", FWD_CHAIN])
    # Return traffic to connected clients (leg -> tunnel).
    _iptables_ensure(
        ["FORWARD", "-o", IFACE, "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED", "-j", "ACCEPT"]
    )


def ensure_masquerade(subnets: list[str]):
    """
    MASQUERADE client subnets leaving through the legs (never the tunnel
    itself: inter-gateway relay traffic keeps the client's address). Covers
    this gateway's own subnet plus the upstream ones the sync reports.
    """
    for subnet in subnets:
        _iptables_ensure(
            ["POSTROUTING", "-s", subnet, "!", "-o", IFACE, "-j", "MASQUERADE"], table="nat"
        )


_egress_rules: list[tuple[str, str]] | None = None


def rebuild_egress_firewall(forward_rules: list[dict]):
    """
    Rebuild FWD_CHAIN from the control plane's (src client, dst network)
    permissions — local and relayed clients alike; anything else entering
    from the tunnel is dropped (default-deny egress). The leading conntrack
    rule lets transit replies (tunnel -> tunnel on a middle hop) through.
    Skipped when nothing changed: the flush/append cycle briefly leaves the
    chain empty, and its behaviour then depends on the host's FORWARD policy.
    """
    global _egress_rules
    rules = [(r["src"], r["dst"]) for r in forward_rules]
    if rules == _egress_rules:
        return
    run(["iptables", "-F", FWD_CHAIN])
    run(["iptables", "-A", FWD_CHAIN, "-m", "conntrack", "--ctstate",
         "RELATED,ESTABLISHED", "-j", "ACCEPT"])
    for address, net in rules:
        run(["iptables", "-A", FWD_CHAIN, "-s", address, "-d", net, "-j", "ACCEPT"])
    run(["iptables", "-A", FWD_CHAIN, "-j", "DROP"])
    _egress_rules = rules


# --- Peer reconciliation ---------------------------------------------------

def current_peers() -> set[str]:
    out = subprocess.run(
        ["wg", "show", IFACE, "peers"], text=True, capture_output=True
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def apply_peer(peer: dict):
    args = ["wg", "set", IFACE, "peer", peer["public_key"]]
    psk_path = None
    if peer.get("preshared_key"):
        psk_path = _write_secret(peer["preshared_key"])
        args += ["preshared-key", psk_path]
    args += ["allowed-ips", ",".join(peer["allowed_ips"])]
    try:
        run(args)
    finally:
        if psk_path:
            os.unlink(psk_path)


def apply_relay_peer(peer: dict):
    """Program an inter-gateway peer: same wg0 interface, no extra port."""
    run([
        "wg", "set", IFACE, "peer", peer["public_key"],
        "endpoint", peer["endpoint"],
        "persistent-keepalive", "25",
        "allowed-ips", ",".join(peer["allowed_ips"]),
    ])


def remove_peer(public_key: str):
    run(["wg", "set", IFACE, "peer", public_key, "remove"])


_relay_routes: set[str] = set()


def sync_relay_routes(relay_peers: list[dict]):
    """
    Kernel routes matching the relay peers' AllowedIPs: forward networks and
    upstream client subnets (return path) are reached through the tunnel.
    """
    global _relay_routes
    desired = {cidr for p in relay_peers for cidr in p["allowed_ips"]}
    for cidr in desired - _relay_routes:
        run(["ip", "route", "replace", cidr, "dev", IFACE])
    for cidr in _relay_routes - desired:
        subprocess.run(["ip", "route", "del", cidr, "dev", IFACE], capture_output=True)
    _relay_routes = desired


def reconcile(state: dict):
    desired = set()
    for peer in state["peers"]:
        try:
            apply_peer(peer)
            desired.add(peer["public_key"])
        except subprocess.CalledProcessError as exc:
            # A single malformed peer must not take the whole gateway down.
            log(f"skipping invalid peer {peer['public_key'][:16]}…: {exc}")

    # Relay peers whose agent has not yet self-reported a key are retried on
    # the next poll (both sides converge within a couple of cycles).
    relay_peers = [p for p in state.get("relay_peers", []) if p.get("public_key")]
    for peer in relay_peers:
        try:
            apply_relay_peer(peer)
            desired.add(peer["public_key"])
        except subprocess.CalledProcessError as exc:
            log(f"skipping relay peer {peer['name']}: {exc}")

    for stale in current_peers() - desired:
        log(f"removing stale peer {stale[:16]}…")
        remove_peer(stale)

    sync_relay_routes(relay_peers)
    rebuild_egress_firewall(state.get("forward_rules", []))
    ensure_masquerade(state.get("masq_subnets", [state["tunnel_subnet"]]))


# --- Main loop -------------------------------------------------------------

def sync(public_key: str) -> dict:
    resp = requests.post(
        f"{CONTROL_PLANE}/api/gateways/sync/",
        headers={"Authorization": f"Bearer {SYNC_TOKEN}"},
        json={"public_key": public_key},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    private_key, public_key = load_or_create_keypair()
    log(f"public key: {public_key}")

    configured = False
    while True:
        try:
            state = sync(public_key)
        except requests.RequestException as exc:
            log(f"sync failed: {exc}")
            time.sleep(POLL_INTERVAL)
            continue

        if not configured:
            prefixlen = int(state["tunnel_subnet"].split("/")[1])
            ensure_interface(
                private_key, public_key, state["address"], prefixlen, state["listen_port"]
            )
            ensure_forwarding()
            configured = True

        reconcile(state)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
