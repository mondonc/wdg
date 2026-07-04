"""Unit tests for the client's post-quantum TLS checks (run: python3 -m unittest)."""

import unittest
from unittest import mock

from wg_client import pqtls


class ClientCapabilityTests(unittest.TestCase):
    def test_capable_on_modern_openssl(self):
        with mock.patch("ssl.OPENSSL_VERSION_INFO", (3, 5, 0, 0, 0)):
            self.assertTrue(pqtls.client_pq_capable())

    def test_incapable_on_old_openssl(self):
        with mock.patch("ssl.OPENSSL_VERSION_INFO", (3, 0, 0, 0, 0)):
            self.assertFalse(pqtls.client_pq_capable())

    def test_preflight_fail_closed(self):
        with mock.patch.object(pqtls, "client_pq_capable", return_value=False):
            with self.assertRaises(pqtls.PostQuantumUnavailable):
                pqtls.preflight(require_pq=True)
            pqtls.preflight(require_pq=False)  # warns, does not raise


class GroupVerificationTests(unittest.TestCase):
    def test_pq_group_confirmed(self):
        headers = {"X-PQ-Group": "X25519MLKEM768"}
        self.assertEqual(pqtls.verify_group(headers, require_pq=True), "X25519MLKEM768")

    def test_classic_group_fails_closed(self):
        headers = {"X-PQ-Group": "X25519"}
        with self.assertRaises(pqtls.PostQuantumUnavailable):
            pqtls.verify_group(headers, require_pq=True)
        # without require_pq it only warns and returns the group
        self.assertEqual(pqtls.verify_group(headers, require_pq=False), "X25519")

    def test_missing_header_fails_closed(self):
        with self.assertRaises(pqtls.PostQuantumUnavailable):
            pqtls.verify_group({}, require_pq=True)


if __name__ == "__main__":
    unittest.main()
