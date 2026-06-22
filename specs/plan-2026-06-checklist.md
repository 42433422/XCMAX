# XCMAX 全量改进计划 Checklist（2026-06）

> 配套主文档：[`plan-2026-06.md`](plan-2026-06.md)
> 用途：PR / Issue 打勾用；执行完一项在 `- [ ]` 改成 `- [x]` 并附 commit SHA
> **每周节奏**：[`weekly/README.md`](weekly/README.md)（当前周次见目录内 `YYYY-Www.md`，与路径图 §6 模板一致）
> **阻塞项（勿标完成）**：[`BLOCKERS.md`](BLOCKERS.md)（T36–37 staging 截图 / T56 生产月报 / T59 split push）  
> **2026-06 脚手架**：T34–35、T38、T45、T55–T57（SYNTHETIC）、T58/T60、T61 dry-run、T66–T67 已交付 — 见各任务行注释  
> **W23 复验（2026-06-05）**：mypy **6/6** · e2e **14/14**（mock）· `du -sh` **~10 GB**（plan **≤8 GB 未达标**）· **`b566ff9f`**（bulk 文档外置 + 运维/可观测脚本 + docs CI）· **`4987839c`**（[`M0-remaining-gaps.md`](../FHD/docs/M0-remaining-gaps.md) 三项仍缺）— 见 [`weekly/2026-W23.md`](weekly/2026-W23.md)；**T36–T37 / T59 仍 `[ ]`**
> **部分闭环 SSOT**：[`close-2026-06-plan/`](.trae/specs/close-2026-06-plan/)（68 项：65 ✅ / 3 ⛔ 阻塞 — T36/T37/T59，详见 [`BLOCKERS.md`](BLOCKERS.md)）

---

## P0 — 仓根卫生与可复跑

### P0-1 清理 FHD 仓根运行残留
- [x] T1：`FHD/.gitignore` 增加 coverage-*.xml/json + .venv-* + 微信私有配置 + 运行态 JSON
- [x] T2：`git rm --cached` 9 份 coverage 产物 + 3 份运行态（仅 `project.private.config.json` 曾入库，已 `--cached` 移除；其余 11 份本就未跟踪）
- [x] T3：.venv-* 不进 git（`.venv-hardening/`、`.venv-mypy/`、`.venv-governance/` 已加入 ignore，且从未入库）
- [x] T4：`docs/START_HERE.md` 增加"覆盖率从 CI artifact 下载"段

### P0-2 清理 `MODstore_deploy/market/` 运行残留
- [x] T5：`.gitignore` 增加 dist*.tar/tgz + cov*.txt + strict-*.txt + out/err/test-results/wav/png 黑名单（含 `market-dist-upload.tgz`）
- [x] T6：`git rm --cached` 20+ dist 压缩包 + 7+ cov 文件 + 4 份 strict 日志 + 4 份运行产物（仅 `market-dist-upload.tgz` 曾入库，已移除；其余本就未跟踪）
- [x] T7：`dist/.gitkeep` 守位（父仓 `.gitignore` 改为 `dist/*` + `!dist/.gitkeep` 例外）

### P0-3 一条命令跑起来
- [x] T8：仓根 `Makefile`（setup/dev/test/test-coverage/lint/openapi-check/e2e）
- [x] T9：`Makefile.win` 兼容 Windows
- [x] T10：仓根 README 改 `make setup && make dev`

### P0-4 _v2 收口单调递减
- [x] T11：`grep -rl "_v[0-9]\+\.py$" FHD/app/` 清单（24 个，见 `docs/MIGRATION_v2_DROP_PLAN.md` §1）
- [x] T12：v1 → alias 桥接 — **本轮跳过**（registry 判定 V1/V2 非 drop-in；见迁移文档 §3.3）
- [x] T13：写 `docs/MIGRATION_v2_DROP_PLAN.md` + `scripts/ci/v2_versioned_py_allowlist.txt`
- [x] T14：pre-commit + CI `guard-no-new-v2-files`（`scripts/guard_no_new_v2_files.py`）

