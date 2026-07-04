"""
WDG session tokens.

After a successful CAS validation the control plane issues its own signed,
stateless token to the client. It is verified locally (HMAC over the Django
``SECRET_KEY``) — no per-request round-trip to CAS, and no server-side session
store. This is what the CLI client sends as ``Authorization: Bearer``.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing

_SALT = "wdg.session.token"


def mint(user: User) -> str:
    """Issue a signed token for the given user."""
    return signing.dumps({"uid": user.pk}, salt=_SALT)


def verify(token: str) -> User | None:
    """Return the user for a valid, unexpired token, else ``None``."""
    try:
        data = signing.loads(token, salt=_SALT, max_age=settings.WDG_TOKEN_MAX_AGE)
    except signing.BadSignature:
        return None
    try:
        return User.objects.get(pk=data["uid"], is_active=True)
    except (User.DoesNotExist, KeyError):
        return None
