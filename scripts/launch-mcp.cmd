@echo off
rem Launch minas-webdav MCP server with THIS repo's venv python (mcp 2.x required).
rem Register in mimocode.jsonc as:
rem   "command": ["cmd", "/c", "F:\\BaiduNetdiskDownload\\Projects\\minas-webdav\\scripts\\launch-mcp.cmd"]
setlocal
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
"%PY%" -m minas_webdav.mcp_server