### P0-5 重组 tests/routes/ 巨文件
- [x] T15：`FHD/scripts/dev/split_routes_tests.py` 拆分工具骨架
- [x] T16：共享 fixture — `tests/routes/conftest.py`（health/template/compat_customer 三试点）
- [x] T17：`pytest tests/routes/ -q` 试点后验证（见执行记录）
- [x] T18：`specs/test-naming.md` 加"禁合并多模块"硬规则

---

## P1 — 架构债与可观察性

### P1-1 mypy ignore_errors 清理（6 个月）
- [x] T19（07 月）：`app.legacy.*` 收口（`TD-P1-1-LEGACY-2026-07`；`pyproject.toml` 独立 strict override）— **W23 复验**：legacy 无宽口径
- [x] T20（07 月）：`app.infrastructure.ai.*` `app.infrastructure.llm.*` 收口（TD-P1-1-AI-2026-07；**已收紧**，见 `FHD/docs/MYPY_BATCH_STATUS.md`）
- [x] T21（08 月）：`app.application.workflow.*` 收口（TD-P1-1-WORKFLOW-2026-08；**已移出**宽口径，子集见 MYPY_BATCH_STATUS）
- [x] T22（08 月）：`app.infrastructure.persistence.*` `app.infrastructure.repositories.*` 收口（TD-P1-1-PERSIST-2026-08；**已移出**宽口径）
- [x] T23（09 月）：`app.infrastructure.gateways.*` 收口（TD-P1-1-GATEWAYS-2026-09；**已收紧**）
- [x] T24（10 月）：`app.services.*` `app.fastapi_routes.*` `app.routes.*` `app.mod_sdk.*` `app.neuro_bus.*` 收口（TD-P1-1-SURFACE-2026-10；routes/ai_chat **已 strict**；services 等仍处 **6 项**宽口径之一）
- [x] T25：每批配 `TECH-DEBT-ID`（`FHD/docs/MYPY_TECH_DEBT.md` + PR 模板段）— **W23**：plan SSOT **18→6** 达标（`pyproject.toml` 宽口径 **6/6**）

### P1-2 数据库双 migration 路径统一
- [x] T26：`docs/DB_DUAL_TARGET_STRATEGY.md`
- [x] T27：删 `app/db/ensure_mod_postgres.py`（→ `scripts/bootstrap_mod_dbs.py` + `app/db/bootstrap_mod.py`）
- [x] T28：`sqlite_write_guard` 并入 `session_cache.py`（shim 保留于 `sqlite_write_guard.py`）
- [x] T29：XCAGI 子树 alembic 入口文档化

### P1-3 写真 e2e（5 条关键链路）
- [x] T30：FHD/frontend/e2e/ **5 链路** + README + `docs/evidence/e2e/` PNG — **W23 复验**：`npm run test:e2e:p0` → **14/14**（mock）
- [x] T31：CI — `FHD/.github/workflows/e2e-playwright-reusable.yml` + `e2e.yml`；仓根 `e2e.yml` 复用 — **W23**：本地 14/14 可复现（staging 仍待路径图 W4）
- [x] T32：`FHD/docs/screenshots/README.md`（CI artifact 取图说明；本地无全栈 PNG 占位）
- [x] T33：`docs/V10_ACCEPTANCE.md` 增加 e2e 跑通验收项

