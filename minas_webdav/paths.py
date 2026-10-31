"""Path helpers: DAV path normalisation, size formatting, data-root sandbox."""
from __future__ import annotations

import os
import re
import urllib.parse

DATA_ROOT = os.environ.get("MINAS_DATA_ROOT", "/pool0/data")

def enc_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return "/".join(urllib.parse.quote(seg, safe="") if seg else seg for seg in path.split("/"))


def norm(path: str) -> str:
    path = path.replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    # collapse //
    while "//" in path:
        path = path.replace("//", "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return path

def fmt_size(n: float) -> str:
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def ensure_data_path(path: str) -> str:
    """Normalize a user path to an absolute path under DATA_ROOT.

    Rejects ``..`` escapes and sibling prefixes like ``/pool0evil``.
    Bare names are treated as relative to DATA_ROOT.
    """
    p = norm(path)
    if p in ("", "/"):
        return DATA_ROOT
    if ".." in p.split("/"):
        raise ValueError("path must stay under the data root (no '..')")
    root = norm(DATA_ROOT)
    # bare /name or name → under DATA_ROOT
    if p != root and not p.startswith(root + "/") and not p.startswith("/pool0/"):
        if not p.startswith("/"):
            p = "/" + p
        p = root.rstrip("/") + p
        p = norm(p)
        if ".." in p.split("/"):
            raise ValueError("path must stay under the data root (no '..')")
    # absolute paths must stay inside DATA_ROOT (not just /pool0*)
    if p != root and not p.startswith(root + "/"):
        raise ValueError(f"path outside data root ({root}): {path}")
    return p


# --------------- commands ---------------

def fnmatch_to_re(pattern: str) -> str:
    out = []
    for ch in pattern:
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)
