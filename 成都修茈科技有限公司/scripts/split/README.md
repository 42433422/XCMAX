# scripts/split/ — monorepo 到多仓的拆分脚本

这些脚本基于 [`git-filter-repo`](https://github.com/newren/git-filter-repo)，
用于把当前 monorepo 的部分路径按干净历史抽出到独立仓库。

## 使用前置

```bash
# 1) 安装 git-filter-repo（推荐）
pip install git-filter-repo
# 或 macOS: brew install git-filter-repo
# Debian/Ubuntu: apt install git-filter-repo

# 2) 确保 monorepo 工作树干净（无 uncommitted change）
git status
```

## 执行

每个脚本都会：
1. 克隆当前仓库到 `.split-out/<target>/`；
2. 在克隆出的副本里跑 `git filter-repo` 按目标路径过滤；
3. 可选地把目录前缀移除（例如 `MODstore_deploy/java_payment_service/` → 仓库根）；
4. 打印"下一步推到远端"的命令供人工执行。

脚本不会向任何远端推送，也不会改当前 monorepo 的历史。

## 各脚本覆盖范围

| 脚本 | 抽出路径 | 生成仓库内根路径 |
| --- | --- | --- |
| `split-payment-java.sh` | `MODstore_deploy/java_payment_service/` | 仓库根（去掉前缀） |
| `split-modstore-backend.sh` | `MODstore_deploy/modstore_server/`、`modman/`、`tests/`、`pyproject.toml`、`alembic/`、`scripts/python-release.sh` | 仓库根（去掉 `MODstore_deploy/` 前缀） |
| `split-modstore-frontend.sh` | `MODstore_deploy/market/` | 仓库根 |
| `split-marketing-site.sh` | 根 `*.html`、`styles.css`、`main.js`、`assets/`、`site/`、`new/` | 保持原路径 |
| `split-vibe-coding.sh` | `vibe-coding/` | 仓库根（去掉 `vibe-coding/` 前缀） |

拆分策略详情见 [`docs/migration/split-repos.md`](../../docs/migration/split-repos.md)。

## 回滚

`.split-out/` 目录可以随时 `rm -rf` 重来；不会影响 monorepo 原本的历史与远端。
