# XCMAX 历史与大文件归档指针

2026-11-10 旧余债 P2 快照外置：`FHD/docs/architecture/DEBT24_P2_CLOSEOUT.md` 原文及 SHA256 位于 `~/XCMAX-archives/debt24-p2-20261110/`，亦可从提交 `9c53fb4f00` 恢复；现行边界以各注册 SSOT 为准。

2026-11-10 旧分支余债快照外置：`FHD/docs/architecture/DEBT19_STILL9_FOLLOWUP.md` 原文及 SHA256 位于 `~/XCMAX-archives/debt19-followup-20261110/`，亦可从提交 `532b1978d5` 恢复；历史数字不代表当前状态。

2026-11-10 认知全栈历史快照外置：`FHD/docs/architecture/COGNITIVE_FULL_STACK_20260729.md` 原文及 SHA256 位于 `~/XCMAX-archives/cognitive-snapshot-20261110/`，亦可从提交 `58090c512c` 恢复；历史实现清单不代表当前运行或验收状态。

2026-11-10 历史余债报告外置：`FHD/docs/reports/DEBT24_CLOSEOUT.md` 原文及 SHA256 保存在 `~/XCMAX-archives/debt24-closeout-20261110/`，亦可从提交 `58090c512c` 恢复；其旧分支数据不代表当前验收状态。

2026-11-10 旧发布日志外置：`FHD/CHANGELOG.md` 中 1.0.0.0–1.0.0.4 历史条目的原文及 SHA256 保存在 `~/XCMAX-archives/release-changelog-20261110/`，也可从提交 `f5c4a2d164` 恢复；未发布变更仍保留在现行日志。

2026-11-10 旧 LangGraph 基准记录外置：`FHD/docs/architecture/langgraph-absorption/09-baseline.md` 的原文和 SHA256 在 `~/XCMAX-archives/langgraph-baseline-20261110/`；亦可从提交 `d79eff902e` 恢复。该记录是历史测量，不代表当前性能；基准脚本仍可显式生成新的结果。

2026-11-10 历史方案收敛：旧 XCAGI v6 架构副本 `docs/modstore/ddd.md` 与 2026-06 的 `FHD/docs/reports/TO_9_PROGRAM.md` 原样外置至 `~/XCMAX-archives/superseded-plans-20261110/`；原始路径及 SHA256 见 `MANIFEST.json`，亦可从提交 `8f9d6bdb39` 恢复。现行架构以 `FHD/docs/ARCHITECTURE.md` 为准，审计评分以 `FHD/config/audit_benchmark_ssot.json` 为准；历史评估不得当作当前审计结果。

2026-11-10 支付文档整理：未登记的 Java 支付早期设计、SQLite 迁移和压测方案三份快照外置至 `~/XCMAX-archives/payment-plans-20261110/`；逐文件 SHA256 见该目录 `MANIFEST.json`，也可从提交 `8f9d6bdb39` 恢复。现行配置和迁移入口见 `成都修茈科技有限公司/MODstore_deploy/java_payment_service/README.md`，压测方案归档不代表压测已执行。

2026-11-10 集成整理：`FHD/CHANGELOG.md` 中 2026-07-12 及更早的历史 Unreleased 记录外置至 `~/XCMAX-archives/changelog-20261110-pr-integration/CHANGELOG-full-before-pr-integration.md`（完整原文 SHA256 `3d1d80c9335c6965c3b7a65129ed0f378e90ee34d4b46e0aa0b047abb8dbaded`，亦可从集成分支提交 `af00026e09` 恢复）。当前发布记录保留在原文件。

2026-10-24 工单交付整理：未登记且已被 v10 指南替代的 `成都修茈科技有限公司/docs/modstore/MOD_AUTHORING_GUIDE.md`（942 行）逐字节校验外置到 `~/XCMAX-archives/docs-20261024-ticket-mod-authoring/`，原文与 SHA256 见 `MANIFEST.json`；现行入口为 `FHD/docs/guides/MOD_AUTHORING_GUIDE.md`。

