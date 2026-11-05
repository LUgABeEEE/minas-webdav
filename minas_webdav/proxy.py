"""Local WebDAV reverse proxy for Xiaomi Smart Storage (MINAS).
http://127.0.0.1:8899 -> https://<nas>:5000 with Basic auth.

The proxy is plain HTTP to a loopback port, so it is platform-neutral; it
exists because most WebDAV clients cannot do the device's mTLS/CN dance
themselves.

* Windows — feed it to WebClient (``net use`` / Explorer); see
  ``scripts/挂载NAS为N盘.ps1``.
* Linux — feed it to ``davfs2`` (``mount -t davfs http://127.0.0.1:8899/ /mnt/n``)
  or to any HTTP-speaking client. The CLI/MCP do **not** need the proxy.
"""

from __future__ import annotations

import base64
import http.client
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlsplit

from . import config as _mconf

UP_HOST = ""
UP_PORT = 5000
UP_USER = ""
UP_PASS = ""
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8899
UP_CN = ""
TOKEN = ""
_ctx: ssl.SSLContext | None = None


def _init() -> None:
    global UP_HOST, UP_PORT, UP_USER, UP_PASS, LISTEN_HOST, LISTEN_PORT, UP_CN, TOKEN, _ctx
    from .cli import client_ctx, resolve_server_cn

    cfg = _mconf.apply_env()
    UP_HOST = cfg["host"]
    UP_PORT = int(cfg["port"])
    UP_USER = os.environ.get("MINAS_USER", "")
    UP_PASS = os.environ.get("MINAS_PASS", "")
    LISTEN_HOST = cfg.get("proxy", {}).get("listen_host", "127.0.0.1")
    LISTEN_PORT = int(cfg.get("proxy", {}).get("listen_port", 8899))
    UP_CN = cfg.get("cn") or os.environ.get("MINAS_CN", "")
    if not UP_CN:
        # Host/SNI must be the device CN — probe the server cert like the CLI does.
        UP_CN = resolve_server_cn(UP_HOST, UP_PORT)
        os.environ["MINAS_CN"] = UP_CN
    TOKEN = base64.b64encode(f"{UP_USER}:{UP_PASS}".encode()).decode()
    # Present the client cert when it exists (needed by the LuCI pool API, not
    # by WebDAV itself — measured 2026-11-01).
    _ctx = client_ctx()


HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
    "host",
}


def ascii_path(path: str) -> str:
    """Keep already-encoded paths; encode raw non-ascii for upstream."""
    try:
        path.encode("ascii")
        return path
    except UnicodeEncodeError:
        parts = path.split("/")
        return "/".join(quote(p, safe="") if p else p for p in parts)


def sanitize_target(raw: str) -> str:
    """Validate a client request-target and return it unchanged when safe.

    Only *origin-form* targets (``/path?query``) are accepted. A client can send
    an absolute-form target (``GET http://evil/x HTTP/1.1``), a network-path
    reference (``//evil/x``) or inject CR/LF; forwarding any of those upstream
    would let a local caller steer the request line sent to the device (CodeQL
    ``py/partial-ssrf``). The upstream host/port stay fixed either way.
    """
    if not raw:
        raise ValueError("empty request target")
    if any(ch in raw for ch in ("\r", "\n", "\x00", " ", "\t")):
        raise ValueError("control character or whitespace in request target")
    if not raw.startswith("/"):
        raise ValueError("only origin-form request targets are supported")
    if raw.startswith("//"):
        raise ValueError("network-path references are not allowed")
    return raw


