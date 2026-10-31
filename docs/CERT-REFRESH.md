# 证书刷新（Linux）

设备的 WebDAV 端点要求 **mTLS 客户端证书**：不带证书的请求一律 `451`。这张证书有两个绕不开的约束：

1. **只能由小米智能存储的官方桌面客户端签发**，且只存在于运行该客户端的机器上；
2. **有效期约 21 天**。

所以一台 Linux 机器无法自行续签——它能做的是：**收下一个在别处生成好的证书包 → 校验 → 安装 → 在到期前提醒人**。`scripts/minas-cert-refresh.sh` 就是这一环。

## 设计取舍

| 决定 | 原因 |
|---|---|
| 只面向 Linux / POSIX | 依赖 GNU `date -d`、`shred`；不引入 PowerShell 或 Windows API |
| 依赖只有 `bash` + `python3`（标准库）+ `openssl` | 与 CLI 一样零第三方包；证书解析优先用 `openssl`，缺了才回退 `cryptography` |
| **不自己连 NAS** | 只读一个「中转目录」（已挂载的 CIFS/NFS、同步盘、U 盘皆可），因此不需要任何 NAS 凭据，也不会碰到 SMB 认证问题 |
| **不内置通知通道** | 告警发给谁是你的本地策略；用 `MINAS_NOTIFY_CMD` 挂任意命令（mail / Matrix / ntfy / webhook / 脚本） |
| 安装后**真的连一次设备**才算成功 | 「文件放对了但连不上」在这条链路上是常见故障，不能靠 exit 0 蒙混 |
| 校验失败**绝不安装**，且保留中转包 | 私钥一旦被替换成错的/恶意的，后面所有 WebDAV 操作都在错误证书上跑 |

## 生产者契约（在装有官方客户端的机器上做）

任何能访问到那个「中转目录」的机器都可以做生产者，脚本只认这个结构：

```text
<staging>/
└── minas-cred-20261026-153000/          # 目录名必须以 minas-cred- 开头（脚本据此识别）
    ├── <prefix>_cert.pem                # 证书
    ├── <prefix>_private_key.pem         # 私钥
    ├── ca_chain.pem                     # CA 链
    ├── credentials.env                  # 可选：MINAS_USER / MINAS_PASS
    └── manifest.json                    # 必需：文件清单与 sha256
```

`manifest.json`：

```json
{
  "files": [
    { "name": "<prefix>_cert.pem",        "sha256": "…", "kind": "cert" },
    { "name": "<prefix>_private_key.pem", "sha256": "…", "kind": "key"  },
    { "name": "ca_chain.pem",             "sha256": "…", "kind": "ca"   },
    { "name": "credentials.env",          "sha256": "…", "kind": "cred" }
  ]
}
```

约定：

- `kind` 只用于「这个包里的证书是不是已经装过」的判断（比对 `cert` 的 sha256），缺省也能跑；
- 文件名必须是**纯文件名**（不允许路径分隔符、`..`），脚本会拒绝越界条目；
- 三个 `.pem` 缺一不可，只装了 1～2 个会按失败处理；
- 文件权限用什么方式生成都行，脚本安装时会统一为 `0600`；**中转目录里请勿长期存放私钥**，安装成功后脚本会删掉整个包。

## 使用

```bash
# 只看状态（默认）；没有配置 STAGE_DIR 时也能用，只是不会发现中转包
./scripts/minas-cert-refresh.sh --check --json

# 有包就装（幂等：包里的证书与已装的一致时只清理，不重复安装）
MINAS_STAGE_DIR=/mnt/nas/backup/_incoming \
  ./scripts/minas-cert-refresh.sh --auto

# 演练告警通道
MINAS_NOTIFY_CMD=/usr/local/bin/notify-me ./scripts/minas-cert-refresh.sh --test-notify
```

安装过程（`--auto`）：

1. 取 `minas-cred-*` 里**名字最新**的一个（名字含时间戳，按名字倒序）
2. 复制到 `mktemp -d` 的 `0700` 目录 —— 只复制 `*.pem` / `credentials.env` / `manifest.json`
3. 按 `manifest.json` 逐个比对 sha256，任何不一致就中止
4. `install -m 600` 到证书目录，旧文件自动留 `.bak-<时间戳>`
5. 用新证书跑一次 `python3 -m minas_webdav ls /pool0/data`；失败则回滚式中止并保留中转包
6. 通过后 `shred` 临时私钥、删除中转包
7. 状态写入 `status.json`（`state` / `days_left` / `expires_on` / `staged_bundle`）

