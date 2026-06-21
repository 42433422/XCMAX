# XCMAX「提升到 9/10」作战计划（TO-9 PROGRAM）

> **SSOT**：本文件是"从约 6/10 提升到 9/10"的唯一执行台账。证据来自一次多代理穷尽式审计 +
> 对安全漏洞的对抗式验证（2026-06-21）。所有"已实测"的数字均来自 `FHD/.venv`（Py3.11，CI 等价依赖）
> 与前端 node18 实跑，**不引用任何过期/退役口径**（见 [CLAIMED_VS_ACTUAL.md](../CLAIMED_VS_ACTUAL.md)）。
>
> 状态图例：✅ 本批次已落地并验证 · 🔭 待办（带工时估算）· ⚠️ 需先满足前置条件

## 0. 基线与目标（实测）

| 维度 | 起点 | 本批次后 | 9/10 目标 | 数据源 |
|---|---|---|---|---|
| 后端架构/代码质量 | 4.5 | ~6 | 9 | 见 §1 |
| 测试 | 5 | ~6 | 9 | 见 §2 |
| 前端 | 6.5 | ~7.5 | 9 | 见 §3 |
| 文档诚实度/对外口径 | 4.5 | ~8 | 9 | 见 §4 |
| CI/CD 与运维 | 8 | ~8.5 | 9 | 见 §5 |
| 领域层真实落地 | 4.5 | ~5 | 9 | 见 §6 |
| 安全 | 6 | ~7 | 9 | 见 §7 |

> 注：分数提升按"已验证的真实改动"计，不按文档堆叠。后端覆盖率实测 **行 85.07% / 分支 74.22%**
> （`metrics/coverage-dual-summary.json#committed_head`），目标 90%/85%（Q4）。

---

## 1. 后端架构与代码质量

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| A1 | `tool_spec.py` 数据外置（3886→495 行，三大 schema 字典 → `tool_spec_data/` 包 + re-export shim） | ✅ | — | `build_tool_specs_v2()`=147、三字典长度前后一致、18 测试绿、ruff 干净 |
| A7 | `tool_spec.py` 魔法值表驱动化（cost/permission/risk/timeout → `tool_spec_data/constants.py`） | ✅ | — | 全 tool×action×risk 笛卡尔积等价断言 0 mismatch |
| A6 | 15 处裸 `except:` → `except Exception:`（7 文件）+ resources 遗留 2 处；BLE001 显式登记 | ✅ | — | `grep 'except:' app/`=0、ruff 干净 |
| — | 清理 13 个**预存** ruff 真 bug（5 个 F821 NameError：`json`/`session_facade`/`_LAST_TOOL_RESULT`，5 个 F401，3 个 BLE001） | ✅ | — | `ruff check app/` = All checks passed! |
| A2 | `tools_workflow_registered.py`（2359 行）按 router 域拆到 `tools_workflow/` 包，原文件逐一 re-export | 🔭 | 4h | 32 个 `_registered_router_*` 可导入、`_REGISTERED_WORKFLOW_ROUTERS` 非空、深路径测试绿 |
| A3 | `ai_chat_app_service.py`（3550 行/60 方法）抽 Excel 导入推断族（~18 纯函数）到 `chat/excel_import_inference.py` | 🔭 | 5h | 模块级符号（LLMWorkflowPlanner 等 patch 目标）保留、相关 ramp 测试绿 |
| A4 | `xcmax_admin.py`/`mobile_api_extensions.py` 拆子路由 + 打破 mobile_api 循环导入 | 🔭 ⚠️ | 6h | 路由数不变、`-k 'mobile or xcmax or admin'` 不回归（风险高，置于 A1/A2 后） |
| A5 | DI registry 引入 `Protocol` 端口（先 3 个高频服务） | 🔭 | 3h | registry 类型注解面向 Protocol、运行期工厂不变 |

**剩余工时小计：~18h**

---