同轮未登记的六月修复快照 `docs/reports/FIXES.md` 与旧评分路线图 `docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md`（共 1,076 行）校验外置到 `~/XCMAX-archives/docs-20261024-ticket-history/`；完整原文、SHA256 及来源提交见 `MANIFEST.json`。归档保留历史未完事项，不构成修复完成声明；现行合同与评分口径以 SSOT 目录和 `FHD/config/audit_benchmark_ssot.json` 为准。

同目录保留未登记、零消费者的六月分支纳入快照 `docs/reports/git_hygiene_intake_2026-06-29.json`（1,622 行）及其校验记录；旧分支待办完整保留，该快照不是当前合入队列。

尽调 **工作区**（`Desktop/XCMAX`）不含下列实体目录；仅保留 `ARCHIVE_POINTER.md` 占位与恢复说明。

## 离线包（本机默认）

| 包 | 路径 | 说明 |
|----|------|------|
| 历史 `_archive` | `~/XCMAX-archives/xcmax-archive-202606/` | 根级历史快照（约 40GB） |
| M0 仓根卫生 | `~/XCMAX-archives/m0-20260605/` | 部署 zip、成都业务包等（~1.7GB） |
| **M0 FHD 大文件** | `~/XCMAX-archives/m0-fhd-bulk-20260605/` | models / installer / XcagiInstaller 等 |
| **M0 FHD 可重建依赖** | `~/XCMAX-archives/m0-venv-20260605/` | `.venv` / `.venv-mypy` / `frontend/node_modules`（~1.6GB） |
| **子仓 `.git` 备份（2026-06-08）** | `~/XCMAX-archives/nested-git-backup-20260608/` | 迁根仓 SSOT 前的 `FHD.git` / `MODstore_deploy.git` / `WechatDecrypt.git` |

### M0 已外置（工作区内为指针）

| 工作区路径 | 归档实体 |
|------------|----------|
| `FHD/XCAGI/models` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/models` |
| `FHD/XCAGI/installer` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/installer` |
| `FHD/XCAGI/distillation` | `.../m0-fhd-bulk-20260605/FHD/XCAGI/distillation` |
| `FHD/tools/XcagiInstaller` | `.../m0-fhd-bulk-20260605/FHD/tools/XcagiInstaller` |
| `FHD/tools/XcagiDownloader` | `.../m0-fhd-bulk-20260605/FHD/tools/XcagiDownloader` |
| `FHD/.venv` | `.../m0-venv-20260605/FHD/.venv-20260605-rebuild` |
| `FHD/.venv-mypy` | `.../m0-venv-20260605/FHD/.venv-mypy` |
| `FHD/frontend/node_modules` | `.../m0-venv-20260605/FHD/frontend/node_modules-20260605-rebuild` |

## 文档收敛归档（2026-09-10）

