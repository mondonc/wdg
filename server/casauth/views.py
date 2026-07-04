"""
CAS login endpoints for the CLI client, plus a token-authenticated whoami.

Flow (see docs/DEPLOYMENT.md):
    client browser -> /auth/cas/login?redirect=<loopback>
                   -> CAS login -> /auth/cas/callback?ticket=...
                   -> validate, upsert user+groups, mint WDG token
                   -> redirect to <loopback>?wdg_token=...
"""

from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect

from core import sync

from . import cas, tokens
from .bearer import require_bearer


def healthz(request):
    return JsonResponse({"status": "ok"})


def _is_allowed_redirect(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "http"
        and parts.hostname in settings.ALLOWED_CLIENT_REDIRECT_HOSTS
    )


def _service_url() -> str:
    return f"{settings.PUBLIC_BASE_URL}/auth/cas/callback"


def cas_login(request):
    """Entry point: remember the client's loopback redirect, bounce to CAS."""
    client_redirect = request.GET.get("redirect", "")
    if not _is_allowed_redirect(client_redirect):
        return HttpResponseBadRequest("invalid or missing loopback 'redirect'")

    request.session["client_redirect"] = client_redirect
    return redirect(cas.login_url(_service_url()))


def _sync_user(cas_user: str, attributes: dict) -> User:
    """Create/update the Django user and mirror CAS groups onto it."""
    user, _created = User.objects.get_or_create(username=cas_user)

    email = attributes.get("email") or attributes.get("mail")
    if isinstance(email, list):
        email = email[0] if email else ""
    if email and user.email != email:
        user.email = email
        user.save(update_fields=["email"])

    sync.sync_membership(user, cas.extract_groups(attributes))
    return user


def cas_callback(request):
    """CAS returns here with a ticket; validate it and hand the client a token."""
    ticket = request.GET.get("ticket")
    client_redirect = request.session.get("client_redirect")
    if not ticket or not client_redirect:
        return HttpResponseBadRequest("missing ticket or session")

    try:
        result = cas.validate_ticket(_service_url(), ticket)
    except cas.CasError as exc:
        return HttpResponseBadRequest(f"CAS validation failed: {exc}")

    user = _sync_user(result["user"], result["attributes"])
    request.session.pop("client_redirect", None)

    token = tokens.mint(user)
    return redirect(client_redirect + "?" + urlencode({"wdg_token": token}))


@require_bearer
def whoami(request):
    """Return the identity + groups behind a WDG bearer token."""
    user = request.wdg_user
    return JsonResponse(
        {
            "username": user.username,
            "email": user.email,
            "groups": sorted(g.name for g in user.wdg_groups.all()),
        }
    )