## 2. 测试

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| T1 | 修复 `[tool.mutmut]`：1.x 旧键(runner/dict_synonyms)→3.x 有效键(source_paths/also_copy/pytest_add_cli_args*) | ✅ | — | 配置解析正常；审计已实跑 app/di 62 变体/25 killed |
| T2 | `.gitignore` 忽略 `mutants/` 与 `.mutmut-cache`（运行时 ~80M 副本） | ✅ | — | grep 命中 |
| T4 | `coverage_ramp` marker + conftest 自动打标钩子（按文件名） | ✅ | — | `-m coverage_ramp` 收集 5413 用例、`-m 'not coverage_ramp'` 16171 用例 |
| T3 | 修 `mutation-smoke.yml` 使其 60min 内完成 + 固定 mutmut==3.6.0 + 起步 `--threshold 40` | 🔭 | 1h | YAML 合法（真跑需 GH Actions） |
| T5 | `coverage_real.sh`：报告剔除 coverage_ramp 后的"诚实覆盖率"，写入 metrics 新字段 | 🔭 | 2.5h | 产出 real_line/real_branch_pct（独立 json，不喂棘轮） |
| T6 | 补 top-3 高分支缺口核心模块（tools_workflow 缺221 / ai_chat 缺181 / employee_specialized 缺176，br仅42%） | 🔭 | 8h | 三文件 br% 上升，带 if/else+except 双分支断言 |
| T7 | 补次级缺口（customer_app_service br26.7%、db/validators br43.3% 等，合计 ~455 分支） | 🔭 | 10h | 对应 `tests/test_application/test_<svc>.py` 覆盖上升 |
| T8 | 棘轮：分支 floor Q3 阶梯 bump（73→80）+ mutation 杀死率棘轮（只升不降） | 🔭 ⚠️ | 3h | 须"全绿+真实测量"后 `coverage_ratchet.py --bump` |
| T9 | 后端 mutation 门禁接入 PR CI（增量变异，仅测改动文件） | 🔭 ⚠️ | 4h | 依赖 T1；起步 continue-on-error 软门禁 |

**剩余工时小计：~28.5h**（其中 T6/T7 的分支覆盖 73.6%→85% 是最大块）

---

## 3. 前端

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| FE-1 | 修复 `useChatMessageUi.ts:84` 解析错误（`})`→`}`）——它让 `vue-tsc` **从未跑完过** | ✅ | — | TS1128 1→0 |
| FE-2 | 清零 17 个被掩盖的真实类型 bug（含 `isRoutableClientErpModId` 被误删→运行时崩溃、重复声明覆盖语义、重复 import、patch 类型过窄） | ✅ | — | `vue-tsc --noEmit` error 17→0；106 相关单测绿 |
| FE-3 | 开启 `noUnusedParameters`（实测仅 +4 错误，加 `_` 前缀） | ✅ | — | error 仍 0 |
| FE-4 | 清死代码后开启 `noUnusedLocals`（实测 +119，集中在 8 文件） | 🔭 | 12h | 临时 tsconfig 统计 TS6133/6192 归零后 flip |
| FE-5 | `EmployeeWorkspaceScene.vue`（4420 行）抽 `useSelfEvolutionLoopRuntime` composable（先补特征测试） | 🔭 ⚠️ | 16h | 新 composable 单测绿、组件 script ~1322→~600 行、tsc 不增 |
| FE-6 | 启用 i18n 消化 142 文件硬编码中文 + `vue/no-bare-strings-in-template` ESLint 门禁 | 🔭 | 10h | 含中文 vue 文件数下降 |
| FE-7 | 引入 `eslint-plugin-vuejs-accessibility` a11y 门禁 | 🔭 | 3h | 规则生效，核心组件升 error |
| FE-8 | 收敛 862 处测试 `any`（建 `test-utils/types.ts` 工厂） | 🔭 | 8h | 测试 any 总数下降 |

**剩余工时小计：~49h**（FE-5 god 组件拆分最重）

---

