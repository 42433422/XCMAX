# 声称 vs 实际（CLAIMED_VS_ACTUAL）

> **维护节奏**：每月首个工作日更新（T66）  
> **数据源**：文档声称来自 `BUSINESS_MODEL.md` / `SLO.md` / `CHANGELOG.md`；实际列需 Grafana、业务库或 e2e 证据，**无证据填「未验证」**。  
> **M0 仍缺（仅 3 项）**：[`M0-remaining-gaps.md`](M0-remaining-gaps.md) · staging SLO 阻塞见 [`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) **T36–T37**（最早 2026-09）。

## 使用说明

| 列 | 含义 |
|----|------|
| **声称** | 文档或对外材料中的数字/能力描述 |
| **实际** | 可复现证据（截图路径、查询、CI artifact）或 `未验证` |
| **差距** | `一致` / `夸大` / `滞后` / `未测` |
| **负责人** | 2026-07 起建议由列出的角色跟进 |

---

## SLO 与平台指标（来源：[`SLO.md`](SLO.md)）

| ID | 声称 | 实际 | 差距 | 负责人 | 证据 |
|----|------|------|------|--------|------|
| SLO-API-01 | API 可用性 99.9%（目标）；基线 99.94% | **阻塞 T36–T37**：staging **未验证**（需 7 天流量或 k6 + PNG）；本地 compose 可复现（脚本 + JSON，**无** 7 天曲线） | 未测 | SRE | 本地：[`local_stack_up.sh`](../scripts/observability/local_stack_up.sh) → [`evidence/slo/`](evidence/slo/)；staging：[`STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md) · [`BLOCKERS.md`](../../specs/BLOCKERS.md) T36–T37（2026-09） |
| SLO-API-02 | 登录 P95 &lt; 500ms；基线 312ms | **阻塞 T36–T37**：staging **未验证**；本地栈未宣称 P95 基线 | 未测 | SRE | 同上 · [`M0-remaining-gaps.md`](M0-remaining-gaps.md) #1 |
| SLO-API-03 | API 错误率 &lt; 0.1%；基线 0.06% | **阻塞 T36–T37**：staging **未验证** | 未测 | SRE | 同上 |
| SLO-AI-01 | 聊天首包 P95 &lt; 1500ms；基线 1080ms | **阻塞 T36–T37**：staging **未验证** | 未测 | AI 平台 | [`evidence/slo/`](evidence/slo/) · panel `xcagi-slo:3` · 禁止无 PNG 填数 |
| SLO-BUS-01 | NeuroBus 投递 99.95%；基线 99.97% | **阻塞 T36–T37**：staging **未验证** | 未测 | 平台 | [`evidence/slo/`](evidence/slo/) · panel `xcagi-slo:7` |
| **可观测性栈** | M0：Grafana 四域 + staging 7 天 | **本地**：`local_stack_up.sh --check-only` 通过；**Docker SLO 四 PNG 未导出**（[`M0-remaining-gaps.md`](M0-remaining-gaps.md) #3）。**staging**：**阻塞 T36–T37** — 7 天流量与正式基线 **未验证**（禁止伪造曲线） | 未测 | SRE | [`scripts/observability/README.md`](../scripts/observability/README.md) · [`BLOCKERS.md`](../../specs/BLOCKERS.md) T36–T37 |
| e2e 关键链路 | 5 条 Playwright 在 CI 稳定通过 | **M0 已验证（2026-06-05）**：本地 `E2E_VITE_MOCK_API=1` + Vite :5001 → `npm run test:e2e:p0` **14/14 passed**（连续 2 次本地复现，约 36s）（`critical-paths` 5 链 + `plan2026-skeleton` 5 链 + `smoke` 4）；截图 [`evidence/e2e/01–05.png`](evidence/e2e/README.md)。CI：仓根 [`e2e.yml`](../../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../.github/workflows/e2e-playwright-reusable.yml)；`E2E_VITE_MOCK_API=1` 契约 mock + 可选 Postgres 全栈 | 一致 | 前端 + QA | [`frontend/e2e/README.md`](../frontend/e2e/README.md)、[`evidence/e2e/`](evidence/e2e/) |

---

## 商业模式（来源：[`../XCAGI/BUSINESS_MODEL.md`](../XCAGI/BUSINESS_MODEL.md)）

| 主题 | 声称 | 实际 | 差距 | 负责人 | 证据 |
|----|------|------|------|--------|------|
| Mod 商店分成 | 平台抽成 30% | **未验证**（**非** T36–T37）；无真实商家 / 0.01 元订单 | 未测 | 商务 + MODstore | [`mod-merchant-pilot.md`](mod-merchant-pilot.md) · [`evidence/mod/`](evidence/mod/) · [`M0-remaining-gaps.md`](M0-remaining-gaps.md) #2 |
| Token 月费档位 | ¥999–9,999/月 | 未验证 | 未测 | 商务 | |
| AI 自动审单命中率 | 文档隐含「AI 员工」自动化 | 未验证 | 未测 | 业务 + 数据 | *待 T55–T57 月报* |

