"""
M8 end-to-end: multi-tunnel plan API + CAS site mapping.

alice (CAS ou=centre-a) must land on centre-a, and her plan must contain the
wdg-a and wdg-b tunnels with disjoint AllowedIPs and per-instance credentials.
"""

import base64
import os
import sys
from urllib.parse import parse_qs, urlsplit

import requests

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
LOOPBACK = "http://localhost:51820/callback"


def fake_wg_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


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
    raise AssertionError("no token")


def api(token):
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {token}"
    return s


def main() -> int:
    s = api(login_as("alice"))

    who = s.get(f"{CONTROL_PLANE}/api/whoami/", timeout=15).json()
    assert who["site"] == "centre-a", f"CAS ou=centre-a should map to centre-a: {who}"
    print(f"  ✓ alice: CAS site attribute mapped to {who['site']}")

    s.post(
        f"{CONTROL_PLANE}/api/peers/register/",
        json={"public_key": fake_wg_key()},
        timeout=15,
    ).raise_for_status()

    plan = s.get(f"{CONTROL_PLANE}/api/plan/", timeout=15).json()
    assert plan["site"] == "centre-a", plan
    by_service = {t["service"]: t for t in plan["tunnels"]}
    assert set(by_service) == {"wdg-a", "wdg-b"}, plan

    # Disjoint partition: the shared net-common is claimed by wdg-a only, and
    # the relayed net-dc rides the wdg-a tunnel (wdgw-a → relay-dc chain).
    a_ips = set(by_service["wdg-a"]["allowed_ips"])
    b_ips = set(by_service["wdg-b"]["allowed_ips"])
    assert a_ips == {"10.0.0.0/24", "192.168.20.0/24", "192.168.40.0/24"}, a_ips
    assert b_ips == {"192.168.30.0/24"}, b_ips
    assert not (a_ips & b_ips)
    print("  ✓ alice: plan tunnels wdg-a/wdg-b with disjoint AllowedIPs")

    for tunnel in plan["tunnels"]:
        for inst in tunnel["instances"]:
            assert inst["address"] and inst["preshared_key"] and inst["endpoint"], inst
    print("  ✓ alice: per-instance credentials present after registration")

    # bob is at centre-b.
    s = api(login_as("bob"))
    who = s.get(f"{CONTROL_PLANE}/api/whoami/", timeout=15).json()
    assert who["site"] == "centre-b", who
    print(f"  ✓ bob: CAS site attribute mapped to {who['site']}")

    print("M8 e2e: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"M8 e2e: FAIL — {exc}")
        sys.exit(1)