| 包 | 路径 | 说明 |
|----|------|------|
| **文档收敛归档** | `~/XCMAX-archives/docs-20260910/` | 208 篇历史/失效文档（53,447 行），加无引用回滚备份树 `docs/xcagi-dashboard/_agentic-bos-rollback/`（29 文件 / 6,242 行）。已 `git rm`，工作区不保留实体。校验和见 `.../docs-20260910/MANIFEST.txt`。 |
| **文档收敛归档（第二批）** | `~/XCMAX-archives/docs-20260910-batch2/` | 20 篇零入链/废弃文档（5,766 行）。已 `git rm`；校验和见 `.../docs-20260910-batch2/MANIFEST.txt`。 |
| **文档收敛归档（第三批）** | `~/XCMAX-archives/docs-20260910-batch3/` | 17 篇从任何活文档根不可达的文档（4,275 行）。已 `git rm`；校验和见 `.../docs-20260910-batch3/MANIFEST.txt`。 |
| **文档收敛归档（第四批）** | `~/XCMAX-archives/docs-20260910-batch4/` | `FHD/XCAGI/API_DOCS.md`（9,815 行）：由 `generate_api_docs.py` 从 FastAPI `openapi()` 生成的 API 快照，零消费者、可再生成。已 `git rm` 并加入 `FHD/XCAGI/.gitignore`；校验和见 `.../docs-20260910-batch4/MANIFEST.txt`。 |
| **文档收敛归档（第五批·营销）** | `~/XCMAX-archives/docs-20260910-batch5/` | `docs/marketing/` 未跟踪营销内容（2 篇 md + 封面 png + `gen_cover.py`）：非活文档且触发 `docs-ssot` WARN，移出工作区；校验和见 `.../docs-20260910-batch5/MANIFEST.txt`。 |
| **文档收敛归档（第六批·控制面收敛）** | `~/XCMAX-archives/docs-20260917-batch6/` | `specs/` 死树 8 篇（839 行，规格已被 [product-lines-3-plus-2.md](specs/product-lines-3-plus-2.md) 与三产品线控制面取代）+ 仓内只读运维归档 `archive/ops/` 10 文件（2,617 行，从未接通真实集群）。已 `git rm`；校验和见 `.../docs-20260917-batch6/MANIFEST.txt`。 |
| **文档收敛归档（第七批·过期架构计划）** | `~/XCMAX-archives/docs-20260925-self-heal/` | `FHD/docs/architecture/REFACTOR_DECOMPOSITION_PLAN.md` 与已标陈旧的 `ddd-refactoring-plan.md` 均未登记为 SSOT；恢复副本与 SHA256 见 `MANIFEST.txt`。 |
| **官网陈旧快照归档（2026-09-26）** | `~/XCMAX-archives/site-stale-20260926/` | `成都修茈科技有限公司/site/` 下 11 个 2026-09-09 官网旧版页面快照（约 1,100 行；内容定位停留在旧版官网，与根目录活页面重复且零引用）。已从工作区删除；`site/` 目录现仅保留 `site/data/`（SSOT 聚合产物）。校验和见 `.../site-stale-20260926/MANIFEST.txt`。 |
| **MODstore 旧部署指引归档（2026-09-27）** | `~/XCMAX-archives/docs-20260927-modstore-immutable/` | `local-to-remote-push-flow.md` 和 `remote-server-operations.md` 仍推荐 Docker/tar 覆盖生产，与当前 immutable release systemd 链冲突；原文及 SHA256 见 `MANIFEST.txt`。 |
| **Mac 发布旧部署指引归档（2026-09-27）** | `~/XCMAX-archives/docs-20260927-mac-release-obsolete/` | 旧版 `FHD/docs/guides/DEPLOYMENT_GUIDE.md` 和 MODstore 的 `xcagi-software-download.md` 已失效；原文及 SHA256 见 `MANIFEST.txt`。 |

本轮 Mac 发布旧状态快照：`~/XCMAX-archives/mac-release-status-20261008/MACOS_RELEASE_SSOT.edf274051.md`；原文校验和见同目录 `MANIFEST-edf274051.txt`。当前交付以 FHD/docs/MACOS_RELEASE_SSOT.md 为准。

## 恢复示例

2026-10-12 #2300：XCAGI 退役小程序规格、旧 Alembic/变更/安全说明及两个重复贡献政策（6 文件 / 1,519 行）已归档至 `~/XCMAX-archives/docs-20261012-pr2300-net-deletion/`；`MANIFEST.json` 记录原提交 `5f8de62c`、逐文件 SHA256 与行数，复制后逐项校验一致再删除。现行迁移公约见 `FHD/docs/guides/ALEMBIC_MIGRATION_GUIDE.md`，其余现行政策见 `FHD/CHANGELOG.md`、`FHD/SECURITY.md` 和 `FHD/.github/`。

2026-10-07 Windows 闭环整理：未登记 SSOT 的 2026-03-17 Excel 迁移快照 `FHD/docs/migration_report.md` 已外置至 `~/XCMAX-archives/docs-20261007-windows-closeout/`；原文与 SHA256 见该目录的 `MANIFEST.txt`，当前迁移入口以 `FHD/docs/MIGRATION_REGISTRY.md` 为准。

```bash
export VR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-venv-20260605"
rsync -a "$VR/FHD/.venv-20260605-rebuild/" "$(pwd)/FHD/.venv/"
rsync -a "$VR/FHD/.venv-mypy/" "$(pwd)/FHD/.venv-mypy/"
rsync -a "$VR/FHD/frontend/node_modules-20260605-rebuild/" "$(pwd)/FHD/frontend/node_modules/"
```

