# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for:

- credential leakage (`credentials.env`, WebDAV basic auth, mTLS certs)
- path traversal / data-root sandbox escapes
- local privilege issues in the reverse proxy (e.g. unexpected bind exposure)
- anything that would expose another user's NAS data

Instead, use GitHub **Private vulnerability reporting** on this repository
(Security → Report a vulnerability), or contact the maintainer privately.

Include a minimal reproduction (redact device CN, IPs, usernames, passwords)
and the impact you observed. You should receive an acknowledgement within a
few days.

## Non-vulnerability reports

For ordinary bugs (CLI output, docs, Windows quirks), a public issue is fine.

## Hard rules in this project

- Credentials live **outside** the repo
  (`%LOCALAPPDATA%\minasCred\credentials.env`); never commit them.
- Device CN / `minas_config.json` is local-only (gitignored).
- Remote paths must stay under the data root (`ensure_data_path`).
- Destructive operations (`rm -r`, bulk moves) require explicit user consent;
  MCP `nas_rm(recursive=True)` demands `confirm=true`.
- The local proxy binds `127.0.0.1` only; do not weaken that default.
- No passwords in process argv, logs, or error strings.