## 4. 文档诚实度 / 对外口径

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| DOC-1 | `gen_claimed_vs_actual.py`（纯标准库，从 metrics 自动生成）+ `CLAIMED_VS_ACTUAL.md`（兑现 6 处断链承诺） | ✅ | — | `--check` 幂等 rc=0、含真实 85.07% |
| DOC-2 | `PROJECT_COMPREHENSIVE_ASSESSMENT.md` 加退役横幅 + 修 5 处过期数字（18%覆盖/2.0分/E2E=0/22500行） | ✅ | — | 横幅存在、过期数字带删除线+实测批注 |
| DOC-3 | 消解 Android 端等级三处矛盾，统一为"实验骨架·非签约级" | ✅ | — | VERSION/START_HERE 不再称 Android 签约级 |
| DOC-4 | 修 `FHD_DEPTH_ASSESSMENT_REVISED` 残留 `fail_under=52%`→84 | ✅ | — | 行 19/150 显示 84 |
| DOC-6 | `SSOT_INDEX.md` 登记 CLAIMED_VS_ACTUAL.md + coverage-dual-summary.json | ✅ | — | `docs_ssot_lint.py --strict` rc=0 |
| DOC-5 | `check_docs_honesty.py` CI 门禁：断链 + 退役数字黑名单 + gen --check | 🔭 ⚠️ | 3.5h | `--strict` rc=1 拦截；接入 test.yml 先软后硬 |

**剩余工时小计：~3.5h**

---

## 5. CI/CD 与运维

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| — | 取消跟踪 `.pytest_products.db` + 根 `.gitignore` 补 `*.pytest_products.db` | ✅ | — | `git ls-files` 命中数 0 |
| C1 | mypy 在已清零严格子集（schemas/middleware/domain.shipment/domain.persona/http，实测 EXIT=0）变阻断门禁，全量保持 advisory | 🔭 | 1.5h | `mypy <5目录> --follow-imports=silent` EXIT=0；改 SSOT 源后跑 publish |
| C2 | SSOT workflow **内容**同步做成真门禁（publish 后 `git diff --exit-code`），先修当前已存在的 dist/deploy 漂移 | 🔭 | 1.5h | publish 后工作树为空 |
| C3 | 补前端 codecov 上报；有 token 时上报失败可感知（无 token 降级不阻断） | 🔭 | 2h | `npm run test:coverage` 产出 lcov |
| C4 | scoped mutation smoke 接入主流水线（PR 即跑，continue-on-error 起步） | 🔭 ⚠️ | 2.5h | 依赖 T1；作用域锁 app/di |

**剩余工时小计：~7.5h**

---

## 6. 领域层真实落地（Neuro-DDD 名实相符）

> 审计修正了"使用率近 0%"的说法 → 真相是**两极分化**：shipment/material 切片是真 DDD（构造注入 Repository 端口、调聚合行为）；
> customer 切片名实不符（直连 `session.query(PurchaseUnitModel)`，内联重写不变量，旁路已写好的 Repository/Mapper/实体）。

| ID | 任务 | 状态 | 工时 | 验收 |
|---|---|---|---|---|
| D1 | 修复**已坏**的 customer mapper（`discount_rate` 列缺失致 AttributeError，getattr 兜底） | ✅ | — | round-trip 测试绿（4 passed） |
| D2 | 示范切片：`CustomerApplicationService` 写操作经 `PurchaseUnit` 实体 + Repository 端口（绞杀者模式，先 4 个高频方法） | 🔭 | 8h | 现有 39 测试迁移绑 repo mock、新增"空名→领域 ValueError→success=False"断言 |
| D3 | 清零调用领域服务（`ShipmentRulesEngine` 删；`PricingEngine` 标 PLANNED+锁定单测，与 D2 折扣衔接） | 🔭 | 3h | grep 证零引用 |
| D4 | 领域落地度回归守卫测试（AST 断言 app service 真调 domain 端口/聚合） | 🔭 | 3h | `test_domain_layer_usage.py` 绿 |
| D5 | 后续批次推广（product→inventory→finance，复用 D2 模板 + D4 守卫） | 🔭 | 大 | 每批=1 PR，独立 verify |
| — | 已外溢任务：`customer_to_domain` 的 `ContactInfo(person=,address=str)` 签名不匹配（运行时 TypeError） | 🔭 | 1h | 单测复现后修 |

