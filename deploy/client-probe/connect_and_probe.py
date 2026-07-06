"""
Client probe: full client flow against the live stack + real WireGuard
tunnels, used to validate M3 (reachability), M4 (group-scoped egress,
revocation), M9 (relayed networks) and M10/M11 (multi-tunnel + failover).

It drives the *real* client code: the plan from ``/api/plan/`` is brought up
by ``wg_client.plan.connect_plan`` — every tunnel at once, failing over
between a service's instances when one does not handshake.

Env:
  USERNAME   CAS user to log in as (default alice)
  GATEWAY    optional service/instance name: bring up only that tunnel
  REACH      comma-separated URLs that MUST be reachable through the tunnels
  DENY       comma-separated URLs that MUST NOT be reachable
  EXPECT_VIA optional "service=gateway" assertions on the connected instance,
             comma-separated (e.g. "wdg-a=wdgw-a2" after a failover)
  MODE       "probe" (default: test then exit) or "hold" (test then stay up)
"""

import os
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit

import requests

from wg_client import plan as wgplan

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
USERNAME = os.environ.get("USERNAME", "alice")
GATEWAY = os.environ.get("GATEWAY", "")
REACH = [u for u in os.environ.get("REACH", "").split(",") if u]
DENY = [u for u in os.environ.get("DENY", "").split(",") if u]
EXPECT_VIA = dict(
    pair.split("=") for pair in os.environ.get("EXPECT_VIA", "").split(",") if pair
)
MODE = os.environ.get("MODE", "probe")
LOOPBACK = "http://localhost:51820/callback"


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


def main():
    token = login_as(USERNAME)
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {token}"

    private_key, public_key = wg_keypair()
    reg = session.post(f"{CONTROL_PLANE}/api/peers/register/", json={"public_key": public_key}, timeout=15)
    if reg.status_code != 200:
        fail(f"register returned {reg.status_code}: {reg.text}")
    print(f"  · {USERNAME} registered: {reg.json()}")

    tunnel_plan = session.get(f"{CONTROL_PLANE}/api/plan/", timeout=15).json()
    if GATEWAY:
        tunnel_plan["tunnels"] = [
            t for t in tunnel_plan["tunnels"]
            if t["service"] == GATEWAY or any(i["gateway"] == GATEWAY for i in t["instances"])
        ] or fail(f"no tunnel matching {GATEWAY}")

    try:
        states = wgplan.connect_plan(tunnel_plan, private_key)
    except wgplan.TunnelError as exc:
        fail(str(exc))
    for state in states:
        print(f"  · {state['iface']}: {state['service']} via {state['gateway']} "
              f"(AllowedIPs: {', '.join(state['allowed_ips'])})")

    for service, expected_gw in EXPECT_VIA.items():
        actual = next((s["gateway"] for s in states if s["service"] == service), None)
        if actual != expected_gw:
            fail(f"expected {service} via {expected_gw}, got {actual}")
        print(f"  ✓ EXPECT_VIA ok: {service} via {actual}")

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
        print("  · holding tunnels up…", flush=True)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
