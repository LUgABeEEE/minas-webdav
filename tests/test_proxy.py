# SPDX-License-Identifier: Apache-2.0
"""Tests for the loopback reverse proxy's request handling.

The interesting logic is pure (target sanitising, Destination rewriting,
non-ascii encoding, body framing), so these run without a server, a device or
credentials.
"""

from __future__ import annotations

import io
import unittest

from minas_webdav import proxy


class TestRequestFraming(unittest.TestCase):
    """A PUT must never be truncated silently — that loses data on the device."""

    def test_content_length_is_honoured(self):
        body = b"x" * 10
        slices, length = proxy.request_body({"Content-Length": "10"}, io.BytesIO(body))
        self.assertEqual(length, 10)
        self.assertEqual(b"".join(slices), body)

    def test_large_body_is_sliced(self):
        body = b"y" * (proxy.CHUNK_SIZE * 2 + 5)
        slices, length = proxy.request_body({"Content-Length": str(len(body))}, io.BytesIO(body))
        pieces = list(slices)
        self.assertEqual(length, len(body))
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= proxy.CHUNK_SIZE for p in pieces))
        self.assertEqual(b"".join(pieces), body)

    def test_chunked_body_is_decoded(self):
        stream = io.BytesIO(b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n")
        slices, length = proxy.request_body({"Transfer-Encoding": "chunked"}, stream)
        self.assertIsNone(length)
        self.assertEqual(b"".join(slices), b"hello world")

    def test_chunked_with_extension_and_trailers(self):
        stream = io.BytesIO(b"4;foo=bar\r\ndata\r\n0\r\nX-Trailer: 1\r\n\r\n")
        slices, _ = proxy.request_body({"Transfer-Encoding": "chunked"}, stream)
        self.assertEqual(b"".join(slices), b"data")

    def test_chunked_bad_size_is_rejected(self):
        stream = io.BytesIO(b"zz\r\ndata\r\n0\r\n\r\n")
        slices, _ = proxy.request_body({"Transfer-Encoding": "chunked"}, stream)
        with self.assertRaises(proxy.ChunkedError):
            list(slices)

    def test_chunked_truncated_payload_is_rejected(self):
        stream = io.BytesIO(b"9\r\nshort\r\n")
        slices, _ = proxy.request_body({"Transfer-Encoding": "chunked"}, stream)
        with self.assertRaises(proxy.ChunkedError):
            list(slices)

    def test_short_content_length_body_is_rejected(self):
        slices, _ = proxy.request_body({"Content-Length": "20"}, io.BytesIO(b"only10byte"))
        with self.assertRaises(proxy.ChunkedError):
            list(slices)

    def test_no_body(self):
        self.assertEqual(proxy.request_body({}, io.BytesIO(b"")), (None, None))
        self.assertEqual(proxy.request_body({"Content-Length": "0"}, io.BytesIO(b"")), (None, 0))

    def test_bad_content_length_is_rejected(self):
        for bad in ("abc", "-1", "1.5"):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                proxy.request_body({"Content-Length": bad}, io.BytesIO(b""))

    def test_chunk_frame_round_trip(self):
        stream = io.BytesIO(proxy.chunk_frame(b"hello") + proxy.LAST_CHUNK)
        self.assertEqual(b"".join(proxy.iter_chunked(stream.readline, stream.read)), b"hello")


class TestMapToRoot(unittest.TestCase):
    """A mounted drive must show the storage pool, not the device's bare "/" (451)."""

    ROOT = "/pool0/data"

    def test_bare_root_becomes_the_data_root(self):
        self.assertEqual(proxy.map_to_root("/", self.ROOT), "/pool0/data/")
        self.assertEqual(proxy.map_to_root("", self.ROOT), "/pool0/data/")

    def test_relative_paths_are_prefixed(self):
        self.assertEqual(proxy.map_to_root("/我的照片", self.ROOT), "/pool0/data/我的照片")
        self.assertEqual(proxy.map_to_root("/a/b?x=1", self.ROOT), "/pool0/data/a/b?x=1")

    def test_already_prefixed_paths_are_untouched(self):
        for path in ("/pool0/data", "/pool0/data/x", "/pool0/data/x?depth=1"):
            with self.subTest(path=path):
                self.assertEqual(proxy.map_to_root(path, self.ROOT), path)

    def test_empty_root_is_a_no_op(self):
        self.assertEqual(proxy.map_to_root("/x", ""), "/x")


class TestProppatchEcho(unittest.TestCase):
    """The device answers 405; WebClient needs a 207 echo or it deletes the file."""

    def test_echoes_the_requested_properties(self):
        body = (
            b'<?xml version="1.0" encoding="utf-8"?>'
            b'<D:propertyupdate xmlns:D="DAV:"><D:set><D:prop>'
            b'<Win32LastModifiedTime xmlns="urn:schemas-microsoft-com:"/>'
            b"</D:prop></D:set></D:propertyupdate>"
        )
        out = proxy.proppatch_response("/a/b.txt", body)
        self.assertIn(b"<Win32LastModifiedTime", out)
        self.assertIn(b"HTTP/1.1 200 OK", out)
        self.assertIn(b"<D:href>/a/b.txt</D:href>", out)

    def test_empty_body_still_answers_multistatus(self):
        out = proxy.proppatch_response("/x", b"")
        self.assertIn(b"<D:multistatus", out)
        self.assertIn(b"200 OK", out)


class TestDestinationMapping(unittest.TestCase):
    def test_root_relative_destination_gets_the_data_root(self):
        dest = proxy.rewrite_destination("http://127.0.0.1:8899/_mounttest/x.bin")
        self.assertEqual(proxy.map_to_root(dest, "/pool0/data"), "/pool0/data/_mounttest/x.bin")

    def test_absolute_device_path_is_left_alone(self):
        dest = proxy.rewrite_destination("http://127.0.0.1:8899/pool0/data/x.bin")
        self.assertEqual(proxy.map_to_root(dest, "/pool0/data"), "/pool0/data/x.bin")


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
