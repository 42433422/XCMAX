# XCMAX 历史与大文件归档指针

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
| **官网陈旧快照归档（2026-09-26）** | `~/XCMAX-archives/site-stale-20260926/` | `成都修茈科技有限公司/web/site/` 下 11 个 2026-09-09 官网旧版页面快照（约 1,100 行；内容定位停留在旧版官网，与根目录活页面重复且零引用）。已从工作区删除；`site/` 目录现仅保留 `site/data/`（SSOT 聚合产物）。校验和见 `.../site-stale-20260926/MANIFEST.txt`。 |
| **MODstore 旧部署指引归档（2026-09-27）** | `~/XCMAX-archives/docs-20260927-modstore-immutable/` | `local-to-remote-push-flow.md` 和 `remote-server-operations.md` 仍推荐 Docker/tar 覆盖生产，与当前 immutable release systemd 链冲突；原文及 SHA256 见 `MANIFEST.txt`。 |
| **Mac 发布旧部署指引归档（2026-09-27）** | `~/XCMAX-archives/docs-20260927-mac-release-obsolete/` | 旧版 `FHD/docs/guides/DEPLOYMENT_GUIDE.md` 和 MODstore 的 `xcagi-software-download.md` 已失效；原文及 SHA256 见 `MANIFEST.txt`。 |
| **客户/品牌资料外置（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/` | `太阳鸟/`（README、安装说明）与 `宣传资料/`（企业介绍 PPT、路演流程清单图）已迁入该仓并按 `ledger/MIGRATION_LEDGER.csv` A12 逐文件校验（状态 `verified`），本仓已 `git rm`。 |
| **docs 冗余快照清理（2026-11-12）** | 同上 `sources/xcmax/`（`SECURITY_CLEANUP_REPORT.md` 见 A10） | 已删 `docs/reports/FIXES.md`、`docs/reports/git_hygiene_intake_2026-06-29.json`、`docs/roadmap/AI_PLATFORM_9_SCORE_ROADMAP.md`（零入链历史快照）；`docs/reports/SECURITY_CLEANUP_REPORT.md` 私有副本已在 xcmax-Li。 |
| **根目录证据/构建产物外置（2026-11-12）** | `~/XCMAX-archives/xcmax-root-evidence-20261112/` | 迁出 9 个未入库目录：`windows-evidence-1.0.0.5`、`windows-evidence-20260926/27/28`、`windows-acceptance-r2`、`xcagi-src-e3ac9f`、`xcagi-tmp`、`xcagi-w06-data`、`xcagi-nsis-bcj`，以及 `_archive/{branch-retirement-20261106,devfleet-comm}`；共约 1.7GB，逐目录文件数与字节总量核对一致。同时删除空壳 `cache-spill/`、`saved_analyses/`、`xcagi-release-c46f938/` 与 0 字节 `modstore-test.db`。`_archive/windows-closeout-20261007` 因权限（`xcshare` 独占）未能读取，保留原地。 |
| **outputs 打包产物外置（2026-11-12）** | `~/XCMAX-archives/xcmax-root-evidence-20261112/outputs/` | 迁出未入库的 `FHD-src-1.0.0.5-20261110.tar.gz`（78MB 源码包）、`byok-auto-match-module/` 与同名 `.zip`，字节核对一致；`outputs/` 仅保留已入库的 `01a05bb6-…/` 交付表。 |
| **临时报告与锁文件清理（2026-11-12）** | `~/XCMAX-archives/xcmax-root-evidence-20261112/reports/` | 未入库的根 `reports/` 两份诊断（`ticket-triage-20261022.md`、`ci-acceleration/2026-10-12-ci-acceleration.md`，零入链）已外置；`test_reports/` 仅含运行锁 `.work_orders.lock`，已删除并移除空目录。 |
| **release/ 过期打包桩移除（2026-11-12）** | `~/XCMAX-archives/xcmax-root-evidence-20261112/release/` | `release/` 仅含 v10.0.0 的 `README.txt`/`MOBILE_VERSION.md` 桩与陈旧 `release/VERSION`(`0.0.1`)，实际 APK/HAP 从未入库，且与 `FHD/VERSION.md`（`1.0.0.5`）构成版本漂移。已外置并 `git rm`；版本唯一权威来源为 `FHD/VERSION.md`。 |
| **过期 runbook 回流清理（2026-11-12）** | `~/XCMAX-archives/docs-20260927-modstore-immutable/`、`~/XCMAX-archives/docs-20260927-mac-release-obsolete/` | `MODstore_deploy/docs/runbooks/` 下 `local-to-remote-push-flow.md`、`remote-server-operations.md`、`xcagi-software-download.md` 三份未跟踪文件属 2026-09-27 已归档的旧部署指引回流（推荐 Docker/tar 覆盖生产），归档区已有副本，本次直接删除。`成都修茈科技有限公司/ops/scripts/__pycache__/` 一并清除。 |
| **App Store 截图素材外置（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/appstore-screenshots/` | 整个 `appstore-screenshots/`（26 文件 / 12.2MB：`live/`、`2.3.3-accurate-metadata/`、`upload/`、`upload-ipad-13/` 与 4 张手机标准图）迁入私有仓并按台账 A13-001…026 逐文件校验（status `verified`）；本仓已 `git rm`，README 头部引用同步移除。 |
| **软著申请材料外置（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/FHD/docs/legal/` | `FHD/docs/legal/`（46MB / 53 文件：软著 V10 鉴别材料、用户手册、完整源代码 dump 与生成脚本）迁入私有仓，台账 A14-001 记录变更后的源码 dump（13,616,052B / SHA256 `a0728eba…`），全目录 53 文件复比 0 不匹配；本仓已 `git rm`，`check_net_deletion.py` 与 `check_broad_except_gate.py` 的 legal 排除项同步移除。 |
| **验收证据素材外置（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/FHD/docs/evidence/` | `FHD/docs/evidence/`（2629 文件 / 410,103,321B，含 165 个验收录像）整目录迁入私有仓，归档内 `MANIFEST.txt` 记录逐文件 SHA-256，全量复比 0 不匹配；台账 A15-001。本仓已 `git rm`，仅保留 [README 指针](FHD/docs/evidence/README.md)。`build_capability_center.py` 新增 `XCAGI_EVIDENCE_ROOT` 覆盖：未设置时 `--check` 输出 WARN 跳过证据校验、生成模式直接失败；官网仍使用已入库的公开副本 `成都修茈科技有限公司/web/capabilities/assets/evidence/`。 |
| **FHD 杂项文件外置（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/FHD/`（`SCRATCH_MANIFEST.txt`） | `FHD/misc/`（8 个零引用开发素材：网格查看器 HTML、标签样本、`longxiang_content.txt`、下载图等）、`FHD/static/VBCABLE_Driver_Pack45.zip`（与 misc 内同名包重复）、`FHD/codex_super_employee/messages.jsonl`、`FHD/cursor_super_employee/messages.jsonl`（本地超级员工测试消息）共 11 文件 / 2,763,212B 已迁入私有仓，逐文件复比 0 不匹配；台账 A16-001。本仓已 `git rm`。仅两处 Windows 本地路径（`E:/FHD/...`）在开发脚本中以字符串形式提及，删除不影响运行。 |
| **FHD 数据/实验目录清理（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/FHD/`（`SCRATCH_MANIFEST-A17.txt`） | `FHD/integrations/vue/`（6 文件，DB 读令牌集成片段；前端 `@/fhd/dbTokenHeaders` 已有同源实现，目录零引用）与 `FHD/delivery/sunbird-seed/`（5 文件 / 408KB，太阳鸟考勤种子数据；该客户定制安装渠道已 fail-closed 停用，`build-sunbird-seed.py` 缺数据时会明确报错）共 11 文件 / 426,331B 迁入私有仓，逐文件复比 0 不匹配，台账 A17-001。另删除 `FHD/etl/error_exports/` 的 3 份运行期错误导出 CSV（UUID 命名、零引用、可再生成）。 |
| **FHD 历史迁移报告归档（2026-11-12）** | 私有迁移仓 [`42433422/xcmax-Li`](https://github.com/42433422/xcmax-Li) `sources/xcmax/FHD/docs/historical/migration_report.md` | `FHD/docs/migration_report.md`（6,158B，2026-06 的「AI 助手」Excel 能力并入记录）为历史快照，无活文档入链；迁入私有仓，SHA256 `7221030d…` 复比一致，台账 A18-001。另删除 0 字节空文件 `FHD/docs/MIGRATION_v2_DROP_PLAN.md`。 |

## 恢复示例

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
