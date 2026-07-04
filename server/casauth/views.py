"""
CAS login endpoints for the CLI client, plus a token-authenticated whoami.

Flow (see docs/DEPLOYMENT.md):
    client browser -> /auth/cas/login?redirect=<loopback>
                   -> CAS login -> /auth/cas/callback?ticket=...
                   -> validate, upsert user+groups, issue one-time code
                   -> redirect to <loopback>?wdg_code=...
    client CLI     -> POST /auth/cas/exchange {"code": ...} -> WDG token

The browser only ever carries the single-use, short-lived code — the bearer
token itself never appears in a URL (history, proxies, access logs).
"""

import datetime
import json
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core import sync

from . import cas, tokens
from .bearer import require_bearer
from .models import AuthCode


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


def _code_cutoff():
    return timezone.now() - datetime.timedelta(seconds=settings.WDG_AUTH_CODE_MAX_AGE)


def cas_callback(request):
    """CAS returns here with a ticket; validate it and hand the client a code."""
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

    # Opportunistic cleanup of codes that were never exchanged.
    AuthCode.objects.filter(created_at__lt=_code_cutoff()).delete()

    code = AuthCode.issue(user)
    return redirect(client_redirect + "?" + urlencode({"wdg_code": code}))


@csrf_exempt
@require_http_methods(["POST"])
def cas_exchange(request):
    """Exchange a one-time code (from the loopback redirect) for a WDG token."""
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"detail": "invalid JSON"}, status=400)

    code = (body.get("code") or "").strip()
    if not code:
        return JsonResponse({"detail": "code required"}, status=400)

    # Delete-on-read inside a transaction makes the code single-use even under
    # concurrent exchange attempts.
    with transaction.atomic():
        row = AuthCode.objects.select_for_update().filter(code=code).first()
        if row is not None:
            row.delete()

    if row is None or row.created_at < _code_cutoff() or not row.user.is_active:
        return JsonResponse({"detail": "invalid or expired code"}, status=401)

    return JsonResponse({"wdg_token": tokens.mint(row.user)})


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
