# XCMAX 工作区地图

**最后更新**：2026-06-17

> **版本控制**：**`XCMAX/` 根目录为 SSOT 单仓**（`git clone` 即得 FHD + MODstore + specs 全栈）。历史子仓 `.git` 备份于 `~/XCMAX-archives/nested-git-backup-20260608/`。远程：**[`42433422/XCMAX`](https://github.com/42433422/XCMAX)**。CI 入口见 [`docs/CI_SSOT.md`](docs/CI_SSOT.md)。周度归档见 [`specs/weekly/`](specs/weekly/)。
>
> **产品线 SSOT**：当前按 **三条主线 + 个人版冻结** 推进，详见 [`specs/product-lines-3-plus-2.md`](specs/product-lines-3-plus-2.md)。
>
> **版本锁定**：产品大版本锁死 **v10**，全产品线版本锚点恒为 **`10.0.0`**。阶段推进使用 v10-A/B/C/D、channel、Git tag、`git_sha`、`sha256` 和 manifest，不使用 `v10.1`、`v10.2`、`v10.3` 或 `v11` 作为路线承诺。

## 项目状态表（三条主线 + 冻结线）

| 子项目 | 路径 | 活跃度 | 日常入口 | CI 主 workflow |
|--------|------|--------|----------|----------------|
| **企业桌面 ERP + AI** | [`FHD/`](FHD/) | **P0 主交付** — 企业桌面宿主、本地 ERP、AI 员工、行业 Mod | [`FHD/docs/START_HERE.md`](FHD/docs/START_HERE.md) | [`fhd-ci-cd.yml`](.github/workflows/fhd-ci-cd.yml) |
| **AI 员工商店** | [`成都修茈科技有限公司/`](成都修茈科技有限公司/) | **P1 商业化线** — 员工 / Mod 目录、授权、支付、下载、更新 | [`MODstore_deploy/docs/developer/README.md`](成都修茈科技有限公司/MODstore_deploy/docs/developer/README.md) | [`modstore-ci-backend-python.yml`](.github/workflows/modstore-ci-backend-python.yml) |
| **移动 AI 协同 App** | [`FHD/mobile-android/`](FHD/mobile-android/) | **P2 配套线** — Kotlin Compose · 登录 / 扫码 / 对话 / 审批 / 通知 | [`FHD/docs/guides/MOBILE_ANDROID.md`](FHD/docs/guides/MOBILE_ANDROID.md) | [`.github/workflows/android-build.yml`](.github/workflows/android-build.yml) |
| **技术债与计划** | [`specs/`](specs/) | **活跃** — 规范与 checklist | [`specs/plan-2026-06.md`](specs/plan-2026-06.md) | — |
| **FHD 历史副本** | [`FHD/MODstore/`](FHD/MODstore/) | **废弃** — 仅保留防断引用 | 见 redirect README | 勿在此开发 |
| **个人版** | [`FHD/docs/_archive/FHD-个人/`](FHD/docs/_archive/FHD-个人/) | **冻结** — 暂停新增投入，仅保留兼容、归档和未来恢复入口 | [`FHD/docs/_archive/FHD-个人/ARCHIVED.md`](FHD/docs/_archive/FHD-个人/ARCHIVED.md) | 不进入当前版本目标 |
| **工作区归档** | [`_archive/`](_archive/) | **只读** | 各目录 `ARCHIVED.md` | — |

> 声称 vs 实测差距跟踪：[`FHD/docs/CLAIMED_VS_ACTUAL.md`](FHD/docs/CLAIMED_VS_ACTUAL.md) · 外部依赖阻塞：[`specs/BLOCKERS.md`](specs/BLOCKERS.md)

## 活跃维护（日常开发 / 发版 / CI）

| 路径 | 用途 |
|------|------|
| [`FHD/`](FHD/) | **企业桌面 ERP + AI 主交付**：后端、前端、桌面安装包、行业 Mod、企业交付文档；个人版仅保留兼容入口 |
| [`成都修茈科技有限公司/`](成都修茈科技有限公司/) | **AI 员工商店**：MODstore、官网、支付、授权、下载与员工 / Mod 目录 |
| [`FHD/mobile-android/`](FHD/mobile-android/) | **移动 AI 协同 App**：企业账号、扫码连接、AI 对话、通知、审批、移动查看 |
| [`specs/`](specs/) | 跨线产品策略、技术债清偿规范和周度执行记录 |

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
**macOS 桌面**：双击 [`FHD/XCAGI/start-desktop-sqlite.command`](FHD/XCAGI/start-desktop-sqlite.command)（arm64/x64 双架构已适配，尚未经生产级完整验证；主交付仍为 Windows；与 `start-desktop-sqlite.bat` 等价）。

### 发版口径

当前主发版目标是 **企业桌面端可交付**。双 SKU 打包能力仍保留，见 [`FHD/docs/guides/RELEASE_TWO_SKUS.md`](FHD/docs/guides/RELEASE_TWO_SKUS.md)；个人版处于冻结状态，不进入当前路线图承诺。

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

覆盖率 SSOT：[`FHD/docs/reports/COVERAGE_RAMP.md`](FHD/docs/reports/COVERAGE_RAMP.md) · HEAD **85.07%** 行 / WIP **74.56%**（`metrics/coverage-dual-summary.json`）。

## Python 依赖锁定

| 路径 | 用途 |
|------|------|
| [`FHD/uv.lock`](FHD/uv.lock) | **主仓** uv 锁定（`cd FHD && uv sync`） |
| [`FHD/XCAGI/requirements.lock.txt`](FHD/XCAGI/requirements.lock.txt) | pip-compile 锁定（CI / 传统 pip 安装） |

Monorepo 根目录 **无** 独立 `uv.lock`；Python 开发请以 **`FHD/`** 为工作目录。

## 文档真相源

- **日常入口（18 份可直接执行）**：[`FHD/docs/START_HERE.md`](FHD/docs/START_HERE.md) · 公开站 <https://docs.xiu-ci.com/>
- **产品版本（唯一数字来源）**：[`FHD/VERSION.md`](FHD/VERSION.md) — v10 锁定、锚点恒 `10.0.0`；README / CHANGELOG 与之冲突时以 VERSION 为准
- 发布叙事：[`FHD/CHANGELOG.md`](FHD/CHANGELOG.md)
- 全文分层索引：[`FHD/docs/DOCUMENTATION_MAP.md`](FHD/docs/DOCUMENTATION_MAP.md)
- 工作区分析 JSON：由 `scripts/build-xcmax-tree-data.py` 写入 `.cache/xcmax/`（勿提交根目录 `xcmax-*.json`）
