"""
Minimal Apereo CAS v3 client.

The control plane acts as a CAS *service*: it sends the browser to the CAS
login page, then validates the returned service ticket server-to-server via
``/p3/serviceValidate`` and reads the released attributes (identity + groups).

Only the pieces WDG needs are implemented; there is deliberately no dependency
on a heavyweight CAS library.
"""

from urllib.parse import urlencode

import requests
from django.conf import settings


class CasError(Exception):
    """Raised when CAS login or ticket validation fails."""


def login_url(service: str) -> str:
    """URL of the CAS login page for the given service (callback) URL."""
    return f"{settings.CAS_BASE_URL}/cas/login?" + urlencode({"service": service})


def validate_ticket(service: str, ticket: str) -> dict:
    """
    Validate a service ticket against ``/p3/serviceValidate``.

    Returns a dict ``{"user": str, "attributes": dict}`` on success.
    Raises :class:`CasError` on any failure.
    """
    url = f"{settings.CAS_BASE_URL}/cas/p3/serviceValidate"
    params = {"service": service, "ticket": ticket, "format": "json"}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise CasError(f"CAS validation request failed: {exc}") from exc

    service_response = payload.get("serviceResponse", {})
    success = service_response.get("authenticationSuccess")
    if not success:
        failure = service_response.get("authenticationFailure", {})
        code = failure.get("code", "UNKNOWN")
        raise CasError(f"CAS authentication failure: {code}")

    return {
        "user": success["user"],
        "attributes": success.get("attributes", {}) or {},
    }


def extract_groups(attributes: dict) -> list[str]:
    """
    Collect group names from the configured CAS attributes.

    CAS releases multi-valued attributes as a list, but a single value may be
    delivered as a bare string; both are normalised here.
    """
    groups: list[str] = []
    for attr in settings.CAS_GROUP_ATTRIBUTES:
        value = attributes.get(attr)
        if value is None:
            continue
        if isinstance(value, str):
            groups.append(value)
        else:
            groups.extend(str(v) for v in value)
    # De-duplicate while preserving order.
    return list(dict.fromkeys(groups))