```bash
export AR="${XCMAX_ARCHIVE_ROOT:-$HOME/XCMAX-archives}/m0-fhd-bulk-20260605"
rsync -a "$AR/FHD/XCAGI/models/" "$(pwd)/FHD/XCAGI/models/"
```

## 运维脚本

```bash
bash FHD/scripts/move_archive_off_workspace.sh   # 根 _archive → xcmax-archive-202606
```

校验和：`~/XCMAX-archives/MANIFEST.txt`

**体积说明**（2026-06-05）：`du -sh Desktop/XCMAX` 约 **9.7G**（清 frontend 与归档重复的 `node_modules` 残留 ~2.6G 后；`FHD/.venv` **ln -s** `m0-venv-20260605`；含 `FHD/.git` ~**9.4G**）；尽调交付树（不含 `.git`）约 **~0.3G**。可重建依赖在 `m0-venv-20260605`（`npm ci` / rsync 恢复）。详见 `FHD/docs/CLAIMED_VS_ACTUAL.md`。

2026-10-09 原工单支持指引归并：未登记的 `FHD/docs/customer/CUSTOMER_SUPPORT.md` 与 `FHD/docs/guides/DESKTOP_DATABASE_DELIVERY.md` 外置至 `~/XCMAX-archives/docs-20261009-original-ticket-support/`，原文及 SHA256 见 `MANIFEST.json`；当前入口为数据安全、双端发布与客服工单总线 SSOT。

2026-10-11 发布断点收口：未登记的旧 `FHD/docs/DEPLOYMENT.md`、`deploy/RELEASE_CHECKLIST.md` 和 2026-06-05 已结束的 `ai-agent-v1-plan.md` 外置至 `~/XCMAX-archives/docs-20261011-delivery-breakpoints/`；原文与 SHA256 见 `MANIFEST.json`。旧仓库、K8s 与 demo 完成声明不作为本轮发布依据；当前入口为双端发布和客服工单 SSOT，历史 demo 与证据仍保留。 同轮将未登记旧 `FHD/tools/XcagiInstaller/README.md` 外置到 `~/XCMAX-archives/docs-20261011-delivery-breakpoints/windows-installer-readme/README.md`；原文 SHA256 `dadea781b3b40fe9cd8273bb03cf1f7e64f48cdc3531c863187a1c9e992de5dc`，逐字节校验与恢复指引见同目录 `MANIFEST.json`。

同轮将未登记且仍含旧版安装与首启规则的 `FHD/docs/guides/PRODUCT_USER_FLOW.md` 校验外置到上述归档；唯一设置顺序与权益边界并入既有 `DELIVERABLE_PRODUCT.md`，交付判定统一指向发布与工单 SSOT，原文保留于 `MANIFEST.json`。

## 证据与根目录杂物外置（2026-10-25）

| 包 | 路径 | 说明 |
|----|------|------|
| **证据 bulk（非 materialization）** | `~/XCMAX-archives/evidence-bulk-20261025/` | 未登记进 `evidence-materialization.json` 的 `FHD/docs/evidence` 媒体、能力中心 generated 公开副本、`appstore-screenshots/`、`宣传资料/`、成都 ≥512KiB 营销媒体（含 `public/hero-video.mp4`）。已 git rm；校验见 `MANIFEST.json`。 |
| 临时 symlink | （已删除） | 根目录 `.codex_modstore_archfix` 已从 git 树移除。 |

**与 #2544 共存**：`evidence-materialization.json` 登记的 FHD 源媒体（约 289MB）与 `retained_sources` 仍留在 git，供 `evidence_assets.materialize` 校验/生成公开别名；能力中心运行时仍优先 COS 预签名。

**保留（有意）**：根目录 `XCAGI-*.html`；`太阳鸟/` 说明；`成都修茈科技有限公司/` 活代码；materialization 源媒体。

2026-10-26 交接整改：`成都修茈科技有限公司/docs/planning/腾讯云Pages部署指南.md` 为根目录同名文件的逐字重复副本（342 行），无该路径消费者；校验外置至 `~/XCMAX-archives/docs-20261026-duplicate-pages-guide/`。保留员工清单所用根目录原件，原文、来源提交及 SHA256 见 `MANIFEST.json`；未删除测试或改变部署流程。

