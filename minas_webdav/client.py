# SPDX-License-Identifier: Apache-2.0
"""Connection layer: mTLS context, device CN discovery, WebDAV client."""

from __future__ import annotations

import base64
import http.client
import json
import os
import re
import socket
import ssl
from pathlib import Path
from typing import Any

from . import config as _mconf
from .davxml import parse_multistatus
from .paths import enc_path

DEFAULT_NAS_IP = os.environ.get("MINAS_IP", "192.168.1.100")
DEFAULT_WEBDAV_PORT = int(os.environ.get("MINAS_PORT", "5000"))
# Platform-aware: %LOCALAPPDATA%\minasCert on Windows, $DSH_HOME/minasCert
# (else ~/.dsh/minasCert) elsewhere. Avoids the old Path("")/"minasCert"
# relative-path fallback when LOCALAPPDATA was unset.
CERT_HOME = _mconf.default_cert_home()


def _cn_from_der(der: bytes) -> str:
    """Subject CN of a DER certificate, cross-platform.

    Tries the ``cryptography`` package, then the ``openssl`` CLI (ubiquitous on
    POSIX), then ``certutil -dump`` (Windows). Returns "" if none work.
    """
    # 1) cryptography (pure-python, no subprocess)
    try:
        from cryptography import x509  # type: ignore
        from cryptography.x509.oid import NameOID  # type: ignore

        attrs = x509.load_der_x509_certificate(der).subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if attrs:
            return str(attrs[0].value).strip()
    except Exception:
        pass
    # 2) openssl CLI
    try:
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile("wb", suffix=".der", delete=False) as fh:
            fh.write(der)
            path = fh.name
        try:
            out = subprocess.run(
                ["openssl", "x509", "-inform", "DER", "-in", path, "-noout", "-subject"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            m = re.search(r"CN\s*=\s*([^,/\n]+)", out.stdout or "")
            if m:
                return m.group(1).strip()
        finally:
            Path(path).unlink(missing_ok=True)
    except Exception:
        pass
    # 3) certutil -dump (Windows)
    try:
        import subprocess
        import tempfile

        tmp = Path(tempfile.gettempdir()) / "minas_peer.cer"
        tmp.write_bytes(der)
        out = subprocess.check_output(["certutil", "-dump", str(tmp)], stderr=subprocess.STDOUT)
        m = re.search(r"CN=([^,\r\n]+)", out.decode("utf-8", "replace"))
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return ""


def find_certs() -> tuple[str, str, str] | None:
    if not CERT_HOME.exists():
        return None
    certs = sorted(CERT_HOME.glob("*_cert.pem"), key=lambda p: p.stat().st_mtime, reverse=True)
    for cert in certs:
        uid_did = cert.name.replace("_cert.pem", "")
        key = CERT_HOME / f"{uid_did}_private_key.pem"
        ca = CERT_HOME / "ca_chain.pem"
        if key.exists() and ca.exists():
            return str(cert), str(key), str(ca)
    return None


def resolve_server_cn(ip: str, port: int) -> str:
    """CN of the device certificate (used for Host/SNI), probed over TLS.

    Needed by entry points that have no config/env CN — the device rejects a
    bare IP/hostname.
    """
    return MinasWebDAV(ip, port)._resolve_cn()


def client_ctx() -> ssl.SSLContext:
    """TLS context for talking to the device, with mTLS when a cert trio exists.

    Measured 2026-11-01 against the live device: the **WebDAV** endpoint (:5000)
    answers 207 with Basic auth alone — no client certificate required, even
    with CA verification off. Its 451 is the *missing Basic auth* response, not
    a missing client certificate. The client cert is only required by the LuCI
    pool-info API on :443 (no cert → HTTP 400), which `df` and credential
    auto-discovery use — so we still present it whenever it exists.
    """
    certs = find_certs()
    if certs:
        cert, key, ca = certs
        ctx = _mconf.verified_ctx(ca)
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        ctx.check_hostname = False
        return ctx
    return _mconf.unverified_ctx()


class MinasWebDAV:
    def __init__(self, ip: str = DEFAULT_NAS_IP, port: int = DEFAULT_WEBDAV_PORT):
        self.ip = ip
        self.port = port
        self.username = os.environ.get("MINAS_USER", "")
        self.password = os.environ.get("MINAS_PASS", "")
        self.server_cn = os.environ.get("MINAS_CN", "")
        self._ctx = None
        self._token = ""
        self._connected = False

    def _make_ctx(self, with_mtls: bool) -> ssl.SSLContext:
        certs = find_certs()
        if with_mtls and certs:
            cert, key, ca = certs
            ctx = _mconf.verified_ctx(ca)
            ctx.load_cert_chain(certfile=cert, keyfile=key)
            ctx.check_hostname = False
            return ctx
        ctx = _mconf.unverified_ctx()
        return ctx

    def _resolve_cn(self) -> str:
        if self.server_cn:
            return self.server_cn
        # probe server cert CN
        ctx = _mconf.unverified_ctx()
        sock = socket.create_connection((self.ip, 443 if self.port == 5000 else self.port), timeout=8)
        try:
            ssock = ctx.wrap_socket(sock, server_hostname="x")
            der = ssock.getpeercert(binary_form=True)
            ssock.close()
        except Exception:
            # webdav port may not do 443 handshake the same; try webdav port
            sock.close()
            sock = socket.create_connection((self.ip, self.port), timeout=8)
            ssock = ctx.wrap_socket(sock, server_hostname="x")
            der = ssock.getpeercert(binary_form=True)
            ssock.close()
        # Parse the CN out of the DER cert, cross-platform (the old code shelled
        # out to `certutil`, which only exists on Windows).
        cn = _cn_from_der(der)
        if not cn:
            raise RuntimeError(
                "cannot parse server CN from cert; set `cn` in minas_config.json "
                "or MINAS_CN explicitly (needed for Host/SNI — the device rejects "
                "a bare IP/hostname)"
            )
        self.server_cn = cn
        return self.server_cn

    def discover(self) -> dict[str, Any]:
        """Fetch pool info via LuCI mTLS API (local tunnel or direct)."""
        certs = find_certs()
        if not certs:
            raise RuntimeError(
                f"certs not found under {CERT_HOME}; login the official client first "
                f"and/or copy the mTLS trio (*_cert.pem, *_private_key.pem, ca_chain.pem) "
                f"there, or set MINAS_CERT_HOME / cert_home to where they are. "
                f"[{_mconf.describe_env()}]"
            )
        cert, key, ca = certs
        cn = self._resolve_cn()
        ctx = _mconf.verified_ctx(ca)
        ctx.load_cert_chain(certfile=cert, keyfile=key)
        ctx.check_hostname = False

        hosts = [(self.ip, 443), ("127.0.0.1", 51087)]
        last_err = None
        for host, port in hosts:
            try:
                conn = http.client.HTTPSConnection(host, port, context=ctx, timeout=10)
                sock = socket.create_connection((host, port), timeout=10)
                ssock = ctx.wrap_socket(sock, server_hostname=cn)
                conn.sock = ssock
                body = b"{}"
                conn.request(
                    "POST",
                    "/cgi-bin/luci/filemgr/get_pool_info",
                    body=body,
                    headers={"Content-Type": "application/json", "Host": cn, "Content-Length": str(len(body))},
                )
                resp = conn.getresponse()
                data = resp.read()
                conn.close()
                if resp.status != 200:
                    last_err = f"{host}:{port} HTTP {resp.status}"
                    continue
                payload = json.loads(data.decode("utf-8", "replace"))
                w = payload.get("data", {}).get("webDAV") or {}
                if not w.get("username"):
                    last_err = f"{host}:{port} no webDAV creds"
                    continue
                self.username = w["username"]
                self.password = w["password"]
                self.server_cn = cn
                self._connected = True
                return payload
            except Exception as e:
                last_err = f"{host}:{port} {type(e).__name__}: {e}"
        raise RuntimeError(f"discover failed: {last_err}")

    def ensure_auth(self) -> None:
        if self.username and self.password and self.server_cn:
            self._token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()
            self._connected = True
            return
        if not self._connected:
            self.discover()
            self._token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode()

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        with_mtls: bool = False,
    ) -> tuple[int, dict[str, str], bytes]:
        self.ensure_auth()
        headers = dict(headers or {})
        headers.setdefault("Authorization", "Basic " + self._token)
        headers.setdefault("Host", self.server_cn)
        headers.setdefault("Connection", "close")
        headers.setdefault("User-Agent", "minas-cli/1.0")
        if body is not None:
            headers["Content-Length"] = str(len(body))
        ctx = self._make_ctx(with_mtls=with_mtls)
        sock = socket.create_connection((self.ip, self.port), timeout=60)
        ssock = ctx.wrap_socket(sock, server_hostname=self.server_cn)
        conn = http.client.HTTPSConnection(self.ip, self.port, context=ctx, timeout=60)
        conn.sock = ssock
        try:
            conn.request(method, enc_path(path), body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            hdrs = {k: v for k, v in resp.getheaders()}
            return resp.status, hdrs, data
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def propfind(self, path: str, depth: str = "1", with_mtls: bool = False) -> list[dict[str, Any]]:
        body = (
            b'<?xml version="1.0"?>'
            b'<a:propfind xmlns:a="DAV:"><a:prop>'
            b"<a:displayname/><a:getcontentlength/><a:resourcetype/>"
            b"<a:getlastmodified/><a:creationdate/>"
            b"</a:prop></a:propfind>"
        )
        status, _, data = self.request(
            "PROPFIND",
            path,
            body=body,
            headers={"Content-Type": "application/xml", "Depth": depth},
            with_mtls=with_mtls,
        )
        if status not in (207, 200):
            raise RuntimeError(f"PROPFIND {path} -> HTTP {status}: {data[:200]!r}")
        return parse_multistatus(data.decode("utf-8", "replace"), self_prefix=path)

    def is_dir(self, path: str) -> bool:
        items = self.propfind(path, depth="0", with_mtls=True)
        return bool(items) and items[0]["is_dir"]
