# SPDX-License-Identifier: Apache-2.0
"""Keep the docs from drifting away from the code.

Two things are pinned here:

* `skill/references/webdav-surface.md` is shipped inside the agent skill, while
  `docs/webdav-surface.md` is what the repository browses. They are meant to be
  the same file, so comparing bytes beats hoping someone copies the edit twice.
* The README's command table must list exactly the subcommands (and flags) that
  `build_parser()` exposes; regenerate it with
  ``MINAS_UPDATE_DOCS=1 python -m unittest tests.test_docs``.

`test_docs.py` is also where the table is generated from, so the table can
never describe a command the CLI does not have.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import unittest

from minas_webdav.cli import build_parser

ROOT = pathlib.Path(__file__).resolve().parent.parent

IDENTICAL_PAIRS = [
    (ROOT / "docs" / "webdav-surface.md", ROOT / "skill" / "references" / "webdav-surface.md"),
]

README = ROOT / "README.md"
TABLE_START = "<!-- command-table:start -->"
TABLE_END = "<!-- command-table:end -->"

# Short, human-facing one-liners; the CLI's own `help=` strings stay terse.
DESCRIPTIONS = {
    "ls": "列目录（`--json` 便于 agent 解析；`--self-only` 只 stat 自身）",
    "stat": "查看单个路径的属性（大小/时间等）",
    "du": "统计子目录体积（`--max-depth`，默认 2）",
    "df": "存储池容量（走 mTLS 的 LuCI API，需要客户端证书）",
    "get": "下载文件到本地",
    "put": "上传本地文件（带校验与失败回退）",
    "cat": "把远端文件打印到 stdout",
    "mkdir": "创建目录（自动建父级）",
    "rm": "删除文件/目录（`-r` 递归需谨慎）",
    "mv": "移动/改名（`-f` 覆盖）",
    "cp": "复制（`-f` 覆盖）",
    "find": "按名字通配查找（`--name` `--max-depth` `--files/--dirs`）",
    "tree": "打印目录树（`--max-depth`，默认 2）",
}

# `--help` is implied; the short aliases would just repeat the long form.
SKIP_FLAGS = {"-h", "--help"}
CANONICAL = {"-r": "--recursive", "-f": "--force"}


def command_table() -> str:
    """Render the README table straight from the argparse tree."""
    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    rows = ["| 命令 | 作用 | 主要参数 |", "|---|---|---|"]
    for name in sorted(subparsers.choices):
        sub = subparsers.choices[name]
        flags: list[str] = []
        for action in sub._actions:
            for opt in action.option_strings:
                canonical = CANONICAL.get(opt, opt)
                if canonical in SKIP_FLAGS or canonical in flags:
                    continue
                flags.append(canonical)
        params = " ".join(f"`{f}`" for f in flags) or "—"
        rows.append(f"| `{name}` | {DESCRIPTIONS.get(name, '')} | {params} |")
    return "\n".join(rows)


def readme_table() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(re.escape(TABLE_START) + r"(.*?)" + re.escape(TABLE_END), text, flags=re.S)
    if not match:
        raise AssertionError(f"{README.name} lost its {TABLE_START} … {TABLE_END} markers")
    return match.group(1).strip("\n")


def write_readme_table(table: str) -> None:
    text = README.read_text(encoding="utf-8")
    new = re.sub(
        re.escape(TABLE_START) + r".*?" + re.escape(TABLE_END),
        TABLE_START + "\n" + table + "\n" + TABLE_END,
        text,
        flags=re.S,
    )
    README.write_text(new, encoding="utf-8")


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


class TestCommandTable(unittest.TestCase):
    def test_readme_table_matches_the_parser(self):
        table = command_table()
        if os.environ.get("MINAS_UPDATE_DOCS"):
            write_readme_table(table)
            self.skipTest("README command table regenerated")
        self.assertEqual(
            readme_table(),
            table,
            "README 的命令表与 build_parser() 不一致；"
            "跑 `MINAS_UPDATE_DOCS=1 python -m unittest tests.test_docs` 重新生成",
        )

    def test_every_subcommand_is_documented(self):
        parser = build_parser()
        subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
        documented = set(re.findall(r"^\| `([a-z]+)` \|", readme_table(), flags=re.M))
        self.assertEqual(documented, set(subparsers.choices))


if __name__ == "__main__":
    unittest.main()