## 实验残留清退（2026-11-06）

| 包 | 路径 | 说明 |
|----|------|------|
| **sandbox-app 实验壳** | `~/XCMAX-archives/experiment-residue-20261106/FHD/sandbox-app/` | `FHD/sandbox-app`（19 文件 / 1,163 行）全仓零引用：不参与任何构建入口、CI 工作流、pytest 收集或发布产物。已 `git rm`；逐文件 SHA256 与来源提交见 `MANIFEST.json`。 |

| **过期历史快照文档** | `~/XCMAX-archives/docs-20261106-stale/` | 20 篇 / 1,256 行，全部由 `FHD/scripts/dev/docs_triage.py report` 判定为 `archive_reason=historical-snapshot`（自述日期快照、零入链、非 SSOT 登记、非运行时资产）。已 `git rm`；逐文件 SHA256 见 `MANIFEST.json`。 |

**同轮保留待判（规则可命中但不宜直接删除）**：`FHD/app/security/SSOT.md`、`FHD/app/neuro_bus/BOUNDARY.md` 是安全/总线边界映射，属治理缺口（应登记 SSOT 而非归档）；`FHD/docs/guides/MOBILE_ANDROID_STORE_COMPLIANCE.md` 是 Android 商店提审清单，属移动端交付依赖；`docs/MUTATION_TESTING_SCOPE.md` 与 `docs/security/aiopen-*-20261028.md` 是近期口径与安全审计记录；两个 `MANIFEST_POINTER.md` 是归档资产恢复指针。以上 7 篇不作为本轮归档对象。

**同轮评估但保留（承重，不可作为残留清退）**：`FHD/sunbird-console` 是 `FHD/frontend/sunbirdConsole.vite.config.js` 的构建输入；`FHD/AMIN` 经 `@amin` 别名进入前端打包；`FHD/mobile-flutter-poc` 由 `.github/workflows/fhd-ci-mobile-flutter.yml`、`fhd-release-android.yml`、`fhd-release-ios.yml` 驱动，属移动端交付链路；`FHD/tests/odoo_absorption` 与 `FHD/tests/langgraph_absorption` 是运行中的契约/边界回归测试；`FHD/rasa` 与 `FHD/XCAGI/rasa` 是 `app/ai_engines/rasa/nlu_service.py` 模型发现与再训练的种子配置。目录名带 poc/absorption 属命名债，不是死代码。

2026-11-09：过期迁移指南原文与未登记的 2026-06 产品打磨清单已归档至 `~/XCMAX-archives/docs-20261109-pr3110/`；迁移入口保留在 `FHD/docs/guides/ALEMBIC_MIGRATION_GUIDE.md`。

2026-11-10：未登记、无仓库引用的 OCR 字体识别历史实现说明外置至 `~/XCMAX-archives/docs-20261110-ocr-history/`；原路径及 SHA256 见 `MANIFEST.json`。

2026-11-10：未登记、无仓库引用的旧 Windows 验证报告及 mypy 状态快照外置至 `~/XCMAX-archives/docs-20261110-historical-reports/`；原路径及 SHA256 见 `MANIFEST.json`。

同日，未登记的旧架构退役看板及审计收口说明外置至 `~/XCMAX-archives/docs-20261110-historical-architecture/`，原路径及 SHA256 见 `MANIFEST.json`。

同日，未登记且含失效报告路径的 OpenAPI 旧指南外置至 `~/XCMAX-archives/docs-20261110-openapi-old-guide/`；校验入口为 `FHD/scripts/tools/check_openapi_consistency.py --help`。

同日，覆盖率文档的旧测量快照外置至 `~/XCMAX-archives/docs-20261110-coverage-snapshot/`；现行文档指向可执行门槛与测量入口。

同日，含过期 Node 要求和 API 示例的旧前端 README 外置至 `~/XCMAX-archives/docs-20261110-frontend-readme/`；现行入口以 `package.json` 与 Vite 配置为准。
