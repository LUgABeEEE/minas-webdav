"""Offline tests for the CLI command layer.

The command handlers only touch the ``MinasWebDAV`` client interface
(``propfind`` / ``request`` / ``discover``), so a canned fake is enough — no
NAS, no network, no credentials. These tests pin the observable behaviour:
which PROPFIND depths and DAV methods are used, what the text/JSON output looks
like, and which exit code a failure produces.
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout

from minas_webdav import cli

DATA = "/pool0/data"


def item(path: str, name: str | None = None, size: int = 0, is_dir: bool = False,
         modified: str = "") -> dict:
    return {
        "path": path,
        "name": name if name is not None else path.rstrip("/").split("/")[-1],
        "size": size,
        "is_dir": is_dir,
        "modified": modified,
    }


class FakeClient:
    """Stand-in for :class:`minas_webdav.cli.MinasWebDAV`."""

    def __init__(self, tree: dict | None = None, replies: dict | None = None,
                 pool: list | None = None):
        self.tree = tree or {}
        self.replies = replies or {}
        self.pool = pool if pool is not None else []
        self.calls: list[tuple] = []

    def propfind(self, path: str, depth: str = "1", with_mtls: bool = False):
        self.calls.append(("PROPFIND", path, depth))
        if path not in self.tree:
            raise RuntimeError(f"PROPFIND {path} -> HTTP 404")
        entries = self.tree[path]
        if depth == "0":  # a real device returns only the target entry
            for entry in entries:
                if cli.norm(entry["path"]) == cli.norm(path):
                    return [dict(entry)]
            return [dict(entries[0])]
        return [dict(x) for x in entries]

    def request(self, method: str, path: str, body=None, headers=None,
                with_mtls: bool = False):
        self.calls.append((method, path, dict(headers or {})))
        return self.replies.get((method, path), (200, {}, b""))
    def discover(self):
        self.calls.append(("DISCOVER", "", ""))
        return {"data": {"internal_pool": self.pool}}

    def methods(self) -> list[str]:
        return [c[0] for c in self.calls]

    def paths_for(self, method: str) -> list[str]:
        return [c[1] for c in self.calls if c[0] == method]


def run(func, client, **kwargs):
    """Call a command handler with a Namespace; return (rc, stdout)."""
    out = io.StringIO()
    with redirect_stdout(out):
        rc = func(client, argparse.Namespace(**kwargs))
    return rc, out.getvalue()


class TestLs(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(tree={
            DATA: [
                item(DATA, name="data", is_dir=True),
                item(f"{DATA}/video", name="video", is_dir=True),
                item(f"{DATA}/a.txt", name="a.txt", size=100),
            ],
            f"{DATA}/video": [item(f"{DATA}/video", name="video", is_dir=True)],
        })

    def test_json_drops_self_and_sorts_dirs_first(self):
        rc, out = run(cli.cmd_ls, self.client, path=DATA, json=True,
                      self_only=False, long=True)
        self.assertEqual(rc, 0)
        names = [row["name"] for row in json.loads(out)]
        self.assertEqual(names, ["video", "a.txt"])

    def test_text_output_marks_dirs(self):
        rc, out = run(cli.cmd_ls, self.client, path=DATA, json=False,
                      self_only=False, long=True)
        self.assertEqual(rc, 0)
        self.assertIn("d ", out)
        self.assertIn("video", out)
        self.assertIn("a.txt", out)

    def test_self_only_keeps_the_entry(self):
        rc, out = run(cli.cmd_ls, self.client, path=DATA, json=True,
                      self_only=True, long=True)
        self.assertEqual(rc, 0)
        self.assertEqual([row["name"] for row in json.loads(out)], ["data"])
        # depth "0" must be requested for --self-only
        self.assertIn(("PROPFIND", DATA, "0"), self.client.calls)

    def test_missing_directory_is_not_found(self):
        rc, _ = run(cli.cmd_ls, self.client, path=f"{DATA}/nope", json=False,
                    self_only=False, long=True)
        self.assertEqual(rc, 2)


class TestStat(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(tree={
            f"{DATA}/a.txt": [item(f"{DATA}/a.txt", size=1234, modified="Wed")],
        })

    def test_json(self):
        rc, out = run(cli.cmd_stat, self.client, path=f"{DATA}/a.txt", json=True)
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["size"], 1234)

    def test_text(self):
        rc, out = run(cli.cmd_stat, self.client, path=f"{DATA}/a.txt", json=False)
        self.assertEqual(rc, 0)
        self.assertIn("type: file", out)
        self.assertIn("1234", out)

    def test_not_found(self):
        rc, _ = run(cli.cmd_stat, self.client, path=f"{DATA}/missing", json=False)
        self.assertEqual(rc, 2)


class TestDu(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(tree={
            DATA: [
                item(DATA, name="data", is_dir=True),
                item(f"{DATA}/docs", name="docs", is_dir=True),
                item(f"{DATA}/a.txt", name="a.txt", size=100),
            ],
            f"{DATA}/docs": [
                item(f"{DATA}/docs", name="docs", is_dir=True),
                item(f"{DATA}/docs/x.bin", name="x.bin", size=2048),
                item(f"{DATA}/docs/y.bin", name="y.bin", size=2000),
            ],
        })

    def test_json_totals(self):
        rc, out = run(cli.cmd_du, self.client, path=DATA, max_depth=2, json=True)
        rows = {row["name"]: row for row in json.loads(out)}
        self.assertEqual(rc, 0)
        self.assertEqual(rows["docs"]["bytes"], 4048)
        self.assertEqual(rows["docs"]["files"], 2)
        self.assertEqual(rows["a.txt"]["bytes"], 100)

    def test_text_has_total_line(self):
        rc, out = run(cli.cmd_du, self.client, path=DATA, max_depth=2, json=False)
        self.assertEqual(rc, 0)
        self.assertIn("TOTAL", out)


class TestFind(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient(tree={
            DATA: [
                item(DATA, name="data", is_dir=True),
                item(f"{DATA}/movie.mp4", name="movie.mp4", size=10),
                item(f"{DATA}/notes.txt", name="notes.txt", size=5),
                item(f"{DATA}/sub", name="sub", is_dir=True),
            ],
            f"{DATA}/sub": [
                item(f"{DATA}/sub", name="sub", is_dir=True),
                item(f"{DATA}/sub/deep.mp4", name="deep.mp4", size=7),
            ],
        })

    def test_wildcard_and_files_only(self):
        rc, out = run(cli.cmd_find, self.client, path=DATA, name="*.mp4",
                      max_depth=3, files=True, dirs=False, json=True)
        names = sorted(row["name"] for row in json.loads(out))
        self.assertEqual(rc, 0)
        self.assertEqual(names, ["deep.mp4", "movie.mp4"])

    def test_dirs_only(self):
        rc, out = run(cli.cmd_find, self.client, path=DATA, name=None,
                      max_depth=3, files=False, dirs=True, json=True)
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(row["name"] for row in json.loads(out)), ["sub"])


class TestTree(unittest.TestCase):
    def test_renders_branches(self):
        client = FakeClient(tree={
            DATA: [
                item(DATA, name="data", is_dir=True),
                item(f"{DATA}/docs", name="docs", is_dir=True),
                item(f"{DATA}/a.txt", name="a.txt", size=2048),
            ],
            f"{DATA}/docs": [item(f"{DATA}/docs", name="docs", is_dir=True)],
        })
        rc, out = run(cli.cmd_tree, client, path=DATA, max_depth=2)
        self.assertEqual(rc, 0)
        self.assertIn(f"{DATA}", out)
        self.assertIn("├── docs", out)
        self.assertIn("└── a.txt", out)


class TestMkdir(unittest.TestCase):
    def test_creates_each_level(self):
        client = FakeClient(replies={("MKCOL", "/pool0/"): (201, {}, b""),
                                     ("MKCOL", "/pool0/data/"): (201, {}, b""),
                                     ("MKCOL", "/pool0/data/work/"): (201, {}, b"")})
        rc, out = run(cli.cmd_mkdir, client, path=f"{DATA}/work")
        self.assertEqual(rc, 0)
        self.assertIn("mkdir ok", out)
        self.assertEqual(client.paths_for("MKCOL"),
                         ["/pool0/", "/pool0/data/", "/pool0/data/work/"])

    def test_already_exists_is_fine(self):
        client = FakeClient(replies={("MKCOL", "/pool0/"): (405, {}, b""),
                                     ("MKCOL", "/pool0/data/"): (405, {}, b"")})
        rc, _ = run(cli.cmd_mkdir, client, path=DATA)
        self.assertEqual(rc, 0)

    def test_failure_bubbles_up(self):
        client = FakeClient(replies={("MKCOL", "/pool0/"): (500, {}, b"boom")})
        rc, _ = run(cli.cmd_mkdir, client, path=f"{DATA}/work")
        self.assertEqual(rc, 1)


class TestRm(unittest.TestCase):
    def test_recursive_deletes_children_then_parent(self):
        client = FakeClient(tree={
            f"{DATA}/dir": [
                item(f"{DATA}/dir", name="dir", is_dir=True),
                item(f"{DATA}/dir/sub", name="sub", is_dir=True),
                item(f"{DATA}/dir/a.txt", name="a.txt", size=1),
            ],
            f"{DATA}/dir/sub": [item(f"{DATA}/dir/sub", name="sub", is_dir=True)],
        })
        rc, out = run(cli.cmd_rm, client, path=f"{DATA}/dir", recursive=True,
                      json=False, force=True)
        self.assertEqual(rc, 0)
        self.assertIn("removed", out)
        deleted = client.paths_for("DELETE")
        self.assertIn(f"{DATA}/dir/sub", deleted)
        self.assertIn(f"{DATA}/dir/a.txt", deleted)
        self.assertEqual(deleted[-1], f"{DATA}/dir")

    def test_non_recursive_409_reports_failure(self):
        client = FakeClient(replies={("DELETE", f"{DATA}/dir"): (409, {}, b"")})
        rc, _ = run(cli.cmd_rm, client, path=f"{DATA}/dir", recursive=True,
                    json=False, force=True)
        self.assertEqual(rc, 1)

    def test_404_counts_as_removed(self):
        client = FakeClient(replies={("DELETE", f"{DATA}/gone"): (404, {}, b"")})
        rc, _ = run(cli.cmd_rm, client, path=f"{DATA}/gone", recursive=False,
                    json=False, force=True)
        self.assertEqual(rc, 0)


class TestMoveCopy(unittest.TestCase):
    def test_mv_sends_encoded_destination_and_overwrite(self):
        client = FakeClient(replies={("MOVE", f"{DATA}/a b.txt"): (201, {}, b"")})
        rc, out = run(cli.cmd_mv, client, src=f"{DATA}/a b.txt",
                      dst=f"{DATA}/b.txt", force=True)
        self.assertEqual(rc, 0)
        self.assertIn("moved", out)
        method, path, headers = client.calls[-1]
        self.assertEqual((method, path), ("MOVE", f"{DATA}/a b.txt"))
        self.assertEqual(headers["Destination"], "/pool0/data/b.txt")
        self.assertEqual(headers["Overwrite"], "T")

    def test_cp_without_force_uses_overwrite_false(self):
        client = FakeClient(replies={("COPY", f"{DATA}/a.txt"): (204, {}, b"")})
        rc, _ = run(cli.cmd_cp, client, src=f"{DATA}/a.txt", dst=f"{DATA}/c.txt",
                    force=False)
        self.assertEqual(rc, 0)
        self.assertEqual(client.calls[-1][2]["Overwrite"], "F")

    def test_failure_exit_code(self):
        client = FakeClient(replies={("MOVE", f"{DATA}/a.txt"): (409, {}, b"nope")})
        rc, _ = run(cli.cmd_mv, client, src=f"{DATA}/a.txt", dst=f"{DATA}/b.txt",
                    force=True)
        self.assertEqual(rc, 1)


class TestGetPut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.local = pathlib.Path(self.tmp.name) / "payload.bin"
        self.local.write_bytes(b"hello-minas")

    def test_get_writes_local_file(self):
        client = FakeClient(replies={("GET", f"{DATA}/a.txt"): (200, {}, b"abc")})
        target = pathlib.Path(self.tmp.name) / "out.txt"
        rc, out = run(cli.cmd_get, client, remote=f"{DATA}/a.txt", local=str(target))
        self.assertEqual(rc, 0)
        self.assertEqual(target.read_bytes(), b"abc")
        self.assertIn("saved", out)

    def test_get_404(self):
        client = FakeClient(replies={("GET", f"{DATA}/missing"): (404, {}, b"")})
        rc, _ = run(cli.cmd_get, client, remote=f"{DATA}/missing",
                    local=str(pathlib.Path(self.tmp.name) / "x"))
        self.assertEqual(rc, 2)

    def test_put_goes_through_temp_name_and_verifies(self):
        data = self.local.read_bytes()
        remote = f"{DATA}/payload.bin"
        client = FakeClient(
            tree={remote: [item(remote, size=len(data))]},
            replies={
                ("PUT", remote + cli.PUT_TMP_SUFFIX): (201, {}, b""),
                ("MOVE", remote + cli.PUT_TMP_SUFFIX): (204, {}, b""),
                ("GET", remote): (200, {}, data),
            },
        )
        rc, out = run(cli.cmd_put, client, local=str(self.local), remote=remote)
        self.assertEqual(rc, 0)
        self.assertIn("verified=size+sha256", out)
        # the payload is never PUT under its final name
        self.assertEqual(client.paths_for("PUT"), [remote + cli.PUT_TMP_SUFFIX])

    def test_put_missing_local_file(self):
        client = FakeClient()
        rc, _ = run(cli.cmd_put, client,
                    local=str(pathlib.Path(self.tmp.name) / "nope"),
                    remote=f"{DATA}/x")
        self.assertEqual(rc, 2)


class TestDf(unittest.TestCase):
    def test_pool_payload(self):
        client = FakeClient(pool=[{
            "name": "pool0", "total_size": 1024, "used_size": 512,
            "data_dir": "/pool0/data",
        }])
        rc, out = run(cli.cmd_df, client, json=True)
        payload = json.loads(out)
        self.assertEqual(rc, 0)
        self.assertEqual(payload["free_bytes"], 512)

    def test_no_pool_info(self):
        client = FakeClient()
        rc, _ = run(cli.cmd_df, client, json=False)
        self.assertEqual(rc, 3)


class TestVersionFlag(unittest.TestCase):
    def test_version_exits_zero_and_prints_version(self):
        import minas_webdav

        parser = cli.build_parser()
        out = io.StringIO()
        with redirect_stdout(out):
            with self.assertRaises(SystemExit) as ctx:
                parser.parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn(minas_webdav.__version__, out.getvalue())


if __name__ == "__main__":
    unittest.main()
