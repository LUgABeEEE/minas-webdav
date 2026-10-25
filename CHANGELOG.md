# Changelog

All notable changes to this project are documented here.

## [0.1.2] - 2026-10-25

### Added

- Console script `minas-webdav-mcp` (MCP stdio server entry point), so MCP
  clients and connector catalogs can start the server by name instead of
  spelling out `python -m minas_webdav.mcp_server`.

## [0.1.1] - 2026-10-25

### Added

- CI on Python 3.10–3.13 plus a build + `twine check` job.
- `tests/test_smoke.py`: package import, version, example config, CLI wiring.
- `release.yml`: tag-triggered build, PyPI Trusted Publishing (OIDC) and a
  GitHub release carrying the wheel and sdist. No API token is stored.
- `docs/RELEASING.md`: the one-time PyPI publisher setup and the per-release steps.
- PyPI metadata: authors, keywords, classifiers and project URLs.
- README: PyPI/CI/licence badges and an install section.

## [0.1.0] - 2026-10-25

### Added

- First public release: `minas-webdav` CLI (`ls/stat/du/df/get/put/cat/mkdir/rm/
  mv/cp/find/tree`), WebDAV capability probe, local reverse proxy for drive
  mapping, and an MCP server behind the `[mcp]` extra.
- Agent skill under `skill/` and integration notes under `docs/`.
