#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""MINAS WebDAV CLI for agent file ops on Xiaomi Smart Storage.

No drive-letter mount required. Talks to the device WebDAV API directly.

Examples:
  python -m minas_webdav ls /pool0/data
  python -m minas_webdav ls /pool0/data --json
  python -m minas_webdav du /pool0/data/我的照片 --max-depth 2
  python -m minas_webdav get /pool0/data/test.txt ./local.txt
  python -m minas_webdav put ./local.txt /pool0/data/test.txt
  python -m minas_webdav mkdir /pool0/data/work
  python -m minas_webdav mv /pool0/data/a.txt /pool0/data/work/a.txt
  python -m minas_webdav rm /pool0/data/work --recursive
  python -m minas_webdav df
  python -m minas_webdav find /pool0/data --name "*.mp4" --max-depth 3

Exit codes: 0 ok, 1 usage/error, 2 not found, 3 auth/network.

The implementation lives in `client` (transport), `davxml` (PROPFIND parsing),
`paths` (path sandbox) and `commands` (one handler per subcommand); this module
keeps the argparse surface plus the historical `minas_webdav.cli.*` import
surface.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .client import (
    CERT_HOME,
    DEFAULT_NAS_IP,
    DEFAULT_WEBDAV_PORT,
    MinasWebDAV,
    _cn_from_der,
    client_ctx,
    find_certs,
    resolve_server_cn,
)
from .commands import (
    PUT_TMP_SUFFIX,
    PUT_VERIFY,
    _exists,
    _move,
    _put_bytes,
    _sha256,
    cmd_cat,
    cmd_cp,
    cmd_df,
    cmd_du,
    cmd_find,
    cmd_get,
    cmd_ls,
    cmd_mkdir,
    cmd_mv,
    cmd_put,
    cmd_rm,
    cmd_stat,
    cmd_tree,
    dest_header,
    safe_put,
    walk_sizes,
)
from .davxml import (
    _split_responses,
    _tag_text,
    parse_multistatus,
    parse_multistatus_self,
)
from .paths import DATA_ROOT, enc_path, ensure_data_path, fmt_size, fnmatch_to_re, norm

# Re-exported on purpose: this module stays the stable import surface for the
# MCP server, probe/proxy and third-party scripts.
__all__ = [
    "CERT_HOME",
    "DATA_ROOT",
    "DEFAULT_NAS_IP",
    "DEFAULT_WEBDAV_PORT",
    "MinasWebDAV",
    "PUT_TMP_SUFFIX",
    "PUT_VERIFY",
    "_cn_from_der",
    "_exists",
    "_move",
    "_put_bytes",
    "_sha256",
    "_split_responses",
    "_tag_text",
    "build_parser",
    "client_ctx",
    "cmd_cat",
    "cmd_cp",
    "cmd_df",
    "cmd_du",
    "cmd_find",
    "cmd_get",
    "cmd_ls",
    "cmd_mkdir",
    "cmd_mv",
    "cmd_put",
    "cmd_rm",
    "cmd_stat",
    "cmd_tree",
    "dest_header",
    "enc_path",
    "ensure_data_path",
    "find_certs",
    "fmt_size",
    "fnmatch_to_re",
    "main",
    "norm",
    "parse_multistatus",
    "parse_multistatus_self",
    "resolve_server_cn",
    "safe_put",
    "walk_sizes",
]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="minas-webdav", description="Xiaomi Smart Storage WebDAV CLI for agents")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--ip", default=DEFAULT_NAS_IP, help="NAS IP (default env MINAS_IP or 192.168.1.100)")
    p.add_argument("--port", type=int, default=DEFAULT_WEBDAV_PORT, help="WebDAV port (default 5000)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ls", help="list directory")
    sp.add_argument("path", nargs="?", default=DATA_ROOT)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--self-only", action="store_true", help="only stat the path itself")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("stat", help="stat one path")
    sp.add_argument("path")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_stat)

    sp = sub.add_parser("du", help="directory sizes")
    sp.add_argument("path", nargs="?", default=DATA_ROOT)
    sp.add_argument("--max-depth", type=int, default=2)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_du)

    sp = sub.add_parser("df", help="pool capacity")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_df)

    sp = sub.add_parser("get", help="download file")
    sp.add_argument("remote")
    sp.add_argument("local")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("put", help="upload file")
    sp.add_argument("local")
    sp.add_argument("remote")
    sp.set_defaults(func=cmd_put)

    sp = sub.add_parser("cat", help="print file to stdout")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_cat)

    sp = sub.add_parser("mkdir", help="create directory (with parents)")
    sp.add_argument("path")
    sp.set_defaults(func=cmd_mkdir)

    sp = sub.add_parser("rm", help="delete file/dir")
    sp.add_argument("path")
    sp.add_argument("-r", "--recursive", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_rm)

    sp = sub.add_parser("mv", help="move/rename")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_mv)

    sp = sub.add_parser("cp", help="copy")
    sp.add_argument("src")
    sp.add_argument("dst")
    sp.add_argument("-f", "--force", action="store_true")
    sp.set_defaults(func=cmd_cp)

    sp = sub.add_parser("find", help="find by name pattern")
    sp.add_argument("path", nargs="?", default=DATA_ROOT)
    sp.add_argument("--name", help="wildcard, e.g. '*.mp4'")
    sp.add_argument("--max-depth", type=int, default=3)
    sp.add_argument("--files", action="store_true")
    sp.add_argument("--dirs", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("tree", help="print tree")
    sp.add_argument("path", nargs="?", default=DATA_ROOT)
    sp.add_argument("--max-depth", type=int, default=2)
    sp.set_defaults(func=cmd_tree)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    client = MinasWebDAV(ip=args.ip, port=args.port)
    try:
        return args.func(client, args)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as e:
        msg = str(e)
        print(msg, file=sys.stderr)
        if "cert" in msg.lower() or "discover" in msg.lower():
            return 3
        return 1
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