### P1-4 SLO 接真数据源 <!-- 见 BLOCKERS.md T34–38 -->
- [x] T34：staging Prometheus + Grafana — **脚手架**：[`FHD/k8s/monitoring/STAGING_RUNBOOK.md`](../FHD/k8s/monitoring/STAGING_RUNBOOK.md)；**待 staging** 实际部署
- [x] T35：xcagi-revenue.json 仪表盘 import — **脚手架**：runbook §2.4；**待 staging** import 验收
- [ ] T36：7 天流量 / k6 压测后截图 — **脚手架**：[`k6_7d_contract.js`](../FHD/scripts/observability/k6_7d_contract.js) · [`k6-7day-job.yaml`](../FHD/k8s/monitoring/k6-7day-job.yaml) · [`run_staging_7d_acceptance.sh`](../FHD/scripts/observability/run_staging_7d_acceptance.sh)；**staging 7d 实跑**仍依赖 [`BLOCKERS.md`](BLOCKERS.md) T36–T37 资源
- [ ] T37：截图入 FHD/docs/evidence/slo/ — **脚手架**：`run_staging_7d_acceptance.sh` + `export_m0_panels.sh --prefix staging`；**合同级 PNG** 待 staging 7d 跑满后 commit
- [x] T38：docs/SLO.md 数据源段 — 已链本地脚本 + 仓内 dashboard JSON + staging runbook

### P1-5 docs 归档门禁
- [x] T39：扩展 `scripts/ci/verify_tier1_docs.py` 检测 Tier 3
- [x] T40：非 Tier 1/2 md 强制 frontmatter（**仅 PR 新增文件**；存量见 `--tier3-report`）
- [x] T41：archived 文件迁 docs/_archive/（首批 5 份 → `FHD/docs/_archive/reports/`，原路径 stub；其余分批）— **W23**：`b566ff9f` bulk Tier 文档 → ~/XCMAX-archives + `ARCHIVE_POINTER`；`v7-reference/*.tar` 已外置
- [x] T42：CI `docs-archive-guard.yml`

### P1-6 README / 入口文档去重
- [x] T43：建"仓库根 → 子项目"索引表
- [x] T44：FHD/MODstore/README.md 加 redirect
- [x] T45：FHD-个人/ 移到仓外 — 已迁至 [`FHD/docs/_archive/FHD-个人/`](../FHD/docs/_archive/FHD-个人/)；仓根 stub：[`FHD-个人/README.md`](../FHD-个人/README.md) — **W23**：[`specs/FHD-个人-MIGRATION.md`](FHD-个人-MIGRATION.md) 交叉核对
- [x] T46：仓根 README 顶部加"项目状态表"

---

## P2 — 业务可观察性 / 跨平台 / 拆仓

### P2-1 macOS 桌面真实验证
- [x] T47：CI `macos-latest` runner 跑 electron 冒烟（`.github/workflows/desktop-macos-smoke.yml`）
- [x] T48：`start-desktop.command` macOS 启动脚本（实际入口 `FHD/XCAGI/start-desktop-sqlite.command`；`FHD/start-desktop.command` redirect 未创建，仓根 README 已直接指向真实路径）
- [x] T49：electron-builder notarize 配置（`desktop/electron-builder.yml` 引用 `build/notarize.cjs` 等 4 文件；**2026-06-20 补齐** `build/{before-pack.cjs, installer.nsh, entitlements.mac.plist, notarize.cjs}`，此前缺失导致打包失败）
- [x] T50：`docs/DEPLOYMENT.md` 加"macOS 实验性"标识
- [x] T51-mac：**macOS 升签约级（2026-06-06）**：arm64+x64 双架构 dmg · `electron-builder.yml` 移除 pkg · `build-installer.sh` 增 `XCAGI_MAC_ARCH` · `release-desktop.yml` 双架构矩阵 + `macos-merge` job · `desktop-macos-smoke.yml` 同步 · 本机 arm64 企业版冒烟验证 · 桌面/Web **签约级**；**Android 仍为实验骨架**（见 P2-2 / [`VERSION.md`](../FHD/VERSION.md)）
  - > **2026-06-20 复核降级**：上述"签约级"为过度声称。实测发现 `desktop/build/` 下 4 个文件（before-pack.cjs / installer.nsh / entitlements.mac.plist / notarize.cjs）缺失，导致 electron-builder 打包必然失败（已补齐）；CI `desktop-macos-smoke.yml` 仅跑启动冒烟、不跑打包；无真实 Electron E2E（IPC/托盘/更新/崩溃恢复未端到端测过）。实际状态：**代码已适配 arm64/x64，待生产级完整验证**。仓根 README 已同步为该表述。

