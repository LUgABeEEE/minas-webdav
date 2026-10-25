# dsh-minas-webdav

DeepSeek Harness 的 [minas-webdav](https://github.com/LUgABeEEE/minas-webdav) 连接包：装完这一条，
DSH 就会把小米智能存储（MINAS）的 MCP server 注册成一行 stdio 配置，模型侧出现 14 个
`minas-webdav` 工具。

## 先装 Python 那一半

这个包只是个配置包，真正的服务在 PyPI 上：

```bash
pipx install 'minas-webdav[mcp]'   # 提供 minas-webdav-mcp 命令
```

一次性准备（与直接用 MCP server 相同）：官方客户端导出的 mTLS 证书放进 `~/.dsh/minasCert`，
`MINAS_USER` / `MINAS_PASS` 写进 `~/.dsh/minasCred/credentials.env`。路径可用
`MINAS_CERT_HOME` / `MINAS_CRED_FILE` 覆盖。**这个包里没有任何凭据。**

## 再装这个插件

```bash
dsh plugin add dsh-minas-webdav
```

它做的事只有一件：往 profile 的组合里插一行

```yaml
- id: mcp-minas-webdav
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: minas-webdav
    transport: stdio
    command: minas-webdav-mcp
```

## 工具

只读：`nas_ls` `nas_stat` `nas_tree` `nas_find` `nas_du` `nas_df` `nas_cat`
写：`nas_get` `nas_put` `nas_mkdir` `nas_mv` `nas_cp` `nas_rm`（递归删除要 `confirm: true`）
自检：`nas_probe`（写唯一临时路径后清理）

## 关掉它

不卸载也能停：在 profile 的 `cordis.patch.yml` 里加

```yaml
- id: mcp-minas-webdav
  disabled: true
```

## License

Apache-2.0，与 minas-webdav 相同。
