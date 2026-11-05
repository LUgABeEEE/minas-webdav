# SPDX-License-Identifier: Apache-2.0
"""Keep the packaged skill copy and the repo documentation from drifting apart.

`skill/references/webdav-surface.md` is shipped inside the agent skill, while
`docs/webdav-surface.md` is what the repository browses. They are meant to be
the same file, so pin that instead of relying on someone remembering to copy
the edit twice.
"""

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent

IDENTICAL_PAIRS = [
    (ROOT / "docs" / "webdav-surface.md", ROOT / "skill" / "references" / "webdav-surface.md"),
]


class TestDocCopies(unittest.TestCase):
    def test_copies_are_byte_identical(self):
        for source, copy in IDENTICAL_PAIRS:
            with self.subTest(copy=str(copy.relative_to(ROOT))):
                self.assertTrue(source.is_file(), f"missing {source}")
                self.assertTrue(copy.is_file(), f"missing {copy}")
                self.assertEqual(
                    source.read_bytes(),
                    copy.read_bytes(),
                    f"{copy.relative_to(ROOT)} drifted from {source.relative_to(ROOT)}; "
                    "copy the file instead of editing one side",
                )


if __name__ == "__main__":
    unittest.main()
