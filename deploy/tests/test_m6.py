"""
M6 end-to-end: CAS attributes drive WDG group membership.

'dave' is released a memberOf as a full LDAP DN (mapped to the vpn-admins group
via cas_names) and an eduPersonAffiliation of staff+member. After login his WDG
groups must reflect all of that: the DN mapping, the affiliation mapping, and an
auto-created group for the otherwise-unknown 'member' value.
"""

import os
import sys
from urllib.parse import parse_qs, urlsplit

import requests

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
LOOPBACK = "http://localhost:51820/callback"


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


def whoami(token):
    r = requests.get(
        f"{CONTROL_PLANE}/api/whoami/", headers={"Authorization": f"Bearer {token}"}, timeout=15
    )
    r.raise_for_status()
    return r.json()


def main() -> int:
    who = whoami(login_as("dave"))
    groups = who["groups"]
    # DN memberOf -> vpn-admins ; affiliation staff -> staff-network ; member -> auto
    assert "vpn-admins" in groups, f"DN did not map to vpn-admins: {groups}"
    assert "staff-network" in groups, f"affiliation did not map: {groups}"
    assert "member" in groups, f"unknown affiliation not auto-created: {groups}"
    print(f"  ✓ dave: CAS attributes mapped to groups {sorted(groups)}")
    print("M6 e2e: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"M6 e2e: FAIL — {exc}")
        sys.exit(1)
