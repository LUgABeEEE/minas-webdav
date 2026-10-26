# Copyright 2026 missfor100
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Offline unit tests for path helpers and XML parsing (no network)."""
from __future__ import annotations

import unittest

from minas_webdav import cli


class TestNormEncPath(unittest.TestCase):
    def test_norm_collapses_slashes(self):
        self.assertEqual(cli.norm("//pool0//data//a/"), "/pool0/data/a")

    def test_norm_backslashes(self):
        self.assertEqual(cli.norm("\\pool0\\data"), "/pool0/data")

    def test_enc_path_quotes_cjk(self):
        self.assertEqual(cli.enc_path("/pool0/data/照片"), "/pool0/data/%E7%85%A7%E7%89%87")

    def test_enc_path_keeps_slashes(self):
        self.assertEqual(cli.enc_path("/pool0/data/a.txt"), "/pool0/data/a.txt")


class TestEnsureDataPath(unittest.TestCase):
    def test_empty_is_data_root(self):
        self.assertEqual(cli.ensure_data_path(""), cli.DATA_ROOT)

    def test_bare_name_prefixed(self):
        self.assertTrue(cli.ensure_data_path("照片").endswith("/照片"))
        self.assertTrue(cli.ensure_data_path("/照片").endswith("/照片"))

    def test_full_data_root_path_ok(self):
        p = cli.ensure_data_path("/pool0/data/a/b.txt")
        self.assertEqual(p, "/pool0/data/a/b.txt")

    def test_dotdot_rejected(self):
        with self.assertRaises(ValueError):
            cli.ensure_data_path("/pool0/data/../etc")
        with self.assertRaises(ValueError):
            cli.ensure_data_path("/pool0/data/a/../../x")

    def test_sibling_prefix_rejected(self):
        with self.assertRaises(ValueError):
            cli.ensure_data_path("/pool0/other/secret")
        with self.assertRaises(ValueError):
            cli.ensure_data_path("/pool0/data2")

    def test_pool0evil_not_outside_via_prefix(self):
        # /pool0evil is not under /pool0/data; must not be accepted as-is
        p = cli.ensure_data_path("/pool0evil")
        self.assertTrue(p.startswith(cli.DATA_ROOT + "/") or p == cli.DATA_ROOT)
        self.assertNotEqual(p, "/pool0evil")


class TestFnmatchToRe(unittest.TestCase):
    def test_star(self):
        r = cli.fnmatch_to_re("*.mp4")
        self.assertTrue(__import__("re").fullmatch(r, "a.mp4"))
        self.assertFalse(__import__("re").fullmatch(r, "a.txt"))
        self.assertFalse(__import__("re").fullmatch(r, "a.mp4.bak"))

    def test_question(self):
        r = cli.fnmatch_to_re("a?.txt")
        self.assertTrue(__import__("re").fullmatch(r, "ab.txt"))
        self.assertFalse(__import__("re").fullmatch(r, "aab.txt"))
        self.assertFalse(__import__("re").fullmatch(r, "a.txt"))


class TestParseMultistatus(unittest.TestCase):
    SAMPLE = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/pool0/data/folder/</D:href>
    <D:propstat><D:prop>
      <D:displayname>folder</D:displayname>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/pool0/data/folder/a.txt</D:href>
    <D:propstat><D:prop>
      <D:displayname>a.txt</D:displayname>
      <D:getcontentlength>12</D:getcontentlength>
      <D:resourcetype/>
      <D:getlastmodified>Mon, 01 Jan 2026 00:00:00 GMT</D:getlastmodified>
    </D:prop></D:propstat>
  </D:response>
</D:multistatus>
"""

    def test_depth1_skips_self_keeps_child(self):
        items = cli.parse_multistatus(self.SAMPLE, self_prefix="/pool0/data/folder")
        names = {it["name"]: it for it in items}
        self.assertIn("a.txt", names)
        self.assertNotIn("folder", names)  # self filtered at depth 1
        self.assertFalse(names["a.txt"]["is_dir"])
        self.assertEqual(names["a.txt"]["size"], 12)

    def test_depth0_keeps_self(self):
        single = """<?xml version="1.0"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/pool0/data/folder/</D:href>
    <D:propstat><D:prop>
      <D:displayname>folder</D:displayname>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop></D:propstat>
  </D:response>
</D:multistatus>
"""
        items = cli.parse_multistatus(single, self_prefix="/pool0/data/folder")
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["is_dir"])
        self.assertEqual(items[0]["name"], "folder")

    def test_alternate_prefix_still_parses(self):
        # some servers use lowercase d: prefix
        text = self.SAMPLE.replace("<D:", "<d:").replace("</D:", "</d:")
        items = cli.parse_multistatus(text, self_prefix="/pool0/data/folder")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "a.txt")


if __name__ == "__main__":
    unittest.main()