---

## 工程与版本（来源：CHANGELOG / V10_ACCEPTANCE）

| 主题 | 声称 | 实际 | 差距 | 负责人 | 证据 |
|----|------|------|------|--------|------|
| `*_app_service_v2.py` 数量 | 历史 CHANGELOG / V10_ACCEPTANCE 曾写「0 / 已清零」 | **23** 个应用服务模块（见下表）；决策为**保留**作应用层 SSOT 后缀 | 夸大（已对齐） | 后端架构 | 本表 + [`V10_ACCEPTANCE.md`](V10_ACCEPTANCE.md) |
| mypy `ignore_errors` 目录数 | ≤ 6（[`plan-2026-06.md`](../../specs/plan-2026-06.md) M0） | **6**（`pyproject.toml` 宽口径 `module` 条，2026-06-05；自 **12→6**） | 一致 | 后端架构 | 自 plan 基线 **18** 分批收口；`app.routes.*` / `ai_chat` 移出宽口径；[`MYPY_BATCH_STATUS.md`](MYPY_BATCH_STATUS.md) |
| 全量覆盖率 | ≥ 88%（plan 目标） | **77.44%**（`metrics/coverage-dual-summary.json`，2026-06-04） | 一致 | QA | CI `fail_under=77` |
| 工作区体积（`du -sh .`） | ≤ 8 GB（[`plan-2026-06.md`](../../specs/plan-2026-06.md) M0） | **7.8G**（2026-06-05；外置 ~/XCMAX-archives/m0-fhd-bulk-20260605/；XCAGI models/installer、tools/XcagiInstaller 等为 ARCHIVE_POINTER；未删 .git 历史） | 一致 | 发布工程 | 迁出前 22 GB；见仓根 ARCHIVE_POINTER.md |
| 仓根/FHD 散落脚本 | 无 `fix_*`/`check_*`/`probe_*` 于仓根或 `scripts/` 根 | **已收敛（2026-06-05）**：`maxdepth 2` 无散落；一次性脚本在 [`scripts/_archived/`](../scripts/_archived/)、探针在 [`scripts/dev/diagnostics/`](../scripts/dev/diagnostics/)、CI 在 [`scripts/ci/`](../scripts/ci/) | 一致 | 发布工程 | [`scripts/README.md`](../scripts/README.md) |
| Android 原生 | README 曾写 Kotlin Compose 已交付 | Kotlin Compose **实验骨架**已存在；非签约级移动产品 | 滞后 | 移动端 | [`mobile-android/README.md`](../mobile-android/README.md) |

---

## `_v2` 应用服务实际清单（23 个）

> **决策（2026-06）**：全部 **保留** 为 `app/application/*_app_service_v2.py` 应用服务层模块；合并到无后缀名称为长期目标，不在 v10 宣称「已清零」。

| 文件 | 去留 | 备注 |
|------|------|------|
| `ai_chat_app_service_v2.py` | 保留 | AI 对话应用服务 |
| `auth_app_service_v2.py` | 保留 | 认证应用服务 |
| `conversation_app_service_v2.py` | 保留 | 对话域 |
| `customer_app_service_v2.py` | 保留 | 客户域 |
| `excel_vector_app_service_v2.py` | 保留 | Excel 向量 |
| `extract_log_app_service_v2.py` | 保留 | 提取日志 |
| `file_analysis_app_service_v2.py` | 保留 | 文件分析 |
| `inventory_app_service_v2.py` | 保留 | 库存 |
| `material_app_service_v2.py` | 保留 | 物料 |
| `ocr_app_service_v2.py` | 保留 | OCR |
| `order_app_service_v2.py` | 保留 | 订单 |
| `print_app_service_v2.py` | 保留 | 打印 |
| `product_app_service_v2.py` | 保留 | 产品 |
| `product_import_app_service_v2.py` | 保留 | 产品导入 |
| `purchase_app_service_v2.py` | 保留 | 采购 |
| `shipment_app_service_v2.py` | 保留 | 发货 |
| `template_app_service_v2.py` | 保留 | 模板 |
| `unit_products_import_app_service_v2.py` | 保留 | 单位产品导入 |
| `user_app_service_v2.py` | 保留 | 用户 |
| `user_memory_vector_app_service_v2.py` | 保留 | 用户记忆向量 |
| `user_preference_app_service_v2.py` | 保留 | 用户偏好 |
| `wechat_contact_app_service_v2.py` | 保留 | 微信联系人 |
| `wechat_task_app_service_v2.py` | 保留 | 微信任务 |

---

## 未 SSOT 化的 `fastapi_routes` 顶层文件（Phase 1 迁移目标）

