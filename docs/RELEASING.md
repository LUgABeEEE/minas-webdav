# Releasing minas-webdav

发布走 **PyPI Trusted Publishing（OIDC）**：GitHub Actions 用一次性的 OIDC
身份换 PyPI 的短时上传令牌，仓库和 GitHub Secrets 里**都不存任何 API token**。

## 一次性配置（只能由仓库所有者在网页上完成）

1. PyPI → 项目 **minas-webdav** → *Settings* → *Publishing* → **Add a publisher**
   → *GitHub*，填：

   | 字段 | 值 |
   |---|---|
   | Owner | `LUgABeEEE` |
   | Repository name | `minas-webdav` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

2. GitHub 仓库 → *Settings* → *Secrets and variables* → *Actions* → **Variables**
   → 新建 `PYPI_TRUSTED_PUBLISHING` = `true`。

   （这个开关是防呆：没配第 1 步时打 tag 仍会构建并生成 GitHub Release，
   只是不会去碰 PyPI，不会留下一次红色的失败记录。）

GitHub 侧的环境 `pypi` 已建好，部署策略限制为 **只允许 `v*` tag**，
分支推送无法进入该环境。

## 每次发版

```bash
# 1) 版本 + CHANGELOG 一起改（两处必须一致）
$EDITOR pyproject.toml minas_webdav/__init__.py CHANGELOG.md

# 2) 本地验证
python -m unittest discover -s tests -v
python -m build && python -m twine check dist/*

# 3) 打 tag 并推送 —— 剩下的全自动
git tag -a v0.1.1 -m "minas-webdav 0.1.1"
git push --follow-tags
```

`release.yml` 会依次：构建 sdist/wheel → `twine check` → OIDC 发布到 PyPI
→ 把产物挂到同名 GitHub Release。

## 发布后核对

```bash
python -m pip download --no-deps -d /tmp/verify minas-webdav==<version>
curl -s -o /dev/null -w '%{http_code}\n' https://pypi.org/pypi/minas-webdav/json
```

## 发错了怎么办

PyPI 不允许删除已发布的版本，只能 **yank**（项目页 → Releases → Yank）。
yank 后 `pip install minas-webdav` 默认不会选中它，但旧环境的锁文件仍可安装。
发布时间窗内的错误版本也可以直接发下一个 patch 版本。

## 应急：token 上传（不推荐）

短期应急可以在本机用项目级 token 上传，但**不要把 token 提交进仓库或写进
workflow**。0.1.0 是这么发的（第一次上手）；从 0.1.1 起统一走 OIDC。
