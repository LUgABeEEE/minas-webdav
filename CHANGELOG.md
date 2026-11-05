# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.7] - 2026-11-05

### Fixed

- **Mounting a drive actually works now.** WebDAV clients probe `PROPFIND /` when
  they mount, and the device answers 451 for the bare root, so `net use N:` ended
  in `System error 67` no matter what else worked. The proxy now maps `/` onto
  the data root (`map_to_root`).
- **Zero-length PUT keeps its framing.** WebClient opens a file with
  `Content-Length: 0`; the proxy used to drop the header entirely and the device
  answered 500, so every copy through a mounted drive failed.
- **`PROPPATCH` is answered locally with a 207 echo.** The device returns 405,
  which WebClient treats as fatal: it uploads the file, sees the property update
  fail, deletes it again and reports "the device attached to the system is not
  functioning".
- **`Destination` gets the same root mapping as the request target**, so renaming
  or moving inside a mounted drive no longer ends in a 500.

### Added

- `MINAS_PROXY_DEBUG=1` logs each proxied request with its method, path and
  headers — the only practical way to see what a mounted-drive client sends.
- `scripts/挂载NAS为N盘.ps1` now preflights the WebClient service and
  `BasicAuthLevel`, waits for the proxy port, and mounts `/` (the pool) instead of
  a sub-path.

### Verified

- Against the device through a real `net use N:` mount (Microsoft-WebDAV-MiniRedir
  10.0.26300): 40 MB and 300 MB copies, rename, delete, mkdir — all byte-identical
  hashes afterwards, proxy RSS steady at ~25 MB.
- CLI-style paths keep working: `/pool0/data/...` is passed through untouched.

## [0.3.6] - 2026-11-05

### Fixed

- **The proxy streams instead of buffering.** Request and response bodies are now
  pumped in 64 KiB slices, so copying a 4 GB file through a mounted drive no
  longer turns into 4 GB of resident memory. Verified against the device: a
  3 MB PUT followed by a GET through the proxy returns a byte-identical file
  (sha256).
- **Chunked uploads are no longer silently emptied.** A client sending
  `Transfer-Encoding: chunked` used to hit `Content-Length: 0`, so the device
  stored an empty file without any error. The proxy now decodes the chunks and
  re-frames them upstream; a 3 MB chunked PUT round-trips with an identical
  sha256.
- **`Expect: 100-continue` is answered by the proxy.** Clients used to stall
  until their own timeout while the proxy waited for a body that had not been
  sent; the header is now consumed locally and never forwarded.
- Response framing is re-emitted per hop (`Content-Length` when the device sent
  one, chunked otherwise) instead of buffering the body to compute a length.

### Changed

- CI: `setup-python` caches pip, a `concurrency` group cancels superseded runs,
  and every job has a `timeout-minutes` cap.
- The `dev` extra is bounded (`pytest>=7,<9`, `ruff>=0.6,<0.15`) so an upstream
  release cannot redden CI on a green commit.
- GitHub release bodies now come from the matching `CHANGELOG.md` section, the
  same way `minas-skill` does it, instead of auto-generated notes.
- README gained a command reference table generated from `build_parser()`;
  `tests/test_docs.py` fails when it drifts (`MINAS_UPDATE_DOCS=1` regenerates).
- `pyproject.toml`: explicit 3.10–3.13 classifiers and `Development Status`.

### Removed

- `ls --long`: the flag was declared but never read (it was always true), so it
  only appeared in `--help` to mislead.

## [0.3.5] - 2026-11-05

### Changed

- Copyright holder in `LICENSE`, `NOTICE` (and the `dsh/` copies) is now
  `LUgABeEEE` — the GitHub account name — instead of `g1394`, so the licence
  header and the published packages name the same person as the repository
  owner. The 0.3.0–0.3.4 artifacts keep the old string, since published
  versions cannot be rewritten.

## [0.3.4] - 2026-11-05

### Added

- `dsh/NOTICE` now ships in the npm bundle (`files` gained `NOTICE`). Apache-2.0
  section 4(d) requires the attribution notices to travel with a distributed
  derivative work; the PyPI sdist and wheel already carried `LICENSE` + `NOTICE`.
- CI: a `coverage` job runs the suite under `coverage.py` and fails below 46%
  (measured baseline 47% on the Linux runner, 2026-11-05) — a ratchet, to be
  raised as real tests land.
- CI: a `ci-ok` aggregate job so branch protection can require one stable
  context instead of the interpreter-specific matrix names; `master` now
  requires `ci-ok` on pull requests.

### Changed

- `# SPDX-License-Identifier: Apache-2.0` on every Python module and workflow
  file (was 0/19 modules and 1/5 workflows), so licence scanners and GitHub's
  licence detection agree with the `LICENSE`/`NOTICE` files.
- The `NOTICE` copyright holder is `g1394` in both repositories (`minas-skill`
  said `missfor100`); one holder name keeps future relicensing or transfer
  straightforward.
- `config.verified_ctx()` is now the single place that builds a CA-verified
  device context (TLS 1.2 floor included); `client.py` previously repeated
  `ssl.create_default_context(cafile=ca)` + `check_hostname = False` in three
  places, which is also what kept the remaining `py/insecure-protocol` alerts
  alive.
- `dsh/package.json` is 0.3.4, following the CLI version as documented in
  `dsh/README.md`.

## [0.3.3] - 2026-11-05

### Security

