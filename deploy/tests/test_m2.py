"""
M2 end-to-end: log in, register a peer, fetch the WireGuard config over HTTP,
and assert the generated conf matches the user's group-granted access.
"""

import base64
import os
import sys
from urllib.parse import parse_qs, urlsplit

import requests

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
LOOPBACK = "http://localhost:51820/callback"


def fake_wg_key() -> str:
    """A syntactically valid WireGuard public key (32 random bytes, base64)."""
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
    # alice: admin; provisioned on both gateways. Primary (wdgw-a) conf carries
    # only what wdgw-a routes and she is granted: net-common + net-lab-a.
    s = api(login_as("alice"))
    reg = s.post(f"{CONTROL_PLANE}/api/peers/register/", json={"public_key": fake_wg_key()}, timeout=15)
    assert reg.status_code == 200, (reg.status_code, reg.text)
    assert sorted(d["gateway"] for d in reg.json()["devices"]) == ["wdgw-a", "wdgw-a2", "wdgw-b"], reg.json()
    conf = s.get(f"{CONTROL_PLANE}/api/config/", timeout=15).text
    assert "PrivateKey = __PRIVATE_KEY__" in conf
    assert "Endpoint = wdgw-a:51820" in conf
    assert "10.0.0.0/24" in conf and "192.168.20.0/24" in conf, conf
    assert "192.168.30.0/24" not in conf, "net-lab-b is behind wdgw-b, not wdgw-a"
    print("  ✓ alice: provisioned on wdgw-a+wdgw-b; wdgw-a conf scoped to its networks")

    # bob: via wdgw-a only net-common; net-lab-b appears only via wdgw-b.
    s = api(login_as("bob"))
    s.post(f"{CONTROL_PLANE}/api/peers/register/", json={"public_key": fake_wg_key()}, timeout=15).raise_for_status()
    conf_a = s.get(f"{CONTROL_PLANE}/api/config/", timeout=15).text
    assert "10.0.0.0/24" in conf_a and "192.168.30.0/24" not in conf_a, conf_a
    conf_b = s.get(f"{CONTROL_PLANE}/api/config/?gateway=wdgw-b", timeout=15).text
    assert "Endpoint = wdgw-b:51820" in conf_b and "192.168.30.0/24" in conf_b, conf_b
    print("  ✓ bob: wdgw-a conf = net-common; wdgw-b conf adds net-lab-b")

    # carol: no groups -> no access
    s = api(login_as("carol"))
    reg = s.post(f"{CONTROL_PLANE}/api/peers/register/", json={"public_key": fake_wg_key()}, timeout=15)
    assert reg.status_code == 403, reg.status_code
    print("  ✓ carol: no access -> 403 on register")

    # config before register -> 409
    s = api(login_as("carol"))  # carol still has no gateway anyway -> 403 on config
    cfg = s.get(f"{CONTROL_PLANE}/api/config/", timeout=15)
    assert cfg.status_code == 403, cfg.status_code
    print("  ✓ carol: 403 on config")

    print("M2 e2e: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"M2 e2e: FAIL — {exc}")
        sys.exit(1)
