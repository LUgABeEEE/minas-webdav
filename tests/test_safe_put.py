"""Offline tests for ``cli.safe_put()`` — the workaround for MINAS' non-truncating PUT.

The device does **not** truncate when a PUT overwrites an existing resource: the
new bytes land at offset 0, the old tail survives, the reported size stays the
old one and the PUT still answers 204. ``safe_put()`` therefore never PUTs onto
an existing name (temp name + MOVE) and verifies the result by reading it back.

These tests pin that contract down without touching the network.
"""
from __future__ import annotations

import unittest

from minas_webdav import cli


class FakeClient:
    """Only the surface ``safe_put()`` actually uses."""

    def __init__(self, *, existed=False, old_size=0, final_size=None,
                 move_status=201, put_status=201, back_bytes=None):
        self.existed = existed
        self.old_size = old_size
        self.final_size = final_size
        self.move_status = move_status
        self.put_status = put_status
        self.back_bytes = back_bytes
        self.calls: list[tuple[str, str]] = []
        self._moved = False
        self._deleted: set[str] = set()

    # -- used by safe_put ---------------------------------------------------
    def request(self, method, path, body=None, headers=None, with_mtls=False):
        self.calls.append((method, path))
        if method == "PUT":
            if path in self._deleted:
                # DELETE + PUT (fresh create) also yields a clean target
                self._moved = True
            return self.put_status, {}, b""
        if method == "MOVE":
            if self.move_status in (200, 201, 204):
                self._moved = True
            return self.move_status, {}, b""
        if method == "DELETE":
            self._deleted.add(path)
            return 204, {}, b""
        if method == "GET":
            return 200, {}, self.back_bytes or b""
        return 499, {}, b""

    def propfind(self, path, depth="0", with_mtls=True):
        if self._moved:
            size = self.final_size
            return [] if size is None else [{"size": size}]
        return [{"size": self.old_size}] if self.existed else []

    # -- helpers for assertions --------------------------------------------
    def methods(self):
        return [c[0] for c in self.calls]

    def paths_for(self, method):
        return [p for m, p in self.calls if m == method]


class TestSafePut(unittest.TestCase):
    def setUp(self):
        self.data = b"hello minas"
        self.remote = "/pool0/data/work/a.txt"
        self.tmp = self.remote + cli.PUT_TMP_SUFFIX

    def test_never_puts_onto_an_existing_name(self):
        client = FakeClient(existed=True, old_size=4096, final_size=len(self.data),
                            back_bytes=self.data)
        res = cli.safe_put(client, self.remote, self.data)
        self.assertTrue(res["ok"], res)
        # the payload only ever lands on the temp name
        self.assertEqual(client.paths_for("PUT"), [self.tmp])
        self.assertIn("MOVE", client.methods())
        self.assertEqual(res["verified"], "size+sha256")

    def test_leftover_tmp_is_cleared_first(self):
        client = FakeClient(final_size=len(self.data), back_bytes=self.data)
        cli.safe_put(client, self.remote, self.data)
        self.assertEqual(client.calls[0], ("DELETE", self.tmp))

    def test_size_mismatch_is_a_failure(self):
        # exactly the shape of the truncation bug: 204 + old (larger) size
        client = FakeClient(existed=True, old_size=4096, final_size=4096,
                            back_bytes=self.data)
        res = cli.safe_put(client, self.remote, self.data)
        self.assertFalse(res["ok"])
        self.assertIn("回读长度", res["error"])

    def test_sha_mismatch_is_a_failure(self):
        client = FakeClient(final_size=len(self.data), back_bytes=b"tampered!!!")
        res = cli.safe_put(client, self.remote, self.data)
        self.assertFalse(res["ok"])
        self.assertIn("sha256", res["error"])

    def test_put_failure_is_reported(self):
        client = FakeClient(put_status=500)
        res = cli.safe_put(client, self.remote, self.data)
        self.assertFalse(res["ok"])
        self.assertIn("HTTP 500", res["error"])

    def test_move_failure_falls_back_to_delete_then_put(self):
        client = FakeClient(existed=True, old_size=4096, final_size=len(self.data),
                            back_bytes=self.data, move_status=502)
        res = cli.safe_put(client, self.remote, self.data)
        self.assertTrue(res["ok"], res)
        # DELETE the stale target, then a fresh PUT (new file ⇒ no old tail)
        self.assertIn(("DELETE", self.remote), client.calls)
        self.assertIn(self.remote, client.paths_for("PUT"))

    def test_verify_size_skips_the_download(self):
        client = FakeClient(final_size=len(self.data), back_bytes=self.data)
        res = cli.safe_put(client, self.remote, self.data, verify="size")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["verified"], "size")
        self.assertNotIn("GET", client.methods())


if __name__ == "__main__":
    unittest.main()
