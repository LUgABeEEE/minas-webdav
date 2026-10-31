"""Command handlers: one function per CLI subcommand."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from .client import MinasWebDAV
from .paths import enc_path, ensure_data_path, fmt_size, fnmatch_to_re, norm


def cmd_ls(client: MinasWebDAV, args: argparse.Namespace) -> int:
    path = ensure_data_path(args.path)
    try:
        items = client.propfind(path, depth="0" if args.self_only else "1", with_mtls=True)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    # For depth 1, drop self if present
    if not args.self_only:
        items = [it for it in items if norm(it["path"]) != norm(path)]
    items.sort(key=lambda x: (not x["is_dir"], x["name"]))
    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0
    for it in items:
        kind = "d" if it["is_dir"] else "-"
        size = fmt_size(it["size"]) if not it["is_dir"] else ""
        print(f"{kind} {size:>10}  {it['name']}")
    return 0


def cmd_stat(client: MinasWebDAV, args: argparse.Namespace) -> int:
    path = ensure_data_path(args.path)
    try:
        items = client.propfind(path, depth="0", with_mtls=True)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    if not items:
        print("not found", file=sys.stderr)
        return 2
    it = items[0]
    if args.json:
        print(json.dumps(it, ensure_ascii=False, indent=2))
    else:
        print(f"path: {it['path']}")
        print(f"name: {it['name']}")
        print(f"type: {'dir' if it['is_dir'] else 'file'}")
        print(f"size: {it['size']} ({fmt_size(it['size'])})")
        print(f"modified: {it.get('modified','')}")
    return 0


def walk_sizes(client: MinasWebDAV, path: str, max_depth: int, depth: int = 0) -> tuple[int, int]:
    """Return (total_bytes, file_count)."""
    total = 0
    count = 0
    try:
        items = client.propfind(path, depth="1", with_mtls=True)
    except Exception as e:
        print(f"warn: {path}: {e}", file=sys.stderr)
        return 0, 0
    for it in items:
        if norm(it["path"]) == norm(path):
            continue
        if it["is_dir"]:
            if depth < max_depth:
                sub_total, sub_count = walk_sizes(client, it["path"], max_depth, depth + 1)
                total += sub_total
                count += sub_count
        else:
            total += it["size"]
            count += 1
    return total, count


def cmd_du(client: MinasWebDAV, args: argparse.Namespace) -> int:
    path = ensure_data_path(args.path)
    max_depth = args.max_depth
    try:
        items = client.propfind(path, depth="1", with_mtls=True)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    rows = []
    for it in items:
        if norm(it["path"]) == norm(path):
            continue
        if it["is_dir"]:
            total, count = walk_sizes(client, it["path"], max_depth=max_depth)
            rows.append((it["name"], total, count, True))
        else:
            rows.append((it["name"], it["size"], 1, False))
    rows.sort(key=lambda r: -r[1])
    if args.json:
        payload = [{"name": n, "bytes": b, "files": c, "is_dir": d} for n, b, c, d in rows]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    grand = 0
    for name, total, count, is_dir in rows:
        grand += total
        mark = "/" if is_dir else ""
        print(f"{fmt_size(total):>10}  {count:>6}  {name}{mark}")
    print("-" * 40)
    print(f"{fmt_size(grand):>10}  TOTAL")
    return 0


def cmd_df(client: MinasWebDAV, args: argparse.Namespace) -> int:
    # use LuCI storage API when possible via discover payload
    try:
        payload = client.discover()
        pool = (payload.get("data") or {}).get("internal_pool") or []
        if pool:
            p0 = pool[0]
            total = int(p0.get("total_size") or 0)
            used = int(p0.get("used_size") or 0)
            info = {
                "name": p0.get("name"),
                "total_bytes": total,
                "used_bytes": used,
                "free_bytes": total - used,
                "total_human": fmt_size(total),
                "used_human": fmt_size(used),
                "free_human": fmt_size(total - used),
                "data_dir": p0.get("data_dir"),
            }
            if args.json:
                print(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                print(f"pool: {info['name']}  data_dir={info['data_dir']}")
                print(f"total: {info['total_human']}  used: {info['used_human']}  free: {info['free_human']}")
            return 0
    except Exception as e:
        print(f"warn: pool info unavailable: {e}", file=sys.stderr)
    print("pool info unavailable", file=sys.stderr)
    return 3


def cmd_get(client: MinasWebDAV, args: argparse.Namespace) -> int:
    remote = ensure_data_path(args.remote)
    local = Path(args.local)
    status, headers, data = client.request("GET", remote, with_mtls=True)
    if status == 404:
        print(f"not found: {remote}", file=sys.stderr)
        return 2
    if status not in (200, 206):
        print(f"GET {remote} -> HTTP {status}", file=sys.stderr)
        return 1
    if local.is_dir():
        local = local / norm(remote).rstrip("/").split("/")[-1]
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    print(f"saved {local} ({fmt_size(len(data))})")
    return 0


def cmd_put(client: MinasWebDAV, args: argparse.Namespace) -> int:
    local = Path(args.local)
    if not local.exists():
        print(f"local not found: {local}", file=sys.stderr)
        return 2
    if local.is_dir():
        print("local is a directory; upload files one by one or use a sync tool", file=sys.stderr)
        return 1
    remote = ensure_data_path(args.remote)
    data = local.read_bytes()
    res = safe_put(client, remote, data)
    if not res["ok"]:
        print(f"upload failed: {res['error']}", file=sys.stderr)
        return 1
    print(f"uploaded {local} -> {remote} ({fmt_size(len(data))}) verified={res['verified']}")
    return 0


def cmd_cat(client: MinasWebDAV, args: argparse.Namespace) -> int:
    remote = ensure_data_path(args.path)
    status, _, data = client.request("GET", remote, with_mtls=True)
    if status == 404:
        print(f"not found: {remote}", file=sys.stderr)
        return 2
    if status not in (200, 206):
        print(f"GET failed HTTP {status}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(data)
    return 0


def cmd_mkdir(client: MinasWebDAV, args: argparse.Namespace) -> int:
    path = ensure_data_path(args.path)
    # create parents
    parts = norm(path).strip("/").split("/")
    cur = ""
    for part in parts:
        cur += "/" + part
        status, _, body = client.request("MKCOL", cur + "/", with_mtls=True)
        if status not in (201, 204, 405):  # 405 = already exists
            if status != 201 and status != 204:
                # 301/405 ok-ish
                if status not in (301, 405):
                    print(f"MKCOL {cur} -> HTTP {status}", file=sys.stderr)
                    return 1
    print(f"mkdir ok: {path}")
    return 0


def cmd_rm(client: MinasWebDAV, args: argparse.Namespace) -> int:
    path = ensure_data_path(args.path)
    if args.recursive:
        # delete children first
        try:
            items = client.propfind(path, depth="1", with_mtls=True)
        except RuntimeError:
            items = []
        for it in items:
            if norm(it["path"]) == norm(path):
                continue
            if it["is_dir"]:
                cmd_rm(client, argparse.Namespace(path=it["path"], recursive=True, json=False, force=True))
            else:
                client.request("DELETE", it["path"], with_mtls=True)
    status, _, body = client.request("DELETE", path, with_mtls=True)
    if status in (200, 204, 404):
        print(f"removed: {path}")
        return 0
    if status == 409 and args.recursive:
        print(f"DELETE {path} -> 409 (not empty?)", file=sys.stderr)
        return 1
    print(f"DELETE {path} -> HTTP {status}: {body[:160]!r}", file=sys.stderr)
    return 1


def dest_header(dest_path: str) -> str:
    # path-only works (IP-in-URL → 400); must be percent-encoded — header
    # values are latin-1 to http.client and raw CJK would raise.
    return enc_path(norm(dest_path))


# ---------------------------------------------------------------------------

#
# 实测（2026-10-15，待办 t-f0df70f0）：设备上的 PUT 覆盖一个**已存在**的资源时
# **不会截断**——新内容从偏移 0 写进去，旧文件的尾巴原样留着，于是文件变成
# 「新头 + 旧尾」的混合体，服务端报告的长度仍是旧长度，而 PUT 照样回 204。
# 24MB -> 2MB 得到的是 25165824 字节、sha256 既不是新版也不是旧版的文件；
# 只要新内容比旧内容**短哪怕 1 字节**就会触发，与文件大小无关。
#
# 修法：绝不 PUT 到已存在的名字。先传到同目录的临时名（全新创建，不存在旧尾巴），
# 再 MOVE 覆盖到目标名（替换是原子的）。MOVE 不可用时退回 DELETE + PUT。
# 写完必须回读核对长度（长度不符 = 正是这个 bug 的形状），默认再核一次 sha256。
# ---------------------------------------------------------------------------

# sha | size | off —— 回读核对的强度，可用环境变量降级（大文件嫌慢时）
PUT_VERIFY = os.environ.get("MINAS_PUT_VERIFY", "sha").strip().lower()
PUT_TMP_SUFFIX = ".minas-uploading"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exists(client: MinasWebDAV, path: str) -> bool:
    try:
        return bool(client.propfind(path, depth="0", with_mtls=True))
    except Exception:  # noqa: BLE001 — 判定失败按「不存在」处理，回读会兜住
        return False


def _put_bytes(client: MinasWebDAV, path: str, data: bytes) -> tuple[int, bytes]:
    status, _, body = client.request(
        "PUT", path, body=data,
        headers={"Content-Type": "application/octet-stream"}, with_mtls=True,
    )
    return status, body


def _move(client: MinasWebDAV, src: str, dst: str) -> int:
    status, _, _ = client.request(
        "MOVE", src,
        headers={"Destination": dest_header(dst), "Overwrite": "T"},
        with_mtls=True,
    )
    return status


def safe_put(client: MinasWebDAV, remote: str, data: bytes,
             verify: str | None = None) -> dict[str, Any]:
    """把 data 安全写到 remote，返回 ok / status / size / verified / error。

    从不直接 PUT 到已存在的名字；写完回读核对，不符就 ok=False，绝不静默成功。
    """
    verify = (verify or PUT_VERIFY or "sha").lower()
    remote = norm(remote)
    tmp = remote + PUT_TMP_SUFFIX
    client.request("DELETE", tmp, with_mtls=True)  # 清掉上一次可能留下的残片

    status, body = _put_bytes(client, tmp, data)
    if status not in (200, 201, 204):
        return {"ok": False, "status": status,
                "error": f"PUT {tmp} -> HTTP {status}: {body[:160]!r}"}

    target_existed = _exists(client, remote)
    moved = _move(client, tmp, remote)
    if moved not in (200, 201, 204):
        if not target_existed:
            return {"ok": False, "status": moved,
                    "error": f"MOVE {tmp} -> {remote} -> HTTP {moved}"}
        # 退回 DELETE + PUT：删掉旧的之后就是全新创建，不存在留尾巴的前提
        client.request("DELETE", remote, with_mtls=True)
        status2, body2 = _put_bytes(client, remote, data)
        client.request("DELETE", tmp, with_mtls=True)
        if status2 not in (200, 201, 204):
            return {"ok": False, "status": status2,
                    "error": f"PUT {remote} -> HTTP {status2}: {body2[:160]!r}"}

    items = client.propfind(remote, depth="0", with_mtls=True)
    got_size = items[0].get("size") if items else None
    if got_size != len(data):
        return {"ok": False, "status": 204, "size": got_size, "expected": len(data),
                "error": f"回读长度 {got_size} != 写入 {len(data)}（正是不截断那个 bug 的形状）"}

    if verify == "off":
        return {"ok": True, "status": 204, "size": got_size, "verified": "none"}
    if verify == "sha":
        _, _, back = client.request("GET", remote, with_mtls=True)
        if _sha256(back) != _sha256(data):
            return {"ok": False, "status": 204, "size": got_size,
                    "error": "回读 sha256 与写入内容不一致"}
        return {"ok": True, "status": 204, "size": got_size,
                "sha256": _sha256(data), "verified": "size+sha256"}
    return {"ok": True, "status": 204, "size": got_size, "verified": "size"}

def cmd_mv(client: MinasWebDAV, args: argparse.Namespace) -> int:
    src = ensure_data_path(args.src)
    dst = ensure_data_path(args.dst)
    status, _, body = client.request(
        "MOVE",
        src,
        headers={"Destination": dest_header(dst), "Overwrite": "T" if args.force else "F"},
        with_mtls=True,
    )
    if status in (200, 201, 204):
        print(f"moved {src} -> {dst}")
        return 0
    print(f"MOVE failed HTTP {status}: {body[:160]!r}", file=sys.stderr)
    return 1


def cmd_cp(client: MinasWebDAV, args: argparse.Namespace) -> int:
    src = ensure_data_path(args.src)
    dst = ensure_data_path(args.dst)
    status, _, body = client.request(
        "COPY",
        src,
        headers={"Destination": dest_header(dst), "Overwrite": "T" if args.force else "F"},
        with_mtls=True,
    )
    if status in (200, 201, 204):
        print(f"copied {src} -> {dst}")
        return 0
    print(f"COPY failed HTTP {status}: {body[:160]!r}", file=sys.stderr)
    return 1


def cmd_find(client: MinasWebDAV, args: argparse.Namespace) -> int:
    root = ensure_data_path(args.path)
    max_depth = args.max_depth
    name_re = re.compile(fnmatch_to_re(args.name)) if args.name else None
    found = []

    def rec(path: str, depth: int) -> None:
        try:
            items = client.propfind(path, depth="1", with_mtls=True)
        except Exception as e:
            print(f"warn: {path}: {e}", file=sys.stderr)
            return
        for it in items:
            if norm(it["path"]) == norm(path):
                continue
            ok = True
            if name_re and not name_re.search(it["name"]):
                ok = False
            if args.files and it["is_dir"]:
                ok = False
            if args.dirs and not it["is_dir"]:
                ok = False
            if ok:
                found.append(it)
            if it["is_dir"] and depth < max_depth:
                rec(it["path"], depth + 1)

    rec(root, 0)
    if args.json:
        print(json.dumps(found, ensure_ascii=False, indent=2))
    else:
        for it in found:
            mark = "/" if it["is_dir"] else ""
            print(f"{fmt_size(it['size']):>10}  {it['path']}{mark}")
    return 0

def cmd_tree(client: MinasWebDAV, args: argparse.Namespace) -> int:
    root = ensure_data_path(args.path)

    def rec(path: str, prefix: str, depth: int) -> None:
        try:
            items = client.propfind(path, depth="1", with_mtls=True)
        except Exception:
            return
        items = [it for it in items if norm(it["path"]) != norm(path)]
        items.sort(key=lambda x: (not x["is_dir"], x["name"]))
        for i, it in enumerate(items):
            last = i == len(items) - 1
            branch = "└── " if last else "├── "
            extra = "/" if it["is_dir"] else f"  ({fmt_size(it['size'])})"
            print(f"{prefix}{branch}{it['name']}{extra}")
            if it["is_dir"] and depth < args.max_depth:
                rec(it["path"], prefix + ("    " if last else "│   "), depth + 1)

    print(root)
    rec(root, "", 0)
    return 0