- **TLS floor pinned to 1.2.** `config.unverified_ctx()` built its context with
  `ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)`, which still permits TLS 1.0/1.1 —
  CodeQL `py/insecure-protocol` flagged six call sites. The context now sets
  `minimum_version = TLSVersion.TLSv1_2`. Certificate verification stays off by
  design (the self-signed chain is trusted explicitly via `ca_chain.pem` and the
  identity is pinned by the device CN), and the device runs nginx 1.24, which
  speaks TLS 1.2/1.3.
- `tests/test_tls.py` pins the floor for both `unverified_ctx()` and
  `client_ctx()`.

## [0.3.2] - 2026-11-05

### Added

- `tests/test_proxy.py` (11 cases): request-target sanitising, `Destination`
  rewriting and non-ascii encoding for the loopback proxy.
- CI: `ruff format --check .` next to `ruff check`, so formatting now gates
  merges instead of drifting.

### Fixed

- **Proxy only accepts origin-form request targets.** An absolute-form target
  (`GET http://evil/x`), a network-path reference (`//evil/x`) or CR/LF in the
  path is now answered with `400` instead of being forwarded upstream (CodeQL
  `py/partial-ssrf`). The upstream host/port were always fixed; this closes the
  remaining way to steer the request line.
- **MOVE/COPY through the proxy work again.** `Destination` arrived as an
  absolute URL (`http://127.0.0.1:8899/…`) and the device rejects that with
  `400`; the header is now rewritten to the percent-encoded, path-only form the
  device expects.

### Changed

- Repo-wide `ruff format` pass (whitespace only, no behaviour change).

## [0.3.1] - 2026-11-01

### Fixed

- **Verified against the live device (2026-11-01): the WebDAV endpoint does not
  need the client certificate.** `PROPFIND /pool0/data` on `:5000` returns 207
  with Basic auth alone — also with CA verification disabled — and the `451` is
  the *missing Basic auth* response, not a missing certificate. The client cert
  is only required by the LuCI pool-info API on `:443` (`df` / credential
  discovery), which answers **HTTP 400** without it and 200 with it.
  `docs/webdav-surface.md` (and its skill copy), `docs/CERT-REFRESH.md`,
  `docs/ENVIRONMENT.md`, README, the skill troubleshooting table and the
  `client_ctx` / `proxy` / `probe` comments now state that instead.
- `scripts/minas-cert-refresh.sh`: the post-install live check now runs
  `python3 -m minas_webdav df` — the mTLS-only path. The previous `ls` check
  only proved that Basic auth worked, so a broken or expired certificate would
  have passed verification.

### Changed

- npm bundle `dsh-minas-webdav` bumped to 0.3.1 to track the CLI release
  (bundle content unchanged since 0.1.1) and published from the `dsh-v0.3.1`
  tag.

## [0.3.0] - 2026-11-01

### Added

- `--version` for every entry point: `python -m minas_webdav --version` and the
  `minas-webdav` console script now print the package version.
- `tests/test_commands.py`: offline tests for the command layer against a fake
  client — PROPFIND depth selection, MOVE/COPY `Destination`/`Overwrite`
  headers, DELETE ordering for `rm -r`, temp-name uploads, exit codes and the
  JSON vs text output.
- `tests/test_mcp.py`: pins the 14 `nas_*` MCP tools, their descriptions and the
  `nas_rm` `recursive`/`confirm` contract. Skipped when the `mcp` extra is not
  installed.
- `tests/test_docs.py`: keeps `skill/references/webdav-surface.md` byte-identical
  to `docs/webdav-surface.md`, so the packaged skill copy cannot drift.
- CI: a `windows-latest` leg (Python 3.12/3.13) beside Linux 3.10–3.13, the
  `[mcp]` extra installed so the MCP tests actually run, a `ruff` job and a
  `pip-audit` job. New `.github/workflows/codeql.yml` (push, PR, weekly).
- Packaging: `[project.optional-dependencies] posix = ["cryptography>=42"]` for
  the certutil-free CN derivation, and `dev` now carries `ruff`.
- `[tool.ruff]` configuration (line-length 120, rules `E,F,W,I,B`).

### Changed

- `cli.py` (964 lines) split into `client.py` (transport, TLS/mTLS, CN
  discovery), `commands.py` (one `cmd_*` per subcommand), `davxml.py`
  (multistatus parsing) and `paths.py` (path sandbox, formatting, wildcards).
  `minas_webdav.cli` keeps `build_parser` / `main` plus the historical
  re-exports, so the MCP server, probe/proxy and third-party imports do not
  change.
- README project structure updated; `docs/RELEASING.md` now shows placeholder
  tags and includes the lint/MCP test step.

### Fixed

- **Docs: the certificate cannot be refreshed manually.** Renewal only happens
  automatically *after* the current certificate expires; there is no way to
  trigger it earlier. README, `docs/CERT-REFRESH.md`, the skill troubleshooting
  table, `docs/ENVIRONMENT.md` and the script header said it as if a manual
  refresh existed — they now state the real constraint and scope the helper to
  "collect the rotated triple, verify it, install it".
- `SECURITY.md` supported-versions table (0.1.x → 0.3.x).
- Dead code (`depth`, `last_status`, `last_body`) and unused imports removed;
  `ruff check` is clean.

## [0.2.0] - 2026-10-31

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
- README: a 「证书过期怎么办（Linux）」 section that points at the helper, plus a
  pointer from the prerequisite list.

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

[Unreleased]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.7...HEAD
[0.3.7]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.6...v0.3.7
[0.3.6]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.5...v0.3.6
[0.3.5]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.4...v0.3.5
[0.3.4]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.3...v0.3.4
[0.3.3]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.4...v0.2.0
[0.1.4]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/LUgABeEEE/minas-webdav/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/LUgABeEEE/minas-webdav/releases/tag/v0.1.0
