import datetime

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from . import cas, tokens
from .models import AuthCode


class ExtractGroupsTests(TestCase):
    @override_settings(CAS_GROUP_ATTRIBUTES=["memberOf", "eduPersonAffiliation"])
    def test_unions_configured_attributes(self):
        attrs = {
            "memberOf": ["vpn-users", "vpn-admins"],
            "eduPersonAffiliation": ["staff", "member"],
            "email": "x@example.org",  # ignored (not a group attribute)
        }
        self.assertEqual(
            cas.extract_groups(attrs), ["vpn-users", "vpn-admins", "staff", "member"]
        )

    @override_settings(CAS_GROUP_ATTRIBUTES=["memberOf"])
    def test_single_string_value_is_normalised(self):
        # CAS may deliver a single-valued attribute as a bare string.
        self.assertEqual(cas.extract_groups({"memberOf": "vpn-users"}), ["vpn-users"])

    @override_settings(CAS_GROUP_ATTRIBUTES=["memberOf"])
    def test_deduplicates_preserving_order(self):
        self.assertEqual(
            cas.extract_groups({"memberOf": ["a", "b", "a"]}), ["a", "b"]
        )


class CodeExchangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="alice")

    def _exchange(self, code):
        return self.client.post(
            "/auth/cas/exchange", {"code": code}, content_type="application/json"
        )

    def test_code_exchanges_for_a_valid_token(self):
        code = AuthCode.issue(self.user)
        resp = self._exchange(code)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(tokens.verify(resp.json()["wdg_token"]), self.user)

    def test_code_is_single_use(self):
        code = AuthCode.issue(self.user)
        self.assertEqual(self._exchange(code).status_code, 200)
        self.assertEqual(self._exchange(code).status_code, 401)

    def test_expired_code_is_rejected(self):
        code = AuthCode.issue(self.user)
        AuthCode.objects.filter(code=code).update(
            created_at=timezone.now() - datetime.timedelta(seconds=120)
        )
        self.assertEqual(self._exchange(code).status_code, 401)

    def test_unknown_code_is_rejected(self):
        self.assertEqual(self._exchange("no-such-code").status_code, 401)

    def test_inactive_user_cannot_exchange(self):
        code = AuthCode.issue(self.user)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self._exchange(code).status_code, 401)
