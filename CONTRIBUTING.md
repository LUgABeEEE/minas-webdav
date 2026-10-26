# Contributing to minas-webdav

Thanks for helping improve the Xiaomi Smart Storage (MINAS) WebDAV toolkit.

## Ground rules

- **No secrets.** Never commit `credentials.env`, `minas_config.json` (device
  CN), certs, or tokens. Credentials live in `%LOCALAPPDATA%\minasCred\`.
- **Path safety is sacred.** Anything that accepts a remote path must go
  through `ensure_data_path` / reject `..`. Add a test when you touch this.
- **Destructive ops need consent.** `rm -r`, bulk photo/backup moves — CLI and
  MCP must keep confirm/dry-run gates.
- **Offline tests.** `tests/` must not require a live NAS.
- **Agent-safe output.** `--json` shapes and exit codes (`0/1/2/3`) are
  contract surface; call out breaking changes in `CHANGELOG.md`.

## Development setup

```powershell
git clone https://github.com/LUgABeEEE/minas-webdav.git
cd minas-webdav
python -m venv .venv
.\.venv\Scripts\pip install -e ".[mcp,dev]"
.\.venv\Scripts\python -m pytest tests/ -q
```

Optional local config (not committed):

```powershell
Copy-Item minas_webdav\minas_config.example.json minas_webdav\minas_config.json
# edit host / cn as needed
```

## Project layout

| Path | Role |
|---|---|
| `minas_webdav/cli.py` | file CLI |
| `minas_webdav/probe.py` | protocol capability probe |
| `minas_webdav/proxy.py` | localhost reverse proxy for `net use` |
| `minas_webdav/mcp_server.py` | MCP tools (`nas_*`) |
| `skill/` | agent skill package |
| `tests/` | offline unit tests |
| `docs/` | protocol surface + environment notes |

## Pull requests

1. Fork and branch (`fix/…`, `feat/…`, `docs/…`).
2. Keep CLI / MCP / SKILL.md in sync when commands or tool signatures change.
3. Add tests for path safety, parsing, and any new pure helper.
4. Green `pytest` before you open the PR.

## Reporting bugs

Use the bug report template. Include: Windows version, Python version,
whether official client login works, `probe` summary output (redact CN), and
the exact command.

## Security issues

See [SECURITY.md](SECURITY.md). Do not file public issues for credential
handling or path-escape bugs.

## Release notes

Maintainers update `CHANGELOG.md` and bump `pyproject.toml` /
`minas_webdav.__version__` together before tagging.
