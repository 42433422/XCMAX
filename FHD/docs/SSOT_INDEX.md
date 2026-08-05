# SSOT 索引（唯一真相源登记表）

> **本文件为 SSOT 索引的 SSOT**。任何文档声称 SSOT 必须在此登记。
> 最后更新：2026-07-31

## 登记规则

1. 每个领域只允许一个 SSOT 文档
2. 新增 SSOT 声明必须先在此登记
3. `scripts/dev/docs_ssot_lint.py` 会扫描所有 md 文件中的 SSOT 声明，与本文件比对
4. 冲突时以本文件为准

## 领域 SSOT 登记表

| 领域 | SSOT 文档 | 说明 |
|------|----------|------|
| coverage（覆盖率） | [reports/COVERAGE_RAMP.md](reports/COVERAGE_RAMP.md) | 后端/前端覆盖率基线、目标、棘轮 floor |
| ci（CI/CD） | [../../docs/CI_SSOT.md](../../docs/CI_SSOT.md) | 根仓 .github/workflows/ 唯一调度入口 |
| mod（Mod 开发） | [guides/MOD_AUTHORING_GUIDE.md](guides/MOD_AUTHORING_GUIDE.md) | Mod 开发规范、mods/ 为唯一编辑源 |
| version（产品版本） | [VERSION.md](../VERSION.md) | 产品版本 1.0.0.0、工具链映射 1.0.0 |
| route（路由） | [reports/WAVE2_ROUTE_SSOT.md](reports/WAVE2_ROUTE_SSOT.md) | RouteRegistry + mounts/* 路由 SSOT |
| git（Git 仓库） | [reports/GIT_WORKTREE_RECOVERY.md](reports/GIT_WORKTREE_RECOVERY.md) | 根仓 XCMAX/ 为 Git SSOT |
| mypy（类型检查） | [../pyproject.toml](../pyproject.toml) | [tool.mypy] 配置 |
| deps（依赖锁定） | [guides/DEPENDENCY_LOCKS.md](guides/DEPENDENCY_LOCKS.md) | Python/Node 依赖锁定策略 |
| auth（授权市场） | [guides/AUTH_MARKET_CONTRACT.md](guides/AUTH_MARKET_CONTRACT.md) | 授权与市场契约 |
| compliance（合规） | [evidence/compliance-tier2/00-control-matrix.md](evidence/compliance-tier2/00-control-matrix.md) | Tier2 合规控制矩阵 |
| autonomy-l4-readiness（L4就绪） | [autonomy/L4_READINESS.md](autonomy/L4_READINESS.md) | 自进化管理端 L4 Readiness 清单与运行入口 |
| ssot-framework（SSOT 框架） | [SSOT_FRAMEWORK.md](SSOT_FRAMEWORK.md) | 统一注册表 ssot.yaml + ssot_cli 编排器 |
| claimed-vs-actual（对外声称 vs 实测） | [CLAIMED_VS_ACTUAL.md](CLAIMED_VS_ACTUAL.md) | 对外声称 vs 实测对照，由 scripts/dev/gen_claimed_vs_actual.py 自动生成 |
| coverage-metrics（覆盖率唯一数字） | [../metrics/coverage-dual-summary.json](../metrics/coverage-dual-summary.json) | 覆盖率唯一数字 SSOT（committed_head / 棘轮 floor / 目标 / 退役口径） |
| coverage-behavior-gate（行为覆盖率门禁决策） | [adr/0001-coverage-behavior-gate.md](adr/0001-coverage-behavior-gate.md) | ADR-0001 决策记录：覆盖率门禁从全量口径切换为行为口径（排除 coverage_ramp stub）；`fail_under` 保留为全量行 floor SSOT |
| account（产品端与账号体系） | [account_system_ssot.md](account_system_ssot.md) | 产品端矩阵、账号体系四维真相源（身份/行业/会员/账号等级）、行业/Persona 派生、字段写入权限矩阵、多租户隔离与账户安全；**定价文档 SSOT** |
| pricing-enterprise（企业宿主授权价） | [../config/saas_plans.json](../config/saas_plans.json) | 体验 ¥99；永久授权 ¥49,999–¥999,999；收银与 `model-payment` / 企业开户读取 |
| pricing-membership（市场会员价） | [../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/base.py](../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/base.py) | `init_default_plan_templates()` → `PlanTemplate`；VIP ¥9.9 – SVIP8 ¥4,999 |
| licensing（许可边界，非定价） | [guides/LICENSING.md](guides/LICENSING.md) | Apache-2.0 vs EULA 触发条件、Mod 分成、Offline 功能差异；**具体金额见上两行 pricing SSOT** |
| project-state（项目真实状态） | [PROJECT_STATE.md](PROJECT_STATE.md) | 项目健康度/完成度诚实仪表盘，唯一禁止撒谎的状态文档 |
| mobile-tri-platform（移动统一） | [mobile_tri_platform_ssot.md](mobile_tri_platform_ssot.md) | **Flutter 唯一交付主线**；独立原生 Android/iOS/HarmonyOS 已删除；OpenAPI + FastAPI 契约 |
| mobile-flutter（移动日常入口） | [guides/MOBILE_FLUTTER.md](guides/MOBILE_FLUTTER.md) | Flutter 本地开发、发版与归档规则 |
| mobile-android（Flutter 渠道） | [guides/MOBILE_ANDROID.md](guides/MOBILE_ANDROID.md) | Flutter Android Runner、本地验证、签名和发布指南 |
| local-data（本地数据安全） | [security/LOCAL_DATA_POLICY.md](security/LOCAL_DATA_POLICY.md) | 桌面/Web 本地数据分类、purge CLI、诊断包与上传鉴权策略 |
| neuro-bus-events（事件契约） | [../config/neuro_bus_events.yaml](../config/neuro_bus_events.yaml) | NeuroBus 三流事件契约统一 SSOT（NeuroBus 域事件 + AgentRun 事件 + 应用桥接），点号命名规范化，派生 Python 常量 + TS 类型 + OpenAPI schema |
| customer-ticket-bus（客服工单闭环） | [architecture/CUSTOMER_TICKET_BUS_SSOT.md](architecture/CUSTOMER_TICKET_BUS_SSOT.md) | 客服工单总线/告警闭环的唯一事实源：MODstore incident_bus + incident_team 与入场边界 |
| deployment-modes（AI 部署模式） | [../config/deployment_modes.yaml](../config/deployment_modes.yaml) | 三档部署模式唯一真相源：绝对安全、安全、性能；统一内网/外网、手机局域网直连与移动端超级员工 LAN 优先策略 |
| database-storage（数据库存储） | [../config/database_storage_modes.yaml](../config/database_storage_modes.yaml) | SQLite/PG 存储模式唯一真相源：桌面 database.json profile、SQLite→PostgreSQL 同步计划、重启生效策略 |
| customer-delivery（客户私有交付） | [../config/customer_delivery.json](../config/customer_delivery.json) | 客户品牌；`legacy_mod_id` vs `industry_mod_id`；**双轨** `modules` / `employees` 及轨道节点进度；生产员工只列定制包；太阳鸟「考勤表转化」= 模块轨节点 |
| process-flow（业务流程与交付流程） | [architecture/PROCESS_FLOW_SSOT.md](architecture/PROCESS_FLOW_SSOT.md) | 业务工作流程 + 对外交付流程唯一真相源；供 AGI 编排（Agent Orchestrator / Workflow Engine / NeuroBus 事件驱动）消费；含统一单据生命周期、自动化就绪度矩阵、断点行动项 |

## 机器注册表（ssot.yaml）

> 与 `FHD/config/ssot.yaml` 的 **enabled 域** 一一对应；由 `scripts/dev/ssot_registry_crosscheck.py` 互校验（CI blocking）。
> 域名 / SSOT 路径必须与 yaml 字节级一致；门禁列仅供人读。

| 域名 | SSOT 路径 | 门禁 |
|------|----------|------|
| mods | `FHD/mods/` | blocking |
| ci-workflows | `FHD/.github/workflows/` | blocking |
| coverage | `FHD/metrics/coverage_ratchet_baseline.json` | blocking |
| version | `FHD/VERSION.md` | blocking |
| docs-ssot | `FHD/docs/SSOT_INDEX.md` | blocking |
| account-system | `FHD/docs/account_system_ssot.md` | blocking |
| test-files | `FHD/tests/` | blocking |
| deploy-scripts | `FHD/scripts/deploy/` | blocking |
| deps | `FHD/pyproject.toml` | blocking |
| error-codes | `FHD/app/http/error_codes.py` | blocking |
| registry-crosscheck | `FHD/docs/SSOT_INDEX.md` | blocking |
| employee-roster | `FHD/config/duty_roster.json` | blocking |
| db-schema | `FHD/alembic/versions/` | blocking |
| service-topology | `FHD/config/service_topology.yaml` | blocking |
| deployment-modes | `FHD/config/deployment_modes.yaml` | blocking |
| database-storage | `FHD/config/database_storage_modes.yaml` | blocking |
| mobile-tri-platform | `FHD/docs/mobile_tri_platform_ssot.md` | blocking |
| neuro-bus-events | `FHD/config/neuro_bus_events.yaml` | blocking |
| runtime-inventory | `FHD/config/service_topology.yaml` | blocking |
| repository-ssot | `FHD/app/infrastructure/repositories/` | blocking |

## 已退役 SSOT（指针化）

| 原文档 | 指向 | 原因 |
|--------|------|------|
| reports/COVERAGE_GAP.md | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
| reports/FHD_DEPTH_ASSESSMENT_REVISED_2026-05-03.md（覆盖率章节） | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
| XCAGI/BUSINESS_MODEL.md（定价章节） | account_system_ssot.md + saas_plans.json + PlanTemplate | 2026-07 定价 SSOT 收敛；BUSINESS_MODEL 保留战略叙事 |
