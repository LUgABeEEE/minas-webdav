# SPDX-License-Identifier: Apache-2.0
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
from typing import Iterator
from urllib.parse import quote, urlsplit

from . import config as _mconf

# Bodies are pumped in fixed-size slices: a 4 GB PUT through a mounted drive must
# not turn into 4 GB of resident memory.
CHUNK_SIZE = 64 * 1024
LAST_CHUNK = b"0\r\n\r\n"


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

# Headers the proxy consumes or re-frames itself: forwarding them verbatim would
# either double the framing (transfer-encoding) or leave the client waiting for a
# 100-continue the device never sees (expect).
DROP = HOP | {"expect"}


class ChunkedError(ValueError):
    """Malformed ``Transfer-Encoding: chunked`` framing from the client."""


def iter_chunked(readline, read) -> Iterator[bytes]:
    """Decode a chunked body, yielding payload slices as they arrive.

    ``readline(n)`` returns one header line and ``read(n)`` up to n payload
    bytes (``io.BytesIO`` in the tests, ``rfile`` in the handler). Framing
    errors raise :class:`ChunkedError` so the handler can answer 400 instead of
    forwarding a silently truncated upload.
    """
    while True:
        line = readline(65536)
        if not line:
            raise ChunkedError("truncated chunk header")
        size_field = line.split(b";")[0].strip()
        try:
            size = int(size_field, 16)
        except ValueError as exc:
            raise ChunkedError(f"bad chunk size {size_field!r}") from exc
        if size == 0:
            while True:  # optional trailers, then the blank line
                trailer = readline(65536)
                if trailer in (b"\r\n", b"\n", b""):
                    return
        remaining = size
        while remaining:
            data = read(min(remaining, CHUNK_SIZE))
            if not data:
                raise ChunkedError("truncated chunk payload")
            remaining -= len(data)
            yield data
        if read(2) not in (b"\r\n", b"\n"):
            raise ChunkedError("missing CRLF after chunk")


def iter_exact(read, total: int) -> Iterator[bytes]:
    """Yield exactly ``total`` bytes, a slice at a time."""
    remaining = total
    while remaining:
        data = read(min(remaining, CHUNK_SIZE))
        if not data:
            raise ChunkedError("client closed before sending the declared body")
        remaining -= len(data)
        yield data


def request_body(headers, rfile) -> tuple[Iterator[bytes] | None, int | None]:
    """Work out how to pump the request body; return (slices, length).

    ``length`` is ``None`` for chunked input (the proxy re-frames it for the
    device) and the requested body is ``None`` when there is none. Raises
    ValueError on framing the proxy cannot honour.
    """
    if "chunked" in (headers.get("Transfer-Encoding") or "").lower():
        return iter_chunked(rfile.readline, rfile.read), None
    raw = headers.get("Content-Length")
    if raw is None:
        return None, None
    try:
        length = int(raw)
    except ValueError as exc:
        raise ValueError(f"bad Content-Length {raw!r}") from exc
    if length < 0:
        raise ValueError("negative Content-Length")
    if length == 0:
        return None, 0
    return iter_exact(rfile.read, length), length


def chunk_frame(data: bytes) -> bytes:
    """Wrap one slice in HTTP/1.1 chunked framing."""
    return b"%x\r\n%s\r\n" % (len(data), data)


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
        try:
            up_path = ascii_path(sanitize_target(self.path))
        except ValueError as exc:
            self._bad_request(str(exc))
            return
        expect = "100-continue" in (self.headers.get("Expect") or "").lower()
        try:
            body_slices, body_len = request_body(self.headers, self.rfile)
        except (ValueError, ChunkedError) as exc:
            self._bad_request(str(exc))
            return
        if expect and body_slices is not None:
            # The client holds the body until it sees this; the device never has
            # to deal with Expect, so the header is dropped below.
            self.wfile.write(b"HTTP/1.1 100 Continue\r\n\r\n")
            self.wfile.flush()
        conn = http.client.HTTPSConnection(UP_HOST, UP_PORT, context=_ctx, timeout=120)
        headers_sent = False
        headers = {}
        for k, v in self.headers.items():
            if k.lower() in DROP:
                continue
            if k.lower() == "destination" and method in ("MOVE", "COPY"):
                headers[k] = rewrite_destination(v)
                continue
            headers[k] = v
        headers["Authorization"] = "Basic " + TOKEN
        headers["Host"] = UP_CN
        headers["Connection"] = "close"
        try:
            # Explicit framing: putrequest + putheader + a manual pump means the
            # body is never materialised, while the device still gets a clean
            # Content-Length (or chunked, when the client used chunked).
            conn.putrequest(method, up_path, skip_host=True, skip_accept_encoding=True)
            for k, v in headers.items():
                conn.putheader(k, v)
            if body_slices is not None:
                if body_len is None:
                    conn.putheader("Transfer-Encoding", "chunked")
                else:
                    conn.putheader("Content-Length", str(body_len))
            conn.endheaders()
            if body_slices is not None:
                for piece in body_slices:
                    conn.send(chunk_frame(piece) if body_len is None else piece)
                if body_len is None:
                    conn.send(LAST_CHUNK)
            resp = conn.getresponse()
            status = resp.status
            # Windows WebClient prefers 200 over 204 for DELETE/LOCK
            if method in ("DELETE", "MKCOL", "UNLOCK") and status == 204:
                status = 200
            self.close_connection = True
            self.send_response(status, resp.reason if status != 200 else "OK")
            up_len = resp.getheader("Content-Length")
            up_chunked = "chunked" in (resp.getheader("Transfer-Encoding") or "").lower()
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in HOP and lk not in ("content-length", "transfer-encoding"):
                    continue
                if lk in ("content-length", "transfer-encoding"):
                    continue  # re-emitted below, framed for this hop
                self.send_header(k, v)
            bodyless = method == "HEAD" or status in (204, 304)
            if bodyless:
                if method == "HEAD" and up_len is not None:
                    self.send_header("Content-Length", up_len)
            elif up_len is not None and not up_chunked:
                self.send_header("Content-Length", up_len)
            else:
                self.send_header("Transfer-Encoding", "chunked")
            self.send_header("Connection", "close")
            self.send_header("MS-Author-Via", "DAV")
            self.end_headers()
            headers_sent = True
            if not bodyless:
                chunked_out = up_len is None or up_chunked
                while True:
                    data = resp.read(CHUNK_SIZE)
                    if not data:
                        break
                    self.wfile.write(chunk_frame(data) if chunked_out else data)
                if chunked_out:
                    self.wfile.write(LAST_CHUNK)
        except Exception as e:
            # Headers may already be on the wire, so the only honest signal left
            # is to abort the connection instead of appending a 502 body.
            msg = f"{type(e).__name__}: {e}".encode()
            self.close_connection = True
            if headers_sent:
                try:
                    self.wfile.write(msg)
                except OSError:
                    pass
            else:
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
