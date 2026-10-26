# minas-webdav

[![PyPI](https://img.shields.io/pypi/v/minas-webdav.svg)](https://pypi.org/project/minas-webdav/) [![CI](https://github.com/LUgABeEEE/minas-webdav/actions/workflows/ci.yml/badge.svg)](https://github.com/LUgABeEEE/minas-webdav/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

小米智能存储（Xiaomi Smart Storage / MINAS）**WebDAV 控制工具箱**——不挂盘、不依赖 Samba，直接通过设备的 HTTPS WebDAV 端点（`:5000`）控制整个 `/pool0/data` 存储池。

三条能力线：

| 入口 | 作用 |
|---|---|
| `python -m minas_webdav <cmd>` | 文件 CLI：列目录、统计、上传下载、移动复制、删除 |
| `python -m minas_webdav probe` | 协议能力探测：读写全链路 + 认证 + 锁 |
| `python -m minas_webdav proxy` | 本机反向代理（`127.0.0.1:8899`），供 Windows `net use` / Linux `davfs2` 挂盘 |

## 安装

```bash
pipx install minas-webdav            # CLI（推荐）
pip install "minas-webdav[mcp]"      # 需要 MCP server 时加 extra
```

要求 Python ≥ 3.10。除 `[mcp]` extra 外**无第三方依赖**（只用标准库）。
不装也可以：`PYTHONPATH=. python3 -m minas_webdav --help`。

## 前置条件

配套环境、设备版本与兼容性说明见 **[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)**（Windows 11 与 Linux 均实测；Python 3.10+ / 小米智能存储官方客户端 1.0.8.170 / `mcp` 2.x；NAS 服务面：nginx/1.24.0 + DAV:1,2）。

1. NAS 与本机同一局域网（默认 `192.168.1.100:5000`）
2. 官方客户端已登录过，拿到 mTLS 证书三件套（`*_cert.pem` / `*_private_key.pem` / `ca_chain.pem`，**必须同目录**）
3. 凭据文件在**仓库外**

证书目录与凭据文件的默认位置**按平台自动选择**（可用 `MINAS_CERT_HOME` / `MINAS_CRED_FILE` 覆盖）：

| | Windows | Linux / macOS |
|---|---|---|
| 证书目录 | `%LOCALAPPDATA%\minasCert\` | `$DSH_HOME/minasCert/`（未设则 `~/.dsh/minasCert/`） |
| 凭据文件 | `%LOCALAPPDATA%\minasCred\credentials.env` | `$DSH_HOME/minasCred/credentials.env`（同上回退） |

```text
MINAS_USER=...
MINAS_PASS=...
```

> Linux 上没有官方客户端，需把证书三件套从 Windows 机器复制过来再用 `cert_home` 指过去。

4. 非机密配置：复制 `minas_webdav/minas_config.example.json` 为
   `minas_webdav/minas_config.json`（已 gitignore），填入真实 `host` / `cn`

## 快速开始

```bash
# 列目录（JSON 输出适合 agent）
python -m minas_webdav ls /pool0/data --json

# 存储池容量
python -m minas_webdav df

# 上传 / 下载（中文路径直接写）
python -m minas_webdav put ./local.txt "/pool0/data/agent操作区/a.txt"
python -m minas_webdav get "/pool0/data/agent操作区/a.txt" ./back.txt

# 整理
python -m minas_webdav mkdir /pool0/data/work
python -m minas_webdav mv /pool0/data/a.txt /pool0/data/work/a.txt
python -m minas_webdav cp /pool0/data/a.txt /pool0/data/a-copy.txt
python -m minas_webdav rm /pool0/data/work -r      # 递删前务必确认！

# 能力探测（写测试用唯一路径，自动清理）
python -m minas_webdav probe

# 本地代理（供挂 N 盘 / Explorer 使用）
python -m minas_webdav proxy
```

也可 `pip install -e .` 后直接用 `minas-webdav` / `minas-webdav-proxy` / `minas-webdav-probe` 命令。

### Linux / macOS

CLI 只依赖标准库，**无需安装**——只要在仓库根目录下运行即可：

```sh
cd /path/to/minas-webdav
python3 -m minas_webdav ls /pool0/data --json
python3 -m minas_webdav probe
```

嫌切目录麻烦就用仓库自带的包装脚本（自动切目录 + 选解释器）：

```sh
scripts/minas-webdav ls /pool0/data --json
MIMO_PYTHON=/usr/bin/python3 scripts/minas-webdav df
```

### 挂盘（可选）

Windows（映射为 N 盘）：

```powershell
.\scripts\挂载NAS为N盘.ps1     # 自动拉起代理 + net use N:
.\scripts\删除N盘文件.ps1 <路径> # 删掉资源管理器删不动的文件
```

Linux（需要 `davfs2`，仓库不负责安装）：

```sh
python3 -m minas_webdav proxy &          # 127.0.0.1:8899
sudo mount -t davfs http://127.0.0.1:8899/ /mnt/nas-n
```

不挂盘不影响任何 CLI/MCP 功能。

## 命令一览

| 命令 | 作用 |
|---|---|
| `ls` `stat` `tree` `find` | 浏览（`--max-depth` 防全盘递归） |
| `du` `df` | 目录体积 / 存储池容量 |
| `get` `put` `cat` | 传输 / 查看文本 |
| `mkdir` `mv` `cp` `rm` | 整理（`rm -r` 需用户确认） |

退出码：`0` 成功 · `1` 错误 · `2` 不存在 · `3` 认证/网络。

## 项目结构

```text
minas_webdav/
  config.py    # 配置与凭据加载（跨平台默认路径 + minas_config.json + credentials.env）
  cli.py       # 文件 CLI
  probe.py     # 能力探测
  proxy.py     # 本机反向代理（平台中立；Windows 给 net use，Linux 给 davfs2）
scripts/       # 包装脚本（POSIX `minas-webdav`）+ 挂盘/清理脚本（Windows .ps1）
docs/          # ENVIRONMENT.md / webdav-surface.md 实测结论
```

## 协议要点（详见 [docs/webdav-surface.md](docs/webdav-surface.md)）

- `Host`/SNI 必须用**设备 CN**（`nas.<uid>.<hash>`），不能裸用 IP
- `PROPFIND Depth: infinity` 被拒（403），递归必须逐层 `Depth: 1`
- `MOVE`/`COPY` 的 `Destination` 用**百分号编码的纯路径**；IP 形式的 URL 会 400
- 无认证访问返回 451；Basic 即可，mTLS 可选

## 已知问题：PUT 覆盖已存在的文件**不截断**（2026-10-15 定位并规避）

设备的 WebDAV 在覆盖一个**已存在**的资源时**不做截断**：新内容从偏移 0 写进去，旧文件
的尾巴原样留着。于是文件变成「新内容 + 旧尾巴」的混合体，服务端报告的长度仍是**旧长度**，
而 PUT 照样返回 **204**——调用方以为写成功了。

实测（**与文件大小无关**，只要新内容比旧内容**短哪怕 1 字节**就触发）：

| 场景 | PUT | 服务端报告 size | 回读内容 |
|---|---|---|---|
| 24 MB 覆盖成 2 MB | 204 | 25165824（旧值） | 新头 + 旧尾，sha256 既非新版也非旧版 |
| 6 MB 覆盖成 6 MB−1 | 204 | 6291456（旧值） | 同上 |
| 同尺寸覆盖 / 由小变大 / 新建 | 204 | 正确 | 正确 |

这解释了历史上「大文件覆盖后内容还是旧的、但 stat 的 modified 更新了」的怪现象
（待办 t-f0df70f0）。**当时的应急办法（先 `mv` 改名再用原名上传）之所以有效，是因为
改名后目标是新名字，不存在旧尾巴。**

**已内置规避**：`cli.safe_put()` 从不直接 PUT 到已存在的名字——先 PUT 到同目录的
临时名（`.minas-uploading` 后缀，全新创建），再 `MOVE` 覆盖到目标名；MOVE 不可用时
退回 `DELETE` + `PUT`。写完**回读核对**：长度必须一致（长度不符正是这个 bug 的形状），
默认再用 sha256 核一遍。核对不过就返回失败，绝不静默成功。CLI 的 `put` 与 MCP 的
`nas_put` 都已走这条路。

> 直接用别的客户端（资源管理器挂盘、`curl -T`、其他库）往设备同一路径覆盖**更短**的内容
> 时，仍然会踩到这个问题——WebDAV 侧只有本仓库的工具做了规避。降级开关：
> `MINAS_PUT_VERIFY=size`（省掉回读下载）或 `off`（只做长度核对的前一步，不建议）。

## 安全约束

- 凭据与设备 CN 不进 Git（`.gitignore` 已挡 `minas_config.json` / `*.env`）
- 不写日志、不打印密码；不碰 SSH/Docker/固件
- 递归删除、批量动照片/备份目录前必须征得用户同意

## Agent 接入

本项目同时提供两种 agent 接入方式（设计见 [docs/agent-integration-design.md](docs/agent-integration-design.md)）：

| 方式 | 位置 | 说明 |
|---|---|---|
| **Skill** | 仓库 `skill/` → 拷到 `~/.dsh/skills/minas-webdav/`（DSH）或 `~/.config/mimocode/skills/minas-webdav/`（MiMoCode） | SKILL.md 触发 + 调本 CLI；全局可用 |
| **MCP** | `mcp_server.py` + 宿主注册 `minas-webdav` | 14 个 `nas_*` 工具（stdio）；`nas_rm` 递归必须 `confirm=true` |

### 装 Skill

把仓库 `skill/` 下的内容拷成技能目录即可，**目录名必须等于 SKILL.md 里的 `name`**：

```sh
# DSH（SER8 上跑的就是这个）
cp -r skill/. ~/.dsh/skills/minas-webdav/
```

```powershell
# MiMoCode（Windows 常用）
Copy-Item -Recurse skill "$HOME\.config\mimocode\skills\minas-webdav"
```

### 注册 MCP

任意 MCP 客户端都走 stdio，先让 `minas-webdav-mcp` 可执行：

```bash
pipx install 'minas-webdav[mcp]'   # 提供 minas-webdav-mcp
```

```jsonc
// 通用 mcpServers 形式
"minas-webdav": {
  "command": "minas-webdav-mcp",
  "args": []
}
```

<details>
<summary>DeepSeek Harness 写法</summary>

```yaml
# ~/.dsh/profiles/web/cordis.patch.yml
- insert:
    - id: mcp-minas
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: minas
        transport: stdio
        command: minas-webdav-mcp
```

</details>

或者一行装完（DSH 插件，会替你插入同样的那行配置）：

```bash
dsh plugin add dsh-minas-webdav
```

装完可用 `dsh plugin` 的补丁关掉它（`- id: mcp-minas-webdav` + `disabled: true`）。

证书与凭据只放本机（默认位置按平台推导，见[前置条件](#前置条件)的对照表；可用
`MINAS_CERT_HOME` / `MINAS_CRED_FILE` 覆盖），MCP 配置里不出现任何凭据。

<details>
<summary>从本仓库源码启动（MiMo Desktop / 本地 venv）</summary>

用仓库自带启动器，确保拿到带 `mcp` 依赖的解释器（避免宿主误用无 `mcp` 的 Python）：

```jsonc
// Windows
"minas-webdav": {
  "type": "local",
  "command": ["cmd", "/c", "<仓库路径>\\scripts\\launch-mcp.cmd"],
  "environment": {},
  "enabled": true
}
```

也可以直接指向解释器 + `PYTHONPATH`（Windows 写 `.venv\\Scripts\\python.exe`，Linux 写 `.venv/bin/python` 或 `/usr/bin/python3`）：

```jsonc
"minas-webdav": {
  "type": "local",
  "command": ["<python>", "-m", "minas_webdav.mcp_server"],
  "environment": { "PYTHONPATH": "<本仓库路径>" },
  "enabled": true
}
```

</details>

MCP 依赖装在项目 venv（`pip install "mcp>=2,<3"`，2.x）；Linux 下 venv 解释器在 `.venv/bin/python`，Windows 在 `.venv\Scripts\python.exe`。改 CLI 后请同步更新 SKILL.md 命令表与 MCP 工具签名。

## 测试

```powershell
# Windows：离线单测（路径安全 / WebDAV XML 解析，不触网）
.venv\Scripts\python.exe -m pytest tests/ -q
```

```sh
# Linux / macOS
python3 -m pytest tests/ -q
```

## License

Apache-2.0，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

**声明**

- 本项目是面向小米智能存储（MINAS）的**第三方** WebDAV 工具箱，**不是**小米官方产品，与 Xiaomi 无隶属、赞助或背书关系。
- Xiaomi、小米智能存储及相关商标归其各自权利人所有；此处仅用于指明兼容目标设备。
- 软件按“现状”提供，不附带任何明示或默示担保。使用本工具访问你自己的 NAS 的风险自负；请遵守当地法律法规与厂商服务条款。
- 请勿将本工具用于未授权访问他人存储设备。

**社区**

| 文档 | 说明 |
|---|---|
| [CONTRIBUTING.md](CONTRIBUTING.md) | 贡献流程与开发约定 |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | 社区行为准则 |
| [SECURITY.md](SECURITY.md) | 安全问题私报渠道 |
| [CHANGELOG.md](CHANGELOG.md) | 版本更新日志 |

## 相关

- 挂 N 盘可选 [rclone](https://rclone.com)（官方下载；仓库不打包二进制）
- Samba 通道（仅 Z: 备份共享）是另一套：[`minas-skill`](https://github.com/LUgABeEEE/minas-skill)（SMB 445）
