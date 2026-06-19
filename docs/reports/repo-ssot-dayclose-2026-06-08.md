# XCMAX 根仓日终检查与归档（2026-06-08）

> v10 线内迭代 · 不升版本号 · 归档类型：**工程起源迁移**

## 1. 检查清单（全量）

| # | 项 | 结果 | 证据 |
|---|-----|------|------|
| 1 | 仓根唯一 `.git` | ✅ | 仅 `/XCMAX/.git`；`FHD/`、`MODstore_deploy/` 无嵌套 `.git` |
| 2 | 嵌套仓历史备份 | ✅ | `~/XCMAX-archives/nested-git-backup-20260608/`（FHD / MODstore / WechatDecrypt） |
| 3 | GitHub remote 权威 | ✅ | `origin` → `42433422/XCMAX`，分支 `main` |
| 4 | WechatDecrypt gitlink | ✅ | 160000 已移除，普通文件 3 个 |
| 5 | CI 调度入口 | ✅ | 根 `.github/workflows/` 20 个；见 [`CI_SSOT.md`](../CI_SSOT.md) |
| 6 | 子目录 workflow 指针 | ✅ | `FHD/.github/workflows/README.md`、`MODstore_deploy/.github/workflows/README.md` |
| 7 | 克隆/提交文档 | ✅ | 根 `README`、`FHD/README`、`QUICK_START`、`specs/weekly/` |
| 8 | `_archive/` 卫生 | ✅ | `bash scripts/verify_no_archive_in_tree.sh` → OK |
| 9 | Mod 一致性 | ✅ | `python FHD/scripts/dev/mods_ssot.py check` → 2 Mod 一致 |
| 10 | 版本锚点 v10 锁 | ✅ | 本次未 bump；`CHANGELOG` Unreleased 已记 |

## 2. Git 提交链（根仓）

| SHA | 说明 |
|-----|------|
| `9367bbcf` | 初始化 XCMAX 根仓（~18k 文件，pack ~123 MB） |
| `5fd24c9c` | CI 迁根、WechatDecrypt、文档对齐 |

## 3. 体积双口径（迁移后复测）

| 口径 | 数值 | 说明 |
|------|------|------|
| 根 `.git` pack | **~123 MB** | GitHub 可推送体量 |
| `du -sh XCMAX/.git` | **~132 MB** | 含 loose objects |
| `du -sh XCMAX`（本机） | **~12 GB** | 含 FHD 本地 `.venv*`、`node_modules` 等（多数已 gitignore） |
| 历史子仓 `.git`（已迁出） | **~9.6 GB** | 不在交付树；备份于 `~/XCMAX-archives/` |

> **M0 口径更新**：2026-06-08 起 **`FHD/.git` 已不存在**；本机 `du` 仍可能因 `.venv`/构建产物偏大，尽调交付树仍以 **不含 `.git` 且不含本地 venv** 为准。

## 4. 退役 remote（只读 / 历史）

| 旧 remote | 角色 | 处置 |
|-----------|------|------|
| `ai-excel-helper` | FHD 历史 | 只读；新提交 → XCMAX |
| `XCMAX-roadmap` | 路线图证据链 | 只读 |
| `xcagi-modstore` | MODstore | 只读 |

## 5. 未纳入 / 待办

| 项 | 状态 |
|----|------|
| 根目录 2 张本地 `.jpg`/`.png` | 未跟踪（非交付树） |
| `FHD/.github/workflows/release-android.yml` | 空文件；Android CI 以根 `android-build.yml` 为准 |
| 旧子仓 tag `v10.0.0` 迁移到根仓 | 待发版窗口打 tag |
| M0 缺口 #1 / #3（staging SLO、Docker 四图） | 与本次迁移无关，仍 `[ ]` |

## 6. 维护命令

```bash
# 克隆
git clone https://github.com/42433422/XCMAX.git && cd XCMAX

# 同步 CI workflow（改 FHD/MODstore 源 yml 后）
python scripts/dev/publish_ci_workflows_to_root.py

# 日检
bash scripts/verify_no_archive_in_tree.sh
cd FHD && python scripts/dev/mods_ssot.py check
```

## 7. 离线归档指针

本报告实体：`FHD/docs/reports/repo-ssot-dayclose-2026-06-08.md`（随根仓提交）。

离线备份索引：`~/XCMAX-archives/nested-git-backup-20260608/README.md`