**剩余工时小计：~15h+（D5 批次另计）**

---

## 7. 安全（经对抗式验证：4 个自承高危中仅 2 个真实可达）

| ID | 漏洞 | 裁决 | 状态 | 工时 | 说明 |
|---|---|---|---|---|---|
| VULN-3 | 模板删除路径遍历（`fs:/etc/passwd` 删任意文件，可远程未鉴权触达） | ✅ 确认真实 | ✅ 已修 | — | basename+realpath 包含校验，合法裸文件名删除不受影响；回归测试 6 项绿 |
| VULN-1 | Mod 后端 RCE（签名校验 fail-open + 无沙盒） | ✅ 确认真实 | ⚠️ 部分缓解 | — | 本批次：加 `XCAGI_REQUIRE_SIGNED_MODS` 可选 fail-closed 开关（默认行为不变）+ 响亮告警 |
| VULN-2 | Mod 解压 Zip-Slip | ❌ 已被缓解（CPython extractall sanitize，对抗 PoC 证伪） | ✅ 加防回归测试 | — | `test_zip_slip_safe.py` 文档化 |
| VULN-4 | 上传删除路径遍历 | ❌ 已被缓解（单段路由 + uvicorn 先解码 → 404，对抗 PoC 证伪） | 🔭 纵深防御 | 1h | 加 secure_filename 一致性硬化（非可达漏洞） |
| S1 | **VULN-1 完整修复**（签名管线落地 + 受信公钥随应用打包 + 去掉调用方 `verify_signature=False` + Mod 后端最小权限沙盒 + 安装端点鉴权） | — | 🔭 ⚠️ | 大 | **旗舰安全工程**；须与签名发布流程一起上线，否则会让所有安装失败 |
| S2 | 修签名管线自指哈希 bug（`signature.json` 被计入 `content_hash` 形成自指环，致真实包验签必 mismatch） | — | 🔭 | 2h | 阻塞 S1 的前置 |

**剩余工时小计：S1 大（需排期）+ S2 2h + VULN-4 硬化 1h**

---

## 8. 已发现的其它预存技术债（建议纳入后续批次）

- 6 个 pytest **收集错误**（`ModuleNotFoundError: app.application.purchase_app_service_v2` 等）——影响全量 `-k` 运行稳定性。
- 14 个**预存测试失败**（`TestSetIndustryEndpoint` 401，`require_admin_user` 拒测试客户端）——经 HEAD 基线对照确认非本批次回归，但应修。
- `ruff check` 仅在 `app/` 已清零；`scripts/`、`XCAGI/`、`MODstore/` 等扫描范围未审。
- 全量 `mypy app/` 实测 1671 errors（文档曾称"绿"，已在 §5 C1 纠正口径）。

---

## 9. 汇总

| 维度 | 本批次已落地 | 剩余工时 |
|---|---|---|
| 后端 | A1/A7/A6 + 13 预存 bug | ~18h |
| 测试 | T1/T2/T4 | ~28.5h |
| 前端 | FE-1/FE-2/FE-3 | ~49h |
| 文档诚实度 | DOC-1/2/3/4/6 | ~3.5h |
| CI/运维 | 取消跟踪 db | ~7.5h |
| 领域层 | D1 | ~15h+ |
| 安全 | VULN-3 修复 + VULN-1 缓解 + 2 防回归 | S1(大)+S2 2h+1h |
| **合计** | **本 PR ≈ 23 项已验证改动** | **约 125h + 2 个旗舰项（VULN-1 签名管线、DDD 全量推广）** |

> **诚实声明**：本 PR 是"到 9 分"的**第 1 批次**——已把若干维度推上一个台阶，并修复了一批被长期掩盖的真实
> bug（前端类型检查从未跑完、5 个后端 NameError、1 个高危任意文件删除、1 个已坏的 customer mapper）。
> 但"全部维度达到验证级 9/10"仍需上表约 **125 工时 + 2 个旗舰工程**，按批次推进。
> 任何"已达 9/10"的对外宣称在上述 🔭 项清零前都不成立——这正是本项目历史上最该避免的"宣称-撤回"循环。