def rewrite_destination(value: str) -> str:
    """Reduce a client ``Destination`` header to the path-only form the device wants.

    WebDAV clients (Explorer, davfs2) send an absolute URL such as
    ``http://127.0.0.1:8899/a/b``; the device rejects a URL in ``Destination``
    (400) and only accepts a percent-encoded path. Without this rewrite a
    MOVE/COPY through the proxy fails.
    """
    raw = value.strip()
    if "://" in raw:
        raw = urlsplit(raw).path or "/"
    elif raw.startswith("//"):
        raw = "/" + raw.lstrip("/")
    if not raw.startswith("/"):
        raw = "/" + raw
    return ascii_path(sanitize_target(raw))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
        sys.stderr.flush()

    def _bad_request(self, message: str) -> None:
        body = message.encode("utf-8", "replace")
        self.close_connection = True
        self.send_response(400)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        try:
            up_path = ascii_path(sanitize_target(self.path))
        except ValueError as exc:
            self._bad_request(str(exc))
            return
        conn = http.client.HTTPSConnection(UP_HOST, UP_PORT, context=_ctx, timeout=120)
        headers = {}
        for k, v in self.headers.items():
            if k.lower() in HOP:
                continue
            if k.lower() == "destination" and method in ("MOVE", "COPY"):
                headers[k] = rewrite_destination(v)
                continue
            headers[k] = v
        headers["Authorization"] = "Basic " + TOKEN
        headers["Host"] = UP_CN
        headers["Connection"] = "close"
        if body:
            headers["Content-Length"] = str(len(body))
        try:
            conn.request(method, up_path, body=body if body else None, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            status = resp.status
            # Windows WebClient prefers 200 over 204 for DELETE/LOCK
            if method in ("DELETE", "MKCOL", "UNLOCK") and status == 204:
                status = 200
            self.close_connection = True
            self.send_response(status, resp.reason if status != 200 else "OK")
            skip = set(HOP)
            for k, v in resp.getheaders():
                if k.lower() in skip:
                    continue
                self.send_header(k, v)
            # HEAD must not carry a body; Content-Length must match what we write.
            out = b"" if method == "HEAD" else data
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Connection", "close")
            self.send_header("MS-Author-Via", "DAV")
            self.end_headers()
            if out:
                self.wfile.write(out)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}".encode()
            self.close_connection = True
            self.send_response(502)
            self.send_header("Content-Length", str(len(msg)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(msg)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def do_GET(self):
        self._proxy("GET")

    def do_HEAD(self):
        self._proxy("HEAD")

    def do_PUT(self):
        self._proxy("PUT")

    def do_POST(self):
        self._proxy("POST")

    def do_DELETE(self):
        self._proxy("DELETE")

    def do_OPTIONS(self):
        self._proxy("OPTIONS")

    def do_PROPFIND(self):
        self._proxy("PROPFIND")

    def do_PROPPATCH(self):
        self._proxy("PROPPATCH")

    def do_MKCOL(self):
        self._proxy("MKCOL")

    def do_COPY(self):
        self._proxy("COPY")

    def do_MOVE(self):
        self._proxy("MOVE")

    def do_LOCK(self):
        self._proxy("LOCK")

    def do_UNLOCK(self):
        self._proxy("UNLOCK")


def run(argv: list[str] | None = None) -> int:
    """Start the loopback reverse proxy.

    ``argv`` exists for symmetry with the other entry points, because
    ``__main__.py`` dispatches ``python -m minas_webdav proxy ...`` with the
    remaining arguments. (It used to take no parameter, so ``-m ... proxy``
    died with ``TypeError: run() takes 0 positional arguments``.) Settings come
    from ``minas_config.json`` / environment, so extra arguments are reported
    and ignored rather than silently swallowed. The ``minas-webdav-proxy``
    console script calls this with no arguments.
    """
    if argv:
        print(
            f"proxy: ignoring extra arguments {argv!r}; "
            "configure via minas_config.json (proxy.listen_host/listen_port) or env",
            file=sys.stderr,
        )
    _init()
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    httpd.daemon_threads = True
    print(f"proxy http://{LISTEN_HOST}:{LISTEN_PORT} -> https://{UP_HOST}:{UP_PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())
