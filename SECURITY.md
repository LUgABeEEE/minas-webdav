# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | yes |
| 0.2.x | security fixes only |
| < 0.2 | no |

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

## Threat model of the local proxy

`proxy.py` listens on loopback and forwards to the device address from
`minas_config.json` / the environment — the upstream host and port are **never**
taken from the request. A caller may address any path on the device (that is the
point of a reverse proxy), so a CodeQL `py/partial-ssrf` finding on the request
line is expected and dismissed; what the proxy does reject is everything that
could change the shape of that request line:

- only origin-form targets (`/path?query`) are accepted — absolute-form
  (`http://host/path`), network-path references (`//host/path`) and CR/LF or
  NUL are answered with `400` (`tests/test_proxy.py` pins this);
- the `Destination` header of `MOVE`/`COPY` is rewritten to a path-only,
  percent-encoded value before it reaches the device;
- `Host`, `Authorization` and `Content-Length` are set by the proxy, not copied
  from the client.

TLS verification against the appliance is intentionally disabled: its chain is
self-signed and trusted explicitly through `ca_chain.pem`, and identity is
pinned by the device CN via `Host`/`SNI`. The protocol floor is TLS 1.2
(`config.unverified_ctx` / `config.verified_ctx`).
