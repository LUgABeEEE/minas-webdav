#!/usr/bin/env bash
# =============================================================================
# minas-cert-refresh.sh — keep the MINAS WebDAV mTLS certificate fresh on Linux
#
# Why this exists:
#   The device answers 451 to requests without a client certificate. The
#   certificate is issued by the official Xiaomi Smart Storage desktop client,
#   lives only on the machine running that client, and expires in ~21 days.
#   A Linux box can therefore never renew it by itself — it can only *collect*
#   a bundle produced elsewhere, verify it, install it and nag a human.
#
# What it does:
#   1. report the remaining lifetime of the installed certificate
#   2. when a bundle (minas-cred-<stamp>/) appears in the staging directory,
#      verify it against its manifest.json and install it atomically
#   3. verify the result against the live device, then remove the bundle
#   4. notify through a caller-supplied command when a human has to act
#
# Design notes (Linux-first on purpose):
#   * POSIX shell + python3 (stdlib) + openssl only — no third-party packages,
#     no PowerShell, no SMB client, no notification backend baked in.
#   * The staging directory is whatever you can read: a mounted CIFS share, an
#     NFS mount, a synced folder, a USB stick. This script never authenticates
#     to the NAS itself, so it needs no credentials of its own.
#   * Certificate parsing prefers `openssl`; when it is missing the script falls
#     back to the `cryptography` module if it happens to be installed.
#
# Usage:
#   minas-cert-refresh.sh [--check|--auto] [--json] [--quiet] [--no-notify]
#                         [--stage-dir DIR] [--cert-home DIR] [--warn-days N]
#                         [--notify CMD] [--no-verify] [--test-notify]
#
#     --check        inspect only (default)
#     --auto         install the newest bundle if it differs from what is installed
#     --json         print one machine-readable JSON line in addition to the report
#     --quiet        do not print the human report (errors still go to stderr)
#     --no-notify    never run the notification command
#     --stage-dir    directory where bundles appear (default: $MINAS_STAGE_DIR)
#     --cert-home    certificate directory (default: $MINAS_CERT_HOME)
#     --warn-days    warn when the certificate has fewer days left (default 7)
#     --notify       command to run on alert; receives the text as $1 and stdin
#     --no-verify    skip the post-install live check (not recommended)
#     --test-notify  send one test notification and exit
#     -h, --help     this text
#
# Exit codes: 0 healthy/refreshed · 10 expiring · 11 expired/missing ·
#             12 refresh failed · 1 usage/internal error
#
# Environment (all optional):
#   MINAS_STAGE_DIR         staging directory holding minas-cred-* bundles
#   MINAS_STAGE_MOUNT_SRC   e.g. //nas.lan/backup — resolves the mount point
#                           from /proc/mounts when MINAS_STAGE_DIR is unset
#   MINAS_CERT_HOME         default: ${DSH_HOME:-~/.dsh}/minasCert
#   MINAS_CRED_HOME         default: ${DSH_HOME:-~/.dsh}/minasCred
#   MINAS_STATUS_FILE       default: $MINAS_CRED_HOME/status.json
#   MINAS_CERT_WARN_DAYS    default: 7
#   MINAS_NOTIFY_CMD        default: unset (print only)
#   MINAS_PYTHON            default: python3
#   MINAS_WEBDAV_HOME       repository root used for the live check
#                           default: parent of this script's directory
#   MINAS_VERIFY_CMD        override the live check entirely
# =============================================================================
set -uo pipefail

MODE="check"
JSON=0
NOTIFY=1
QUIET=0
TEST_NOTIFY=0
VERIFY=1

DSH_HOME="${DSH_HOME:-$HOME/.dsh}"
CERT_HOME="${MINAS_CERT_HOME:-$DSH_HOME/minasCert}"
CRED_HOME="${MINAS_CRED_HOME:-$DSH_HOME/minasCred}"
STATUS_FILE="${MINAS_STATUS_FILE:-$CRED_HOME/status.json}"
STAGE_DIR="${MINAS_STAGE_DIR:-}"
MOUNT_SRC="${MINAS_STAGE_MOUNT_SRC:-}"
WARN_DAYS="${MINAS_CERT_WARN_DAYS:-7}"
NOTIFY_CMD="${MINAS_NOTIFY_CMD:-}"
PY="${MINAS_PYTHON:-python3}"