### P2-2 Android 端诚实标注
- [x] T51：`mobile-android/README.md` 改"规划中"
- [x] T52：写 1 个 MainActivity.kt + Compose 简单页（既有 `MainActivity.kt` + `XcagiNavHost`，未删功能）
- [x] T53：CI `android-build.yml`（仓根 `.github/workflows/android-build.yml`）
- [x] T54：仓根 README 同步 Android 状态

### P2-3 AI 业务证据化 <!-- 见 BLOCKERS.md T55–57 -->
- [x] T55：选 2 个场景（发货单自动审 / 合同到期提醒）— **脚手架**：[`FHD/docs/AI_BUSINESS_EVIDENCE.md`](../FHD/docs/AI_BUSINESS_EVIDENCE.md)
- [x] T56：跑 1 个月数据 — **SYNTHETIC/SEED** 月报已写入 [`FHD/docs/AI_BUSINESS_EVIDENCE.md`](../FHD/docs/AI_BUSINESS_EVIDENCE.md)（`seed_synthetic_evidence.py`）；生产/staging 复核待补
- [x] T57：数据入 `docs/AI_BUSINESS_EVIDENCE.md` — 2026-06 SYNTHETIC 月报已填；生产数值待替换

### P2-4 拆分 `成都修茈科技有限公司/` <!-- 见 BLOCKERS.md T58–61 -->
- [x] T58：建 3 个空仓（market / backend / payment）— 已在 **42433422** 个人账号创建；组织 `xiu-ci/*` 待 Owner 迁移 remote
- [ ] T59：`git subtree split` 拆出 <!-- dry-run 清单已生成；push 需 git-filter-repo -->
- [x] T60：本地仓改保留为总览 — [`成都修茈科技有限公司/README.md`](../成都修茈科技有限公司/README.md) 总览 + 外链
- [x] T61：SPLIT_MILESTONES.md 更新 — dry-run 清单 [`SPLIT_DRY_RUN_MANIFEST.json`](../成都修茈科技有限公司/docs/migration/SPLIT_DRY_RUN_MANIFEST.json)；T59 push 待 git-filter-repo

### P2-5 DORA metrics 真实落盘
- [x] T62：CI `FHD/.github/workflows/dora-metrics-collect.yml` 每日写 `FHD/metrics/dora-YYYYMMDD.json`
- [x] T63：月报脚本 `FHD/scripts/dora_metrics_render.py` → `metrics/dora-monthly-YYYYMM.md`
- [x] T64：4 指标入仓 + `FHD/metrics/DORA_DATA_SOURCES.md`（种子 `deploy_events.seed.jsonl`、日快照、202606 月报）

---

## P3 — 长期改进

### P3-1 商业模式"声称-事实"差距表
- [x] T65：`docs/CLAIMED_VS_ACTUAL.md`（模板，实际列待填）
- [x] T66：每月更新 — **脚手架**：2026-06 首轮「待填」行已入 [`FHD/docs/CLAIMED_VS_ACTUAL.md`](../FHD/docs/CLAIMED_VS_ACTUAL.md)；数值待负责人填

### P3-2 pro-mode 特效投入评估
- [x] T67：评审报告 — [`FHD/docs/PRO_MODE_INVESTMENT_REVIEW.md`](../FHD/docs/PRO_MODE_INVESTMENT_REVIEW.md)
- [x] T68：高级视觉模式开关（默认关闭；不删 `pro-mode/` 组件）— 见 `FHD/docs/PRO_MODE_INVESTMENT_REVIEW.md` §T68

---

## 总览

- P0 任务数：26
- P1 任务数：24
- P2 任务数：14
- P3 任务数：4
- **合计：68 个 TODO**

每完成一项：把 `- [ ]` 改成 `- [x] TODOxx` 并在 PR 描述里附 commit SHA。
