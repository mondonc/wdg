"""
M0 end-to-end integration test (runs inside the compose network).

Walks the full CASv3 login the way the CLI client's browser would:
    /auth/cas/login -> mock CAS -> /auth/cas/callback -> loopback?wdg_token=...
then checks the minted token against /api/whoami/ and asserts the CAS groups
were mirrored onto the user.

Exit code 0 on success, 1 on failure.
"""

import os
import sys
from urllib.parse import parse_qs, urlsplit

import requests

CONTROL_PLANE = os.environ["CONTROL_PLANE"].rstrip("/")
LOOPBACK = "http://localhost:51820/callback"

EXPECTED = {
    "alice": ["research-lab-a", "vpn-admins", "vpn-users"],
    "bob": ["research-lab-b", "vpn-users"],
    "carol": [],
}


def login_as(username: str) -> str:
    """Drive the browser redirect chain, return the WDG token from the loopback."""
    session = requests.Session()
    url = f"{CONTROL_PLANE}/auth/cas/login?redirect={LOOPBACK}"

    for _ in range(10):
        resp = session.get(url, allow_redirects=False, timeout=15)
        if resp.status_code not in (301, 302, 303, 307, 308):
            raise AssertionError(f"expected redirect at {url}, got {resp.status_code}: {resp.text[:200]}")
        location = resp.headers["Location"]

        # The mock CAS login page needs a username; inject it like a human would.
        if "/cas/login" in location and "username=" not in location:
            location += ("&" if "?" in location else "?") + f"username={username}"

        if location.startswith(LOOPBACK):
            token = parse_qs(urlsplit(location).query).get("wdg_token", [None])[0]
            if not token:
                raise AssertionError(f"no wdg_token in loopback redirect: {location}")
            return token

        url = location

    raise AssertionError("redirect loop did not reach the loopback")


def check_whoami(token: str) -> dict:
    resp = requests.get(
        f"{CONTROL_PLANE}/api/whoami/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    for username, expected_groups in EXPECTED.items():
        token = login_as(username)
        who = check_whoami(token)
        assert who["username"] == username, who
        assert who["groups"] == expected_groups, f"{username}: {who['groups']} != {expected_groups}"
        print(f"  ✓ {username}: token OK, groups={who['groups']}")

    # A garbage token must be rejected.
    bad = requests.get(
        f"{CONTROL_PLANE}/api/whoami/",
        headers={"Authorization": "Bearer not-a-real-token"},
        timeout=15,
    )
    assert bad.status_code == 401, bad.status_code
    print("  ✓ invalid token rejected (401)")

    print("M0 e2e: PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"M0 e2e: FAIL — {exc}")
        sys.exit(1)
