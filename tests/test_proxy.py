"""Tests for the loopback reverse proxy's request handling.

The interesting logic is pure (target sanitising, Destination rewriting,
non-ascii encoding), so these run without a server, a device or credentials.
"""

from __future__ import annotations

import unittest

from minas_webdav import proxy


class TestSanitizeTarget(unittest.TestCase):
    def test_origin_form_is_kept(self):
        for target in ("/", "/pool0/data", "/a%20b/c.txt?x=1"):
            self.assertEqual(proxy.sanitize_target(target), target)

    def test_absolute_form_is_rejected(self):
        with self.assertRaises(ValueError):
            proxy.sanitize_target("http://evil.example/pool0/data")
        with self.assertRaises(ValueError):
            proxy.sanitize_target("https://evil.example/")

    def test_network_path_reference_is_rejected(self):
        with self.assertRaises(ValueError):
            proxy.sanitize_target("//evil.example/pool0/data")

    def test_control_characters_are_rejected(self):
        for bad in ("/a\r\nX-Injected: 1", "/a\x00b", "/a b", "/a\tb", ""):
            with self.subTest(target=bad):
                with self.assertRaises(ValueError):
                    proxy.sanitize_target(bad)


class TestRewriteDestination(unittest.TestCase):
    def test_absolute_url_becomes_path(self):
        self.assertEqual(
            proxy.rewrite_destination("http://127.0.0.1:8899/pool0/data/a.txt"),
            "/pool0/data/a.txt",
        )

    def test_already_path_is_kept(self):
        self.assertEqual(proxy.rewrite_destination("/pool0/data/b.txt"), "/pool0/data/b.txt")

    def test_network_path_loses_the_reference(self):
        self.assertEqual(proxy.rewrite_destination("//nas/pool0/data/c.txt"), "/nas/pool0/data/c.txt")

    def test_non_ascii_is_percent_encoded(self):
        self.assertEqual(
            proxy.rewrite_destination("http://127.0.0.1:8899/pool0/data/我的照片/a.jpg"),
            "/pool0/data/%E6%88%91%E7%9A%84%E7%85%A7%E7%89%87/a.jpg",
        )

    def test_relative_value_gets_a_leading_slash(self):
        self.assertEqual(proxy.rewrite_destination("pool0/data/d.txt"), "/pool0/data/d.txt")


class TestAsciiPath(unittest.TestCase):
    def test_ascii_passthrough(self):
        self.assertEqual(proxy.ascii_path("/a/b%20c"), "/a/b%20c")

    def test_non_ascii_encoded_per_segment(self):
        self.assertEqual(
            proxy.ascii_path("/pool0/data/agent操作区/x.txt"),
            "/pool0/data/agent%E6%93%8D%E4%BD%9C%E5%8C%BA/x.txt",
        )


if __name__ == "__main__":
    unittest.main()
