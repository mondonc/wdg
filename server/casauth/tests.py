from django.test import TestCase, override_settings

from . import cas


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
