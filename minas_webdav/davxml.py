"""PROPFIND multistatus parsing (namespace-prefix agnostic)."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any


def _split_responses(text: str) -> list[str]:
    """Split a multistatus body on <xxx:response> regardless of namespace prefix."""
    return re.split(r"<(?:[A-Za-z0-9_]+:)?response(?:\s[^>]*)?>", text)[1:]


def _tag_text(block: str, local: str) -> str | None:
    m = re.search(rf"<(?:[A-Za-z0-9_]+:)?{local}(?:\s[^>]*)?>(.*?)</(?:[A-Za-z0-9_]+:)?{local}>", block, re.S)
    return m.group(1) if m else None


def parse_multistatus(text: str, self_prefix: str = "") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    blocks = _split_responses(text)
    for block in blocks:
        href_raw = _tag_text(block, "href")
        if href_raw is None:
            continue
        href = urllib.parse.unquote(href_raw)
        name_raw = _tag_text(block, "displayname")
        size_raw = _tag_text(block, "getcontentlength")
        mod_raw = _tag_text(block, "getlastmodified")
        is_dir = bool(re.search(r"<(?:[A-Za-z0-9_]+:)?collection(?:\s*/|>)", block))
        name = urllib.parse.unquote(name_raw) if name_raw else href.rstrip("/").split("/")[-1]
        size = int(size_raw) if size_raw and size_raw.isdigit() else 0
        # skip self entry when depth>0 includes it
        if self_prefix and href.rstrip("/") == self_prefix.rstrip("/") and len(blocks) > 1:
            # keep only if sole entry (depth 0)
            continue
        items.append(
            {
                "path": href if href.startswith("/") else "/" + href,
                "name": name,
                "size": size,
                "is_dir": is_dir,
                "modified": mod_raw or "",
            }
        )
    # depth=0 often returns exactly one self item — keep it
    if not items:
        items = parse_multistatus_self(text)
    return items


def parse_multistatus_self(text: str) -> list[dict[str, Any]]:
    out = []
    for block in _split_responses(text):
        href_raw = _tag_text(block, "href")
        if href_raw is None:
            continue
        href = urllib.parse.unquote(href_raw)
        name_raw = _tag_text(block, "displayname")
        is_dir = bool(re.search(r"<(?:[A-Za-z0-9_]+:)?collection(?:\s*/|>)", block))
        size_raw = _tag_text(block, "getcontentlength")
        out.append(
            {
                "path": href,
                "name": urllib.parse.unquote(name_raw) if name_raw else href,
                "size": int(size_raw) if size_raw and size_raw.isdigit() else 0,
                "is_dir": is_dir,
                "modified": "",
            }
        )
    return out
