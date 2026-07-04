"""
One-time authorization codes for the CAS callback → CLI hand-off.

The browser only ever sees a short-lived, single-use code on the loopback
redirect; the CLI exchanges it for the real session token with a POST to
``/auth/cas/exchange``. This keeps the bearer token out of browser history
and access logs.
"""

import secrets

from django.contrib.auth.models import User
from django.db import models


class AuthCode(models.Model):
    code = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="wdg_auth_codes")
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def issue(cls, user: User) -> str:
        code = secrets.token_urlsafe(32)
        cls.objects.create(code=code, user=user)
        return code

    def __str__(self) -> str:
        return f"auth-code for {self.user.username}"