while [ $# -gt 0 ]; do
  case "$1" in
    --check)       MODE="check" ;;
    --auto)        MODE="auto" ;;
    --json)        JSON=1 ;;
    --quiet)       QUIET=1 ;;
    --no-notify)   NOTIFY=0 ;;
    --no-verify)   VERIFY=0 ;;
    --test-notify) TEST_NOTIFY=1 ;;
    --stage-dir)   [ $# -ge 2 ] || { echo "--stage-dir needs a value" >&2; exit 1; }; STAGE_DIR="$2"; shift ;;
    --cert-home)   [ $# -ge 2 ] || { echo "--cert-home needs a value" >&2; exit 1; }; CERT_HOME="$2"; shift ;;
    --warn-days)   [ $# -ge 2 ] || { echo "--warn-days needs a value" >&2; exit 1; }; WARN_DAYS="$2"; shift ;;
    --notify)      [ $# -ge 2 ] || { echo "--notify needs a value" >&2; exit 1; }; NOTIFY_CMD="$2"; shift ;;
    -h|--help)     sed -n '2,70p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1 (try --help)" >&2; exit 1 ;;
  esac
  shift
done

case "$WARN_DAYS" in ''|*[!0-9]*) echo "--warn-days must be a positive integer" >&2; exit 1 ;; esac

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TOOL_HOME="${MINAS_WEBDAV_HOME:-$(dirname -- "$HERE")}"
VERIFY_CMD="${MINAS_VERIFY_CMD:-}"

say() { [ "$QUIET" -eq 1 ] || printf '%s\n' "$*"; }
log() { printf '%s %s\n' "$(date -Is)" "$*"; }
warn() { printf '%s %s\n' "$(date -Is)" "$*" >&2; }

# --------------------------------------------------------------- notification

notify() {
  # Hand the text to the caller's command. We deliberately ship no backend:
  # mail, Matrix, Telegram, ntfy, a webhook — that is a local policy decision.
  [ "$NOTIFY" -eq 1 ] || return 0
  local msg="$1"
  if [ -z "$NOTIFY_CMD" ]; then
    say "(no notification command configured; set MINAS_NOTIFY_CMD to enable alerts)"
    return 0
  fi
  local out rc
  out=$(printf '%s\n' "$msg" | sh -c "$NOTIFY_CMD" -- "$msg" 2>&1)
  rc=$?
  if [ "$rc" -eq 0 ]; then
    log "notify: ${out:-ok}"
  else
    warn "notify: command failed (rc=$rc): ${out:-no output}"
  fi
  return 0
}

# -------------------------------------------------------------- certificate