> 已迁入 `domains/*` 的域见 [`domain_registry.py`](../app/fastapi_routes/domain_registry.py)。下表为 **T1.1–T1.7** 登记项（迁移中或待迁）。

| 顶层文件 | 目标域 | 状态 | 原因 |
|----------|--------|------|------|
| `finance.py` | `domains/finance/routes.py` | **已迁**（顶层 re-export shim） | T1.1 |
| `inventory.py` | `domains/inventory/routes.py` | **已迁** | T1.2 |
| `ocr.py` | `domains/ocr/routes.py` | **已迁** | T1.3 |
| `rbac.py` | `domains/rbac/routes.py` | **已迁** | T1.4 |
| `lan_routes.py` | `domains/lan/user_routes.py` | **已迁** | T1.5 |
| `lan_admin_routes.py` | `domains/lan/admin_routes.py` | **已迁** | T1.5 |
| `lan_settings_routes.py` | `domains/lan/settings_routes.py` | **已迁** | T1.5 |
| `xcmax_admin.py` | `domains/xcmax_admin/routes.py` | **已迁** | T1.6 |
| `market_account.py` | `domains/market_account/routes.py` | **已迁** | T1.7 |
| `wechat_decrypt_routes.py` | `domains/wechat_decrypt/routes.py` | **已迁** | T1.7 |

---

## 2026-06 首轮月更（T66 — 待填）

> 每月首个工作日由负责人填写；无证据保持「待填」，禁止编造数字。

| 主题 | 声称（摘要） | 实际 | 差距 | 填表人 | 证据路径 |
|------|--------------|------|------|--------|----------|
| SLO 全表复核 | 见上文 SLO 节 | **阻塞 T36–T37**（staging）；本地 Docker 四 PNG 待补 | — | SRE | [`M0-remaining-gaps.md`](M0-remaining-gaps.md) #1、#3 |
| Mod 分成 30% | BUSINESS_MODEL | **待填**（需试点订单） | — | 商务 | [`mod-merchant-pilot.md`](mod-merchant-pilot.md) · `evidence/mod/` |
| AI 审单命中率 | ≥70%（计划 P2-3） | **待填** | — | 业务 | [`AI_BUSINESS_EVIDENCE.md`](AI_BUSINESS_EVIDENCE.md) |
| 合同提醒触达 | ≥90%（计划 P2-3） | **待填** | — | 业务 | 同上 |
| DORA 四月指标 | Lead time / deploy freq 等 | **待填** | — | 发布工程 | [`metrics/dora-monthly-202606.md`](../metrics/dora-monthly-202606.md) |
| Pro-mode 默认曝光 | 文档「AI 员工」沉浸 UI | **待填**（建议：默认关闭） | — | 产品 | [`PRO_MODE_INVESTMENT_REVIEW.md`](PRO_MODE_INVESTMENT_REVIEW.md) |

---

## 更新记录

| 日期 | 更新人 | 摘要 |
|------|--------|------|
| 2026-06-04 | 计划执行 worker | 初版模板；实际列均为「未验证」直至 staging/业务数据接入 |
| 2026-06-04 | 计划执行 worker | T66 首轮「待填」行入表；待月度负责人填写 |
| 2026-06-04 | align-claimed-vs-actual | 新增 _v2 清单（23）、fastapi_routes 未 SSOT 表；工程节覆盖率/Android 对齐 |
| 2026-06-05 | M0 bulk 外置 worker | m0-fhd-bulk-20260605；仓根 du 达标；models/installer/XcagiInstaller 指针 |
| 2026-06-05 | M0 仓根卫生 worker | 工作区体积事实行；e2e 行已含 M0 验证 |
| 2026-06-05 | M0 外置 bulk worker | `m0-fhd-bulk-20260605`；仓根 **8.6 GB**；models/installer/XcagiInstaller 已指针化 |
| 2026-06-05 | M0 归档迁出 worker | `~/XCMAX-archives/m0-20260605/`；工作区 `du` 22→20 GB |
| 2026-06-05 | mypy P1-1 worker | `ignore_errors` 宽口径 **12→6**（plan SSOT 18→6）；`pyproject.toml` + `app/routes/*` |
| 2026-06-05 | M0 脚本/env worker | `fix_*`/`check_*` 迁入 `scripts/*`；`.env*` maxdepth2=5；[`ENV_FILES.md`](ENV_FILES.md) |
| 2026-06-05 | observability worker | SLO 行区分「本地 compose 可复现」vs「staging 未验证」；证据链 `docs/evidence/` |
| 2026-06-05 | observability subagent | `--check-only` 通过；Docker 不可用→无 PNG；CLAIMED 可观测行区分 local/staging，禁止伪造 7 天 |
| 2026-06-05 | M0 docs worker | `mod-merchant-pilot.md`、`M0-remaining-gaps.md`、`evidence/mod/`；SLO/Mod 行对齐 BLOCKERS T36–T37 |
