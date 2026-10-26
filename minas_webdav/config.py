"""Central config loader for minas-webdav.

Non-secret settings (host/port/cn/certs): ``minas_config.json`` next to this
file (gitignored; see ``minas_config.example.json``). Override with
``MINAS_CONFIG``.

Secrets: ``credentials.env`` OUTSIDE any repo. Default location is
platform-dependent (see :func:`default_cred_path`):

* Windows — ``%LOCALAPPDATA%\\minasCred\\credentials.env``
* Linux/macOS — ``$DSH_HOME/minasCred/credentials.env``, else
  ``~/.dsh/minasCred/credentials.env``

The file holds two lines::

    MINAS_USER=...
    MINAS_PASS=...

Same rule for the mTLS certificates (``cert_home``): on Windows the official
client writes them to ``%LOCALAPPDATA%\\minasCert``; elsewhere point
``cert_home`` / ``MINAS_CERT_HOME`` at wherever you copied them.

Environment variables already set always win (setdefault semantics).
"""
from __future__ import annotations

import json
import os
import re
import ssl
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def unverified_ctx() -> ssl.SSLContext:
    """TLS context that accepts the device's self-signed certificate.

    Public API only — ``ssl._create_unverified_context`` is private and has
    changed between Python releases.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

# ``%NAME%`` style variables are expanded by os.path.expandvars on Windows only.
# Do it ourselves so a Windows-flavoured config still resolves on POSIX.
_PCT_VAR = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


def _expand(value: str) -> str:
    """Expand ``~``, ``$VAR`` and ``%VAR%`` (any platform)."""
    value = _PCT_VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    return os.path.expandvars(os.path.expanduser(value))


def platform_home() -> Path:
    """Base directory for local minas data.

    Windows: ``%LOCALAPPDATA%`` (falling back to the conventional path).
    POSIX:   ``$DSH_HOME`` when set, otherwise ``~/.dsh``.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) if base else Path.home() / "AppData" / "Local"
    base = os.environ.get("DSH_HOME")
    return Path(base) if base else Path.home() / ".dsh"


def default_cert_home() -> Path:
    """Where the mTLS certificates (cert / private_key / ca_chain) live."""
    env = os.environ.get("MINAS_CERT_HOME")
    if env:
        return Path(_expand(env))
    return platform_home() / "minasCert"


def default_cred_path() -> Path:
    """Where ``credentials.env`` lives. ``MINAS_CRED_FILE`` wins if set."""
    env = os.environ.get("MINAS_CRED_FILE")
    if env:
        return Path(_expand(env))
    return platform_home() / "minasCred" / "credentials.env"


CONFIG_PATH = Path(
    _expand(os.environ["MINAS_CONFIG"])
    if os.environ.get("MINAS_CONFIG")
    else PACKAGE_DIR / "minas_config.json"
)
CRED_PATH = default_cred_path()

_DEFAULTS = {
    "host": "192.168.1.100",
    "port": 5000,
    "cn": "",
    "data_root": "/pool0/data",
    "cert_home": str(default_cert_home()),
    "proxy": {"listen_host": "127.0.0.1", "listen_port": 8899},
}


def load_config() -> dict:
    cfg = dict(_DEFAULTS)
    if CONFIG_PATH.is_file():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def load_credentials() -> tuple[str, str]:
    user = os.environ.get("MINAS_USER", "")
    password = os.environ.get("MINAS_PASS", "")
    if user and password:
        return user, password
    if CRED_PATH.is_file():
        for line in CRED_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key == "MINAS_USER" and not user:
                user = val
            elif key == "MINAS_PASS" and not password:
                password = val
    return user, password


def apply_env() -> dict:
    """Push config + credentials into os.environ (setdefault) and return config."""
    cfg = load_config()
    user, password = load_credentials()
    os.environ.setdefault("MINAS_IP", str(cfg["host"]))
    os.environ.setdefault("MINAS_PORT", str(cfg["port"]))
    os.environ.setdefault("MINAS_CN", str(cfg.get("cn") or ""))
    cert_home = _expand(str(cfg.get("cert_home") or "")) or str(default_cert_home())
    os.environ.setdefault("MINAS_CERT_HOME", cert_home)
    os.environ.setdefault("MINAS_DATA_ROOT", str(cfg.get("data_root", "/pool0/data")))
    if user:
        os.environ.setdefault("MINAS_USER", user)
    if password:
        os.environ.setdefault("MINAS_PASS", password)
    return cfg


def describe_env() -> str:
    """One-line summary used by error hints (never prints secrets)."""
    user, password = load_credentials()
    return (
        f"cert_home={default_cert_home()} (exists={default_cert_home().exists()}); "
        f"credentials={CRED_PATH} (exists={CRED_PATH.is_file()}); "
        f"user={'set' if user else 'MISSING'}; pass={'set' if password else 'MISSING'}"
    )
