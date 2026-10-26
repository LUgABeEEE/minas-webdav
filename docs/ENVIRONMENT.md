# 配套环境与设备版本 · 实测记录

> 记录日期：**2026-09-27**（初测）· **2026-10-26**（固件更新后复测，协议面未变）
> 用途：说明跑通本项目需要的环境，以及实测过的 NAS 服务面版本
> 脱敏：不含凭据、设备 UID、CN、IP

## 1. 客户端环境（本机实测）

| 项 | 值 | 说明 |
|---|---|---|
| 操作系统（Windows） | Windows 11（build 22631） | `scripts/挂载NAS为N盘.*` / `删除N盘文件.ps1` 为 Windows 专用 |
| 操作系统（Linux） | Ubuntu 24.04（SER8） | CLI/probe/proxy 纯标准库，Linux 实测可用；**无需挂盘** |
| Python | **3.12.13**（Windows）/ **3.12.3**（Linux）；要求 ≥3.10 | CLI/探测/代理仅用标准库，**零第三方依赖** |
| MCP 依赖 | `mcp==2.2.0`（2.x） | 仅 MCP server 需要；装在项目 `.venv`，勿污染系统 Python |
| 官方客户端 | **小米智能存储 1.0.8.170**（Windows / Electron） | 产生 mTLS 证书与 WebDAV 凭据的唯一来源；**Linux 无客户端** |
| 证书目录 | Windows `%LOCALAPPDATA%\minasCert\`；Linux `$DSH_HOME/minasCert/`（未设 `DSH_HOME` 则 `~/.dsh/minasCert/`） | cert / private_key / ca_chain，**三者必须同目录**；可用 `MINAS_CERT_HOME` 覆盖 |
| 凭据文件 | Windows `%LOCALAPPDATA%\minasCred\credentials.env`；Linux `$DSH_HOME/minasCred/credentials.env`（同上回退） | `MINAS_USER` / `MINAS_PASS`，仓库外；可用 `MINAS_CRED_FILE` 覆盖 |
| 网络 | 与 NAS 同一局域网 | 需可达 `:5000`（WebDAV）与 `:443`（LuCI API，`df`/自动发现用） |

> **Linux 部署方式**：从 Windows 机器把证书三件套复制过来（例如 `~/.dsh/minasCert/`），
> 凭据写成 `~/.dsh/minasCred/credentials.env`（权限 600），然后运行
> `python3 -m minas_webdav probe`（路径默认值已按平台自动选择，通常无需显式设置环境变量）。

安装 Python 依赖（仅 MCP）：

```powershell
# Windows
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install "mcp>=2,<3"
```

```sh
# Linux / macOS
python3 -m venv .venv
.venv/bin/python -m pip install "mcp>=2,<3"
```

## 2. NAS 设备侧（实测）

| 项 | 值 |
|---|---|
| 产品 | **小米智能存储**（Xiaomi Smart Storage / MINAS） |
| 固件版本号 | 官方 API 未直接暴露；请在官方客户端「设备信息」查看。本工具**不依赖具体固件号**，只依赖下方协议面 |
| HTTP 服务 | `nginx/1.24.0`（:5000 WebDAV 与 :443 管理接口同栈） |
| 管理接口 | LuCI on **Lua 5.1**（错误栈可见 `NasStorage.lua`），`/cgi-bin/luci/...` |
| WebDAV | HTTPS **:5000**；`DAV: 1,2`；`Allow: GET,HEAD,PUT,DELETE,MKCOL,COPY,MOVE,PROPFIND,OPTIONS,LOCK,UNLOCK` |
| 认证 | Basic（账密）；无认证返回 451；mTLS 可选。**Host/SNI 必须用设备 CN** |
| 存储池 | `pool_type=cfs`；数据根 `/pool0/data` |
| 只读自检 | `python -m minas_webdav probe`（读写全链路 + 锁） |

已验证的管理 API（mTLS）：

| 路径 | 用途 |
|---|---|
| `POST /cgi-bin/luci/filemgr/get_pool_info` | 存储池 + WebDAV 凭据（`df` 与自动发现的数据源） |
| `POST /cgi-bin/luci/filemgr/list_directory` 等 filemgr 系 | 官方客户端使用，本项目未依赖 |

其余猜测路径实测 403/500，**不要依赖未列入的接口**。

## 3. 版本兼容性说明

- 本项目的能力基线是 **WebDAV 协议面**（上表 Allow/DAV），不绑定固件号；OTA 若改协议面，排查顺序：
  1. `python -m minas_webdav probe` 看能力表变化
  2. `references/webdav-surface.md`（skill）/ `docs/webdav-surface.md`（仓库）的已知坑
  3. 客户端重新登录以刷新证书/凭据
- `mcp` 2.x 与 1.x API 不同（`FastMCP` → `MCPServer`）；本仓库按 **2.x** 编写，若装 1.x 会导入失败
- 客户端 1.0.8.170 为实测版本；更高版本预期兼容（协议面未变时）

## 4. 快速验证清单

```powershell
# 1) CLI 连通
python -m minas_webdav df

# 2) 协议能力
python -m minas_webdav probe

# 3) MCP 工具（注册后新会话可见；或本地直测）
.\.venv\Scripts\python.exe -c "import asyncio,sys; sys.path.insert(0,'.'); from minas_webdav.mcp_server import mcp; print([t.name for t in asyncio.run(mcp.list_tools())])"
```

三步全绿即环境就绪。
