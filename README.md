# XCMAX 工作区地图

**最后更新**：2026-06-08

> **版本控制**：**`XCMAX/` 根目录为 SSOT 单仓**（`git clone` 即得 FHD + MODstore + specs 全栈）。历史子仓 `.git` 备份于 `~/XCMAX-archives/nested-git-backup-20260608/`。远程：**[`42433422/XCMAX`](https://github.com/42433422/XCMAX)**。CI 入口见 [`docs/CI_SSOT.md`](docs/CI_SSOT.md)。周度归档见 [`specs/weekly/`](specs/weekly/)。

## 项目状态表（仓库根 → 子项目）

| 子项目 | 路径 | 活跃度 | 日常入口 | CI 主 workflow |
|--------|------|--------|----------|----------------|
| **XCAGI 主产品** | [`FHD/`](FHD/) | **活跃** — 后端 / 前端 / 桌面 / 双 SKU | [`FHD/docs/START_HERE.md`](FHD/docs/START_HERE.md) | [`fhd-ci-cd.yml`](.github/workflows/fhd-ci-cd.yml) |
| **Android（签约级）** | [`FHD/mobile-android/`](FHD/mobile-android/) | **签约级移动产品** — 双 SKU · IM V0 · `release-android.yml` | [`FHD/docs/guides/MOBILE_ANDROID.md`](FHD/docs/guides/MOBILE_ANDROID.md) | [`.github/workflows/android-build.yml`](.github/workflows/android-build.yml) |
| **MODstore 姊妹栈** | [`成都修茈科技有限公司/`](成都修茈科技有限公司/) | **活跃** — 市场前端 / modstore_server / 支付 | [`MODstore_deploy/docs/developer/README.md`](成都修茈科技有限公司/MODstore_deploy/docs/developer/README.md) | [`modstore-ci-backend-python.yml`](.github/workflows/modstore-ci-backend-python.yml) |
| **技术债与计划** | [`specs/`](specs/) | **活跃** — 规范与 checklist | [`specs/plan-2026-06.md`](specs/plan-2026-06.md) | — |
| **FHD 历史副本** | [`FHD/MODstore/`](FHD/MODstore/) | **废弃** — 仅保留防断引用 | 见 redirect README | 勿在此开发 |
| **个人版归档** | [`FHD/docs/_archive/FHD-个人/`](FHD/docs/_archive/FHD-个人/) | **只读归档** — 仓根 [`FHD-个人/`](FHD-个人/) 为 stub | [`FHD/docs/_archive/FHD-个人/ARCHIVED.md`](FHD/docs/_archive/FHD-个人/ARCHIVED.md) | 已迁（T45，2026-06） |
| **工作区归档** | [`_archive/`](_archive/) | **只读** | 各目录 `ARCHIVED.md` | — |

> 声称 vs 实测差距跟踪：[`FHD/docs/CLAIMED_VS_ACTUAL.md`](FHD/docs/CLAIMED_VS_ACTUAL.md) · 外部依赖阻塞：[`specs/BLOCKERS.md`](specs/BLOCKERS.md)

## 活跃维护（日常开发 / 发版 / CI）

| 路径 | 用途 |
|------|------|
| [`FHD/`](FHD/) | **XCAGI v10.0.0** 一体化主仓：后端、前端、桌面（**Windows 主交付 · 签约级**；**Android 签约级**；macOS **实验性** — 见 [`FHD/VERSION.md`](FHD/VERSION.md)）、双 SKU 打包 |
| [`成都修茈科技有限公司/`](成都修茈科技有限公司/) | MODstore、官网、支付等姊妹项目 |
| [`specs/`](specs/) | 技术债清偿规范（范围：FHD + 成都修茈） |

### 快速启动

在**仓根**（`XCMAX/`）一条命令完成依赖安装与开发服务启动：

**macOS / Linux**

```bash
make setup && make dev
```

**Windows**（需已安装 `make`，例如 [Git for Windows](https://git-scm.com/download/win)）

```powershell
make -f Makefile.win setup
make -f Makefile.win dev
```

其他常用目标（仓根执行）：`make test`、`make lint`、`make openapi-check`、`make e2e`（Windows 将 `make` 换为 `make -f Makefile.win`）。  
详细场景（桌面 SQLite、Docker、双模式）见 [`FHD/docs/guides/快速启动说明.md`](FHD/docs/guides/快速启动说明.md) 与 [`FHD/docs/QUICK_START.md`](FHD/docs/QUICK_START.md)。  
**macOS 桌面**：双击 [`FHD/start-desktop.command`](FHD/start-desktop.command)（**实验性**，主交付仍为 Windows；与 `start-desktop-sqlite.bat` 等价）。

### 双 SKU 发版

见 [`FHD/docs/guides/RELEASE_TWO_SKUS.md`](FHD/docs/guides/RELEASE_TWO_SKUS.md)。

## 只读归档（勿作日常入口）

已迁入 [`_archive/`](_archive/)，各目录含 `ARCHIVED.md`：

- SKU 拆仓外壳：[`_archive/sku-repos-20260527/`](_archive/sku-repos-20260527/)（`xcagi-enterprise`、`xcagi-personal`、`xcagi-offline`）
- 历史 core 快照：`xcagi-core-20260526-223646`
- 并行实例 / 副本：`FHD-个人`、`_personal_sync_bak`、`面试区域`

**禁止**：对归档树执行 `build-enterprise.ps1` 等 overlay 复制后再提交 core。

## 活跃测试入口（勿在 `_archive/` 补测）

| 项目 | 套件路径 | 本地命令 | CI |
|------|----------|----------|-----|
| FHD / XCAGI | [`FHD/tests/`](FHD/tests/)（索引：[`FHD/tests/INDEX.md`](FHD/tests/INDEX.md)） | `cd FHD && python -m pytest tests/ -q` | [`fhd-ci-cd.yml`](.github/workflows/fhd-ci-cd.yml) |
| MODstore | [`MODstore_deploy/tests/`](成都修茈科技有限公司/MODstore_deploy/tests/) | `cd 成都修茈科技有限公司/MODstore_deploy && python -m pytest tests/ -q` | [`modstore-ci-backend-python.yml`](.github/workflows/modstore-ci-backend-python.yml) |
| vibe-coding | [`vibe-coding/tests/`](成都修茈科技有限公司/vibe-coding/tests/) | `cd 成都修茈科技有限公司/vibe-coding && python -m pytest tests/agent/ -q` | 见 yuangon test-qa-runner |
| xcagi_common | [`packages/xcagi_common/tests/`](packages/xcagi_common/tests/) | `cd packages/xcagi_common && python -m pytest tests/ -q` | 随 FHD 变更 |

**测试命名 SSOT**：[`specs/test-naming.md`](specs/test-naming.md)（禁止新增 `test_coverage_ramp_phase*`；pre-commit 钩子 `guard-no-new-coverage-ramp`）。

覆盖率双轨说明：[`FHD/docs/reports/COVERAGE_RAMP.md`](FHD/docs/reports/COVERAGE_RAMP.md)、[`MODstore_deploy/docs/coverage-gates.md`](成都修茈科技有限公司/MODstore_deploy/docs/coverage-gates.md)。

## Python 依赖锁定

| 路径 | 用途 |
|------|------|
| [`FHD/uv.lock`](FHD/uv.lock) | **主仓** uv 锁定（`cd FHD && uv sync`） |
| [`FHD/XCAGI/requirements.lock.txt`](FHD/XCAGI/requirements.lock.txt) | pip-compile 锁定（CI / 传统 pip 安装） |

Monorepo 根目录 **无** 独立 `uv.lock`；Python 开发请以 **`FHD/`** 为工作目录。

## 文档真相源

- **日常入口（18 份可直接执行）**：[`FHD/docs/START_HERE.md`](FHD/docs/START_HERE.md) · 公开站 <https://docs.xiu-ci.com/>
- **产品版本（唯一数字来源）**：[`FHD/VERSION.md`](FHD/VERSION.md) — README / CHANGELOG 与之冲突时以 VERSION 为准
- 发布叙事：[`FHD/CHANGELOG.md`](FHD/CHANGELOG.md)
- 全文分层索引：[`FHD/docs/DOCUMENTATION_MAP.md`](FHD/docs/DOCUMENTATION_MAP.md)
- 工作区分析 JSON：由 `scripts/build-xcmax-tree-data.py` 写入 `.cache/xcmax/`（勿提交根目录 `xcmax-*.json`）
