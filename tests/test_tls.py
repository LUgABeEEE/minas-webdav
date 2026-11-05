"""The device TLS contexts must keep a modern protocol floor.

Verification is intentionally off for this LAN appliance (the chain is trusted
explicitly and the identity is pinned by CN), but the *protocol* should never
fall back to TLS 1.0/1.1 — CodeQL `py/insecure-protocol` flagged exactly that
before the floor was pinned.
"""

from __future__ import annotations

import ssl
import unittest

from minas_webdav import config as mconf
from minas_webdav.client import client_ctx


class TestTlsFloor(unittest.TestCase):
    def test_unverified_ctx_requires_tls12(self):
        ctx = mconf.unverified_ctx()
        self.assertGreaterEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)
        self.assertFalse(ctx.check_hostname)

    def test_client_ctx_requires_tls12(self):
        # No cert trio in a clean checkout -> falls back to the unverified ctx.
        self.assertGreaterEqual(client_ctx().minimum_version, ssl.TLSVersion.TLSv1_2)


if __name__ == "__main__":
    unittest.main()
