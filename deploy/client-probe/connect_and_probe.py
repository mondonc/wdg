"""
Client probe: full client flow against the live stack + a real WireGuard tunnel,
used to validate M3 (reachability), M4 (group-scoped egress, revocation) and
M9 (relayed networks: the tunnel conf comes from the multi-tunnel plan API, so
AllowedIPs include what is reachable through relay chains).

Env:
  USERNAME   CAS user to log in as (default alice)
  GATEWAY    optional service/instance name to select the tunnel — defaults to
             the plan's first tunnel
  REACH      comma-separated URLs that MUST be reachable through the tunnel
  DENY       comma-separated URLs that MUST NOT be reachable
  MODE       "probe" (default: test then exit) or "hold" (test then stay up)
"""

import os
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import requests

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
USERNAME = os.environ.get("USERNAME", "alice")
GATEWAY = os.environ.get("GATEWAY", "")
REACH = [u for u in os.environ.get("REACH", "").split(",") if u]
DENY = [u for u in os.environ.get("DENY", "").split(",") if u]
MODE = os.environ.get("MODE", "probe")
LOOPBACK = "http://localhost:51820/callback"
IFACE = "wg0"


def fail(msg: str):
    print(f"probe: FAIL — {msg}")
    sys.exit(1)


def login_as(username: str) -> str:
    session = requests.Session()
    url = f"{CONTROL_PLANE}/auth/cas/login?redirect={LOOPBACK}"
    for _ in range(10):
        resp = session.get(url, allow_redirects=False, timeout=15)
        location = resp.headers["Location"]
        if "/cas/login" in location and "username=" not in location:
            location += ("&" if "?" in location else "?") + f"username={username}"
        if location.startswith(LOOPBACK):
            code = parse_qs(urlsplit(location).query)["wdg_code"][0]
            resp = requests.post(
                f"{CONTROL_PLANE}/auth/cas/exchange", json={"code": code}, timeout=15
            )
            resp.raise_for_status()
            return resp.json()["wdg_token"]
        url = location
    fail("did not obtain a token")


def wg_keypair() -> tuple[str, str]:
    priv = subprocess.run(["wg", "genkey"], check=True, text=True, capture_output=True).stdout.strip()
    pub = subprocess.run(["wg", "pubkey"], input=priv, check=True, text=True, capture_output=True).stdout.strip()
    return priv, pub


def reachable(url: str, tries: int = 1) -> bool:
    for _ in range(tries):
        r = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "3", url],
            text=True, capture_output=True,
        )
        if r.stdout.strip() == "200":
            return True
        time.sleep(1)
    return False


def build_conf(private_key: str, tunnel: dict) -> str:
    instance = tunnel["instances"][0]
    return (
        "[Interface]\n"
        f"PrivateKey = {private_key}\n"
        f"Address = {instance['address']}/32\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {instance['public_key']}\n"
        f"PresharedKey = {instance['preshared_key']}\n"
        f"Endpoint = {instance['endpoint']}\n"
        f"AllowedIPs = {', '.join(tunnel['allowed_ips'])}\n"
        "PersistentKeepalive = 25\n"
    )


def pick_tunnel(plan: dict) -> dict:
    tunnels = plan["tunnels"]
    if not GATEWAY:
        return tunnels[0]
    for tunnel in tunnels:
        if tunnel["service"] == GATEWAY or any(
            i["gateway"] == GATEWAY for i in tunnel["instances"]
        ):
            return tunnel
    fail(f"no tunnel matching {GATEWAY} in plan: {[t['service'] for t in tunnels]}")


def main():
    token = login_as(USERNAME)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    private_key, public_key = wg_keypair()
    reg = session.post(f"{CONTROL_PLANE}/api/peers/register/", json={"public_key": public_key}, timeout=15)
    if reg.status_code != 200:
        fail(f"register returned {reg.status_code}: {reg.text}")
    print(f"  · {USERNAME} registered: {reg.json()}")

    plan = session.get(f"{CONTROL_PLANE}/api/plan/", timeout=15).json()
    tunnel = pick_tunnel(plan)
    conf = build_conf(private_key, tunnel)
    os.makedirs("/etc/wireguard", exist_ok=True)
    with open(f"/etc/wireguard/{IFACE}.conf", "w") as fh:
        fh.write(conf)

    subprocess.run(["wg-quick", "up", IFACE], check=True)
    print(f"  · tunnel up via {tunnel['service']} (AllowedIPs: {', '.join(tunnel['allowed_ips'])})")

    for url in REACH:
        if reachable(url, tries=15):
            print(f"  ✓ REACH ok: {url}")
        else:
            fail(f"expected reachable but was not: {url}")

    for url in DENY:
        if reachable(url, tries=2):
            fail(f"expected blocked but was reachable: {url}")
        print(f"  ✓ DENY ok (blocked): {url}")

    print(f"probe: PASS ({USERNAME})")

    if MODE == "hold":
        print("  · holding tunnel up…", flush=True)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