## 参数与环境变量

| 参数 | 环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `--stage-dir DIR` | `MINAS_STAGE_DIR` | 无 | 中转目录（包放在其下） |
| — | `MINAS_STAGE_MOUNT_SRC` | 无 | 例如 `//nas.lan/backup`，按 `/proc/mounts` 自动找挂载点 |
| `--cert-home DIR` | `MINAS_CERT_HOME` | `${DSH_HOME:-~/.dsh}/minasCert` | 证书目录（与 CLI 默认一致） |
| — | `MINAS_CRED_HOME` | `${DSH_HOME:-~/.dsh}/minasCred` | 凭据目录，`status.json` 也放这里 |
| — | `MINAS_STATUS_FILE` | `$MINAS_CRED_HOME/status.json` | 状态文件 |
| `--warn-days N` | `MINAS_CERT_WARN_DAYS` | `7` | 剩余天数 ≤ N 时告警 |
| `--notify CMD` | `MINAS_NOTIFY_CMD` | 无（只打印） | 告警命令；文本同时作为 `$1` 与 stdin 传入 |
| — | `MINAS_PYTHON` | `python3` | 解释器 |
| — | `MINAS_WEBDAV_HOME` | 本脚本所在目录的上级 | 安装后自检用的仓库根 |
| — | `MINAS_VERIFY_CMD` | `python3 -m minas_webdav ls /pool0/data` | 覆盖自检命令 |

退出码：`0` 健康/刚刷新成功 · `10` 即将到期 · `11` 已过期或缺失 · `12` 刷新失败 · `1` 参数或内部错误。

## 定时运行（systemd）

```ini
# /etc/systemd/system/minas-cert-refresh.service
[Unit]
Description=Collect a MINAS WebDAV certificate bundle if one is waiting

[Service]
Type=oneshot
User=agent
Environment=MINAS_STAGE_DIR=/mnt/nas/backup/_incoming
Environment=MINAS_NOTIFY_CMD=/usr/local/bin/notify-me
ExecStart=/opt/minas-webdav/scripts/minas-cert-refresh.sh --auto --quiet
# 10/11/12 都是「已经处理完、只是需要人」，不必让 systemd 标红
SuccessExitStatus=0 10 11 12
```

```ini
# /etc/systemd/system/minas-cert-refresh.timer
[Unit]
Description=Check the MINAS WebDAV certificate a few times a day

[Timer]
OnCalendar=*-*-* 06:00:00
OnCalendar=*-*-* 12:00:00
OnCalendar=*-*-* 18:00:00
OnCalendar=*-*-* 23:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now minas-cert-refresh.timer
```

每天多次检查几乎没有成本（纯本地读文件、最多一次 `smbclient`/HTTP 自检），而 21 天的证书寿命意味着**最长 24 小时的发现延迟**在这里是不可接受的——所以示例给了 4 个节点。

## 安全注意

- 私钥只落在两个地方：`0600` 的中转包（短暂）和 `0600` 的证书目录；临时目录用 `0700` 并在结束时 `shred`。
- 脚本**从不打印**私钥、口令或证书内容；状态文件里只有天数、日期和包名。
- 中转目录里的包在安装成功后会被删除；校验失败时保留，便于人工排查——处理完请手删。
- 不要把证书、私钥、`credentials.env` 提交进 Git。

## 故障排查

| 现象 | 处理 |
|---|---|
| `no staging directory` | 没设 `MINAS_STAGE_DIR` / `MINAS_STAGE_MOUNT_SRC`，或挂载没起来；先 `ls` 一下中转目录 |
| `bundle rejected by manifest validation: sha256 mismatch` | 生产端复制损坏或写入未完成；重新投递 |
| `bundle does not contain the full triple` | 包里少了证书/私钥/CA 链之一 |
| `post-install check failed` | 证书本身无效、`cn` 不匹配或网络不通；包会被保留，`--no-verify` 可跳过自检但不建议 |
| `days_left: -1` | 证书目录空，或既没有 `openssl` 也没有 `cryptography`，无法解析 |
| 一直 `expiring` 但中转区没包 | 生产端还没投递；`--check` 的输出里会写明 `newest_bundle: none` |

## 限制

- 只在 Linux 上验证过（GNU coreutils + systemd）；macOS 上 `date -d`/`shred` 语义不同，未做适配。
- 脚本不会也无法续签证书——它只搬运。真正的续签动作必须在装有官方客户端的机器上完成。
