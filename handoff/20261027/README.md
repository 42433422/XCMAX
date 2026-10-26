# XCMAX 现场整改接手包（2026-10-27）

这是源码和未完成草稿的交接包，不是安装包，也不是通过验收的产品。此分支只用于交接，不应直接合入 `main`。

## 内容

`XCMAX-handoff-20261027.zip` 内含：

- `HANDOFF.md`：15 项现场问题逐项状态、失败检查、接手顺序和清理说明。
- `local-branches.bundle`：四条本地提交链，保留真实 Git 提交与各分支头；它是基于公开历史的增量包，不是完整仓库。
- `unstaged.patch`：现场整合线已跟踪文件未提交差异；`staged.patch` 为空。
- `untracked-drafts.tar.gz`：26 个未跟踪源码及测试草稿；须单独审查，不能整目录覆盖。
- `worktree-status.txt`、`SHA256SUMS`：导出时状态及各文件校验值。哈希只证明文件完整，不证明功能通过。

此前的 [2026-10-26 交接包](../20261026/README.md) 保留在本分支；旧补丁和测试数字应按其当时的基线理解。

## 下载和核验

下载 ZIP 和同目录 `SHA256SUMS`，使用 Git Bash 或终端运行：

```bash
shasum -a 256 -c SHA256SUMS
unzip XCMAX-handoff-20261027.zip -d XCMAX-handoff-20261027
cd XCMAX-handoff-20261027
shasum -a 256 -c SHA256SUMS
```

外层校验还包括同目录的 `README.md` 和 `HANDOFF.md`，因此检查外层 `SHA256SUMS` 时应一并下载这两个文件。Linux 也可使用 `sha256sum -c SHA256SUMS`。

## 导入本地提交链

先克隆官方仓库并获取 `main` 完整历史。增量包需要公开历史中的 `e7f31dc23362af19cc9a611851394c4bdfc032f3` 和 `54d4541cbe4cd77e258163c75e3e9fc8c886b507`；导出时两者均为 `origin/main` 的祖先。不要在已有脏工作树内覆盖文件。

```bash
# PKG 改为解压目录的绝对路径。
PKG='/你的路径/XCMAX-handoff-20261027'
git clone https://github.com/42433422/XCMAX.git XCMAX-review
cd XCMAX-review
git cat-file -e e7f31dc23362af19cc9a611851394c4bdfc032f3^{commit}
git cat-file -e 54d4541cbe4cd77e258163c75e3e9fc8c886b507^{commit}
git bundle verify "$PKG/local-branches.bundle"
git bundle list-heads "$PKG/local-branches.bundle"
git fetch "$PKG/local-branches.bundle" \
  refs/heads/codex/takeover-onsite-20261026:refs/heads/handoff/onsite-20261027 \
  refs/heads/codex/harness-takeover-a-20261026:refs/heads/handoff/harness-20261027 \
  refs/heads/codex/etl-candidate-review-20261026:refs/heads/handoff/etl-20261027 \
  refs/heads/codex/1-0-0-7-test-prepare-20261026:refs/heads/handoff/release-20261027
git rev-parse handoff/onsite-20261027 handoff/harness-20261027 handoff/etl-20261027 handoff/release-20261027
```

四个头分别应为：

| 分支 | 导出 HEAD |
| --- | --- |
| 现场整合 | `22be489d7d45971d49934f518f49324c647abf6c` |
| harness | `34fffd9b8a591bec7288cebbbdcfef8daec4a857` |
| ETL 候选 | `275bcf5c24ce6f478e20866b722b8bf32f8f6079` |
| 发布准备 | `3aa4acde90c6e38c7dd94617563a773a595cb6f2` |

如需查看现场线草稿，请先从 `handoff/onsite-20261027` 建立单独的干净 worktree，确认 HEAD 与上表一致，再先审 `unstaged.patch`、执行 `git apply --check`。未跟踪归档先用 `tar -tzf` 检查文件名和目标是否已有同名文件，再按需提取；不要覆盖其他人的修改。草稿中的知识恢复和部分合法 Mod 操作仍临时失败关闭，最新组合回归不通过。

## 交付边界

[PR #2686](https://github.com/42433422/XCMAX/pull/2686) 尚未合并；旧远端检查不代表本包的新提交和草稿通过。#2683 也未合并。没有新的 1.0.0.7 安装包，没有真实模型调用验收。先完成全部整改与原场景验收，再按用户要求统一从主线固定提交构建、安装、升级、恢复和回滚验证。
