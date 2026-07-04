"""Bearer-token authentication for WDG API endpoints."""

from functools import wraps

from django.http import JsonResponse

from . import tokens


def bearer_user(request):
    """Return the user behind a valid WDG bearer token, or ``None``."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return tokens.verify(header[len("Bearer ") :])


def require_bearer(view):
    """View decorator: 401 unless a valid token is present; sets request.wdg_user."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        user = bearer_user(request)
        if user is None:
            return JsonResponse({"detail": "unauthenticated"}, status=401)
        request.wdg_user = user
        return view(request, *args, **kwargs)

    return wrapped
