# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Linux / macOS support.** The CLI, `probe` and `proxy` only use the standard
  library, so they run on POSIX as-is once the certs and credentials are in
  place. Defaults are now platform-aware: `%LOCALAPPDATA%\minasCert` /
  `%LOCALAPPDATA%\minasCred\credentials.env` on Windows,
  `$DSH_HOME/minasCert` / `$DSH_HOME/minasCred/credentials.env` elsewhere
  (falling back to `~/.dsh/…`). `MINAS_CERT_HOME` / `MINAS_CRED_FILE` still win.
- `scripts/minas-webdav`: POSIX wrapper that runs the CLI from the repository
  root with `MIMO_PYTHON` / `PYTHON` (default `python3`).
- `cli._cn_from_der()`: the device CN is derived without Windows-only
  `certutil` — `cryptography` when importable, then the `openssl` CLI, then
  `certutil` as the last resort. This is what previously made POSIX fail even
  with valid certificates.
- `cli.safe_put()`: the device answers a PUT that overwrites an existing
  resource with `204`, keeps the **old** size, and leaves the new head followed
  by the old tail (shorter payloads only). Uploads now go to a temporary name
  and are `MOVE`d into place, then verified by size and (by default) sha256;
  a mismatch is reported as a failure instead of a silent success. Downgrade
  with `MINAS_PUT_VERIFY=size` (skip the download) or `off`.
- `tests/test_safe_put.py`: offline tests pinning the temp-name/`MOVE`/verify
  contract, the `DELETE`+`PUT` fallback and the failure modes.

### Added

- `scripts/minas-cert-refresh.sh`: a Linux-only helper for the mTLS certificate
  this device requires (~21 days, issued only by the official client). It reads
  a staging directory, validates the bundle against its `manifest.json`
  (sha256, no path traversal), installs the triple as `0600` with backups,
  **verifies against the live device**, and only then removes the bundle.
  It ships no notification backend — `MINAS_NOTIFY_CMD` is the hook. Exit codes
  `0/10/11/12` map to healthy / expiring / expired / refresh failed.
- `docs/CERT-REFRESH.md`: the producer contract (bundle layout + manifest),
  configuration reference, a systemd `service` + `timer` example and a
  troubleshooting table.

### Fixed

- `%VAR%` placeholders are expanded on POSIX too: `os.path.expandvars` only
  understands `$VAR`, so the Windows-style defaults turned into a literal
  `%LOCALAPPDATA%\minasCert` directory name and certificates were never
  found.
- `cli.CERT_HOME` no longer degrades to the relative path `minasCert` when
  `LOCALAPPDATA` is unset.
- Missing-cert / missing-credential hints print the paths actually searched plus
  a secret-free environment summary instead of a hard-coded Windows path.
- `minas_config.example.json` no longer pins `cert_home`; the default is derived
  per platform.

## [0.1.4] - 2026-10-26

### Fixed

- `python -m minas_webdav proxy` crashed with
  `TypeError: run() takes 0 positional arguments but 1 was given`
  (the `__main__` dispatcher passed leftover argv). `proxy.run()` now
  accepts an optional `argv`, matching `probe.run()`. Console script
  `minas-webdav-proxy` was unaffected.

### Added

- Smoke tests covering `proxy.run` / `probe.run` entry-point signatures.

### Verified

- Post-firmware-update live check on Xiaomi Smart Storage (2026-10-26):
  WebDAV protocol surface unchanged (`DAV: 1,2`, Basic auth, Depth:infinity
  still 403); CLI / MCP `nas_*` / SMB `minas-skill` / Chinese paths /
  local proxy all healthy.

## [0.1.3] - 2026-10-26

### Fixed

- Local proxy sent `Content-Length: 0` on HTTP 200 while still writing the
  body — GET/PROPFIND downloads through `net use N:` were unreliable.
  Length now matches the bytes written; HEAD never carries a body.
- Path anchoring: `ensure_data_path` rejects `..` and sibling prefixes such
  as `/pool0evil` / `/pool0/data2`; bare names stay under the data root.
- PROPFIND multistatus parser accepts any DAV namespace prefix
  (`<D:response>`, `<d:response>`, …) instead of a hard-coded `<D:>`.
- `nas_find` name wildcards use full-match semantics (same as the CLI).

### Added

- `nas_get` 32MB per-call size cap with a clear CLI fallback hint.
- Offline test suite (`tests/test_paths.py`): path safety, `fnmatch`
  conversion, multistatus parsing.
- `scripts/launch-mcp.cmd` — boots MCP with this repo's venv so the host
  never picks a Python without `mcp` installed.
- Community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  issue / PR templates.

### Changed

- Skill / docs no longer hard-code `F:\Projects\minas-webdav`; use
  `MINAS_WEBDAV_HOME` (fallback documented in `skill/SKILL.md`).
- `dest_header()` dropped an unused parameter.

## [0.1.2] - 2026-10-25

### Added

- Console script `minas-webdav-mcp` (MCP stdio server entry point), so MCP
  clients and connector catalogs can start the server by name instead of
  spelling out `python -m minas_webdav.mcp_server`.
- Documented tested environment, NAS service versions, and compatibility
  notes (`docs/ENVIRONMENT.md`).

## [0.1.1] - 2026-10-25

### Added

- CI on Python 3.10–3.13 plus a build + `twine check` job.
- `tests/test_smoke.py`: package import, version, example config, CLI wiring.
- `release.yml`: tag-triggered build, PyPI Trusted Publishing (OIDC) and a
  GitHub release carrying the wheel and sdist. No API token is stored.
- `docs/RELEASING.md`: the one-time PyPI publisher setup and the per-release steps.
- PyPI metadata: authors, keywords, classifiers and project URLs.
- README: PyPI/CI/licence badges and an install section.
- Apache-2.0 license with `NOTICE`.
- MCP server (`minas_webdav/mcp_server.py`, 14 `nas_*` tools).
- Agent skill package (`skill/`).

### Removed

- Bundled `rclone.zip` (download from upstream if you need rclone).

## [0.1.0] - 2026-10-25

### Added

- First public release: `minas-webdav` CLI (`ls/stat/du/df/get/put/cat/mkdir/rm/
  mv/cp/find/tree`), WebDAV capability probe, local reverse proxy for drive
  mapping, and an MCP server behind the `[mcp]` extra.
- Agent skill under `skill/` and integration notes under `docs/`.

[Unreleased]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/LUgABeEEE/minas-webdav/releases/tag/v0.1.0
