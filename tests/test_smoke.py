"""Smoke tests: the package imports, the CLI is wired up, and the
example config parses — no NAS, no network, no credentials."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestPackage(unittest.TestCase):
    def test_version_is_semver(self):
        import minas_webdav

        self.assertRegex(minas_webdav.__version__, r"^\d+\.\d+\.\d+$")

    def test_example_config_parses(self):
        path = ROOT / "minas_webdav" / "minas_config.example.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("host", "port", "cn", "data_root"):
            self.assertIn(key, data)


class TestCli(unittest.TestCase):
    def test_help_lists_commands(self):
        out = subprocess.run(
            [sys.executable, "-m", "minas_webdav", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        for cmd in ("ls", "get", "put", "df", "tree"):
            self.assertIn(cmd, out.stdout)


if __name__ == "__main__":
    unittest.main()