cert_file() {
  # Newest *_cert.pem in the certificate directory (the client rotates names)
  ls -1t "$CERT_HOME"/*_cert.pem 2>/dev/null | head -1
}

_cert_meta_python() {
  # Fallback when openssl is absent: print "<days_left> <expiry-YYYY-MM-DD>"
  "$PY" - "$CERT_HOME" <<'PY' 2>/dev/null || echo "-1 "
import datetime, sys
from pathlib import Path
try:
    from cryptography import x509
except Exception:
    print("-1 ")
    raise SystemExit
certs = sorted(Path(sys.argv[1]).glob("*_cert.pem"),
               key=lambda p: p.stat().st_mtime, reverse=True)
if not certs:
    print("-1 ")
    raise SystemExit
c = x509.load_pem_x509_certificate(certs[0].read_bytes())
na = getattr(c, "not_valid_after_utc", None) or c.not_valid_after.replace(
    tzinfo=datetime.timezone.utc)
left = int((na - datetime.datetime.now(datetime.timezone.utc)).total_seconds() // 86400)
print(f"{left} {na.astimezone().strftime('%Y-%m-%d')}")
PY
}

cert_meta() {
  # Print "<days_left> <expiry-YYYY-MM-DD>"; days_left is -1 when unknown.
  local f end epoch now
  f=$(cert_file)
  if [ -z "$f" ]; then
    printf '%s\n' "-1 "
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    end=$(openssl x509 -in "$f" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')
    if [ -n "$end" ]; then
      epoch=$(date -u -d "$end" +%s 2>/dev/null) || epoch=""
      if [ -n "$epoch" ]; then
        now=$(date -u +%s)
        printf '%s %s\n' "$(( (epoch - now) / 86400 ))" "$(date -u -d "$end" +%F)"
        return 0
      fi
    fi
  fi
  _cert_meta_python
}

cert_fingerprint() {
  local f
  f=$(cert_file)
  [ -n "$f" ] && sha256sum "$f" 2>/dev/null | awk '{print $1}'
}

# --------------------------------------------------------------- staging area

resolve_stage() {
  # Sets STAGE_DIR when it can be worked out; returns 1 when unknown.
  if [ -n "$STAGE_DIR" ]; then
    [ -d "$STAGE_DIR" ] && return 0
    warn "staging directory not found: $STAGE_DIR"
    return 1
  fi
  if [ -n "$MOUNT_SRC" ]; then
    local mp
    mp=$(awk -v src="$MOUNT_SRC" '$1 == src { print $2; exit }' /proc/mounts 2>/dev/null)
    if [ -n "$mp" ] && [ -d "$mp" ]; then
      STAGE_DIR="$mp"
      return 0
    fi
    warn "MINAS_STAGE_MOUNT_SRC=$MOUNT_SRC is not mounted"
  fi
  return 1
}

list_bundles() {
  # Newest first; only names that look like ours.
  resolve_stage || return 0
  find "$STAGE_DIR" -mindepth 1 -maxdepth 1 -type d -name 'minas-cred-*' \
       -printf '%f\n' 2>/dev/null | sort -r
}

bundle_valid_name() {
  case "${1:-}" in
    minas-cred-*) ;;
    *) warn "refusing to touch unexpected directory name: ${1:-<empty>}"; return 1 ;;
  esac
}

# --------------------------------------------------------------- bundle ops

validate_bundle() {
  # Verify manifest.json against the files actually present. Never installs.
  "$PY" - "$1" <<'PY'
import hashlib, json, os, sys

root = sys.argv[1]
man_path = os.path.join(root, "manifest.json")
if not os.path.isfile(man_path):
    print("manifest.json missing")
    raise SystemExit(1)
try:
    with open(man_path, encoding="utf-8") as fh:
        man = json.load(fh)
except Exception as exc:                     # noqa: BLE001 — report, never install
    print(f"manifest.json unreadable: {exc}")
    raise SystemExit(1)

files = man.get("files") or []
if not files:
    print("manifest.json lists no files")
    raise SystemExit(1)

for entry in files:
    name = entry.get("name") or ""
    if not name or os.path.basename(name) != name or name in (".", ".."):
        print(f"unsafe file name in manifest: {name!r}")
        raise SystemExit(1)
    path = os.path.join(root, name)
    if not os.path.isfile(path):
        print(f"missing file: {name}")
        raise SystemExit(1)
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != (entry.get("sha256") or ""):
        print(f"sha256 mismatch: {name}")
        raise SystemExit(1)
print("ok")
PY
}

bundle_cert_sha() {
  # sha256 of the certificate recorded in the bundle manifest (no install).
  "$PY" - "$1/manifest.json" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        man = json.load(fh)
except Exception:
    raise SystemExit(0)
for entry in man.get("files") or []:
    if (entry.get("kind") or "") == "cert":
        print(entry.get("sha256") or "")
        break
PY
}

remove_bundle() {
  local bundle="$1" path
  bundle_valid_name "$bundle" || return 1
  path="$STAGE_DIR/$bundle"
  [ -f "$path/manifest.json" ] || { warn "refusing to remove $bundle (no manifest.json)"; return 1; }
  rm -rf -- "$path" 2>/dev/null
}

install_bundle() {
  # copy → validate → install (0600) → live check → clean up. Never leaves a
  # half-installed certificate behind: on any failure the bundle is kept.
  local bundle="$1" tmp rc=0 f installed=0 vout
  bundle_valid_name "$bundle" || return 1
  resolve_stage || { warn "no staging directory; cannot install"; return 1; }

  tmp=$(mktemp -d "${TMPDIR:-/tmp}/minas-cert.XXXXXX") || return 1
  chmod 700 "$tmp" 2>/dev/null || true
  log "INSTALL start: $bundle"

  for f in "$STAGE_DIR/$bundle"/*; do
    [ -f "$f" ] || continue
    case "$(basename "$f")" in
      *.pem|credentials.env|manifest.json)
        cp -a -- "$f" "$tmp/" || { warn "copy failed: $(basename "$f")"; rm -rf "$tmp"; return 1; } ;;
    esac
  done

  if ! vout=$(validate_bundle "$tmp" 2>&1); then
    warn "bundle rejected by manifest validation: $vout"
    rm -rf "$tmp"
    return 1
  fi

  mkdir -p "$CERT_HOME" "$CRED_HOME" 2>/dev/null
  chmod 700 "$CERT_HOME" "$CRED_HOME" 2>/dev/null || true

  for f in "$tmp"/*_cert.pem "$tmp"/*_private_key.pem "$tmp"/ca_chain.pem; do
    [ -f "$f" ] || continue
    if [ -e "$CERT_HOME/$(basename "$f")" ]; then
      cp -a -- "$CERT_HOME/$(basename "$f")" \
             "$CERT_HOME/$(basename "$f").bak-$(date +%Y%m%d%H%M%S)"
    fi
    install -m 600 -- "$f" "$CERT_HOME/$(basename "$f")" || rc=1
    installed=$((installed + 1))
  done

  if [ -f "$tmp/credentials.env" ]; then
    if [ -e "$CRED_HOME/credentials.env" ]; then
      cp -a -- "$CRED_HOME/credentials.env" \
             "$CRED_HOME/credentials.env.bak-$(date +%Y%m%d%H%M%S)"
    fi
    install -m 600 -- "$tmp/credentials.env" "$CRED_HOME/credentials.env" || rc=1
  fi

  if [ "$installed" -lt 3 ]; then
    warn "bundle does not contain the full triple (cert / key / ca_chain); installed=$installed"
    rm -rf "$tmp"
    return 1
  fi
  if [ "$rc" -ne 0 ]; then
    warn "installing the certificate files failed"
    rm -rf "$tmp"
    return 1
  fi

  if [ "$VERIFY" -eq 1 ]; then
    local vrc
    if [ -n "$VERIFY_CMD" ]; then
      vout=$(cd "$TOOL_HOME" && sh -c "$VERIFY_CMD" 2>&1); vrc=$?
    else
      vout=$(cd "$TOOL_HOME" && timeout 90 "$PY" -m minas_webdav ls /pool0/data 2>&1); vrc=$?
    fi
    if [ "$vrc" -ne 0 ]; then
      warn "post-install check failed; bundle kept for inspection"
      printf '%s\n' "$vout" | tail -5 >&2
      rm -rf "$tmp"
      return 1
    fi
  fi

  # Shred the temporary copies: they held a private key.
  find "$tmp" -name '*.pem' -exec shred -u {} + 2>/dev/null || rm -f "$tmp"/*.pem 2>/dev/null
  rm -rf "$tmp"

  if remove_bundle "$bundle"; then
    log "OK bundle removed from staging: $bundle"
  else
    warn "could not remove bundle from staging; delete it by hand: $bundle"
  fi
  log "OK installed: $bundle"
  return 0
}

# ------------------------------------------------------------------- main

if [ "$TEST_NOTIFY" -eq 1 ]; then
  set -- $(cert_meta)
  say "sending one test notification (days_left=$1)…"
  notify "minas-cert-refresh: test notification from $(hostname 2>/dev/null || echo host); certificate has $1 day(s) left"
  exit 0
fi

read -r DAYS EXPIRY <<EOF
$(cert_meta)
EOF
FP=$(cert_fingerprint)
BUNDLES=$(list_bundles 2>/dev/null || true)
NEWEST=$(printf '%s\n' "$BUNDLES" | grep -v '^$' | head -1 || true)

STATE="ok"
MSG=""
RC=0

if [ "$DAYS" -lt 0 ] && [ -z "$FP" ]; then
  STATE="missing"
  MSG="minas certificate not found: install a bundle produced by the official client"
  RC=11
elif [ "$DAYS" -le 0 ]; then
  STATE="expired"
  MSG="minas certificate expired on ${EXPIRY:-an unknown date}: install a fresh bundle"
  RC=11
elif [ "$DAYS" -le "$WARN_DAYS" ]; then
  STATE="expiring"
  MSG="minas certificate expires in ${DAYS} day(s) (${EXPIRY:-unknown}): install a fresh bundle"
  RC=10
fi

if [ -z "$BUNDLES" ] && [ "$STATE" != "ok" ] && { [ -n "$STAGE_DIR" ] || [ -n "$MOUNT_SRC" ]; }; then
  say "no bundle waiting in ${STAGE_DIR:-the staging area}"
fi

if [ -n "$NEWEST" ]; then
  SHA=$(bundle_cert_sha "$NEWEST" || true)
  if [ -n "$SHA" ] && [ "$SHA" = "$FP" ]; then
    say "newest bundle is already installed: $NEWEST"
    if [ "$MODE" = "auto" ]; then
      if remove_bundle "$NEWEST"; then
        log "OK removed redundant bundle: $NEWEST"
      else
        warn "could not remove redundant bundle: $NEWEST"
      fi
    fi
  else
    say "found a new bundle: $NEWEST"
    if [ "$MODE" = "auto" ]; then
      if install_bundle "$NEWEST"; then
        read -r DAYS EXPIRY <<EOF
$(cert_meta)
EOF
        STATE="refreshed"
        MSG="minas certificate refreshed (${DAYS} day(s) left)"
        RC=0
      else
        STATE="refresh_failed"
        MSG="minas certificate refresh failed: check the bundle and the logs"
        RC=12
      fi
    else
      say "(--check mode: nothing installed; use --auto to install)"
    fi
  fi
fi

mkdir -p "$CRED_HOME" 2>/dev/null
"$PY" - "$STATUS_FILE" "$STATE" "$DAYS" "$NEWEST" "$RC" "$EXPIRY" <<'PY' 2>/dev/null
import datetime, json, sys

path, state, days, bundle, rc, expires = sys.argv[1:7]
with open(path, "w", encoding="utf-8") as fh:
    json.dump({
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "state": state,
        "days_left": int(days),
        "expires_on": expires or None,
        "staged_bundle": bundle or None,
        "exit_code": int(rc),
    }, fh, ensure_ascii=False, indent=2)
PY

say "state: $STATE  days_left: ${DAYS}  expires_on: ${EXPIRY:-unknown}  newest_bundle: ${NEWEST:-none}"
if [ "$JSON" -eq 1 ]; then
  "$PY" - "$STATE" "$DAYS" "$NEWEST" "$RC" "$EXPIRY" <<'PY'
import json, sys

state, days, bundle, rc, expires = sys.argv[1:6]
print(json.dumps({
    "state": state,
    "days_left": int(days),
    "expires_on": expires or None,
    "bundle": bundle or None,
    "rc": int(rc),
}, ensure_ascii=False))
PY
fi

if [ "$RC" -ge 10 ] && [ -n "$MSG" ]; then
  notify "$MSG"
fi

exit "$RC"
