# SSOT 索引（唯一真相源登记表）

> **本文件为 SSOT 索引的 SSOT**。任何文档声称 SSOT 必须在此登记。
> 最后更新：2026-07-26

## 登记规则

1. 每个领域只允许一个 SSOT 文档
2. 新增 SSOT 声明必须先在此登记
3. `scripts/dev/docs_ssot_lint.py` 会扫描所有 md 文件中的 SSOT 声明，与本文件比对
4. `scripts/dev/ssot_registry_contract.py` 强制互校本表的「执行注册名」与 `config/ssot.yaml`
5. 带执行注册名的行，其路径必须与 `ssot.yaml` 的 `ssot` 路径逐项一致

## 领域 SSOT 登记表

| 领域 | SSOT | 说明 | 执行注册名 |
|------|------|------|------------|
| coverage（覆盖率） | [coverage_ratchet_baseline.json](../metrics/coverage_ratchet_baseline.json) | 覆盖率棘轮机器基线；说明见 reports/COVERAGE_RAMP.md | `coverage` |
| ci（CI/CD） | [workflows/](../.github/workflows/) | FHD 工作流编辑源；根仓 .github/workflows/ 为生成件 | `ci-workflows` |
| mod（Mod 开发） | [mods/](../mods/) | Mod 唯一编辑源；开发规范见 guides/MOD_AUTHORING_GUIDE.md | `mods` |
| version（产品版本） | [VERSION.md](../VERSION.md) | 产品版本 1.0.0.0、工具链映射 1.0.0 | `version` |
| docs-registry（文档登记） | [SSOT_INDEX.md](SSOT_INDEX.md) | 文档声明登记表，同时是机器注册表的人类投影 | `docs-ssot` |
| account（产品端与账号体系） | [account_system_ssot.md](account_system_ssot.md) | 身份/行业/会员/账号等级、多租户隔离与账户安全 | `account-system` |
| test-files（测试资产） | [tests/](../tests/) | 测试文件规范与临时文件守卫 | `test-files` |
| deploy-scripts（部署脚本） | [deploy/](../scripts/deploy/) | 生产部署脚本编辑源 | `deploy-scripts` |
| deps（依赖锁定） | [pyproject.toml](../pyproject.toml) | Python 依赖声明，requirements 为派生/校验件 | `deps` |
| error-codes（错误码） | [error_codes.py](../app/http/error_codes.py) | HTTP 错误码定义 | `error-codes` |
| registry-contract（注册表契约） | [SSOT_INDEX.md](SSOT_INDEX.md) | 人类登记表与机器注册表逐项互校 | `registry-crosscheck` |
| employee-roster（员工花名册） | [duty_roster.json](../config/duty_roster.json) | AI 员工/部门花名册机器源 | `employee-roster` |
| db-schema（数据库结构） | [alembic/versions/](../alembic/versions/) | Alembic 迁移链是 DB schema 唯一写入源 | `db-schema` |
| service-topology（服务拓扑） | [service_topology.yaml](../config/service_topology.yaml) | 服务地址、端口和健康探针源 | `service-topology` |
| deployment-modes（AI 部署模式） | [deployment_modes.yaml](../config/deployment_modes.yaml) | 三档部署模式与网络/性能策略 | `deployment-modes` |
| database-storage（数据库存储） | [database_storage_modes.yaml](../config/database_storage_modes.yaml) | SQLite/PG 存储模式与迁移策略 | `database-storage` |
| mobile-tri-platform（移动统一） | [mobile_tri_platform_ssot.md](mobile_tri_platform_ssot.md) | Flutter 唯一交付主线与三端契约 | `mobile-tri-platform` |
| neuro-bus-events（事件契约） | [neuro_bus_events.yaml](../config/neuro_bus_events.yaml) | NeuroBus 三流事件契约与生成件 | `neuro-bus-events` |
| runtime-inventory（运行时清单） | [service_topology.yaml](../config/service_topology.yaml) | 期望拓扑与实际运行状态的投影源 | `runtime-inventory` |
| coverage-guide（覆盖率说明） | [reports/COVERAGE_RAMP.md](reports/COVERAGE_RAMP.md) | 覆盖率基线、口径和棘轮说明文档 | — |
| ci-guide（CI 说明） | [../../docs/CI_SSOT.md](../../docs/CI_SSOT.md) | 根仓工作流生成、触发和门禁说明 | — |
| mod-guide（Mod 开发说明） | [guides/MOD_AUTHORING_GUIDE.md](guides/MOD_AUTHORING_GUIDE.md) | Mod 编辑源、导出树与开发流程说明 | — |
| deps-guide（依赖说明） | [guides/DEPENDENCY_LOCKS.md](guides/DEPENDENCY_LOCKS.md) | 依赖声明与锁文件同步规则 | — |
| route（路由） | [reports/WAVE2_ROUTE_SSOT.md](reports/WAVE2_ROUTE_SSOT.md) | RouteRegistry + mounts/* 路由 SSOT | — |
| git（Git 仓库） | [reports/GIT_WORKTREE_RECOVERY.md](reports/GIT_WORKTREE_RECOVERY.md) | 根仓 XCMAX/ 为 Git SSOT | — |
| mypy（类型检查） | [../pyproject.toml](../pyproject.toml) | [tool.mypy] 配置 | — |
| auth（授权市场） | [guides/AUTH_MARKET_CONTRACT.md](guides/AUTH_MARKET_CONTRACT.md) | 授权与市场契约 | — |
| compliance（合规） | [evidence/compliance-tier2/00-control-matrix.md](evidence/compliance-tier2/00-control-matrix.md) | Tier2 合规控制矩阵 | — |
| autonomy-l4-readiness（L4就绪） | [autonomy/L4_READINESS.md](autonomy/L4_READINESS.md) | 自进化管理端 L4 Readiness 清单与运行入口 | — |
| ssot-framework（SSOT 框架） | [SSOT_FRAMEWORK.md](SSOT_FRAMEWORK.md) | 统一注册表 ssot.yaml + ssot_cli 编排器 | — |
| claimed-vs-actual（对外声称 vs 实测） | [CLAIMED_VS_ACTUAL.md](CLAIMED_VS_ACTUAL.md) | 对外声称 vs 实测对照，由 scripts/dev/gen_claimed_vs_actual.py 自动生成 | — |
| coverage-metrics（覆盖率唯一数字） | [coverage-dual-summary.json](../metrics/coverage-dual-summary.json) | committed_head / 棘轮 floor / 目标 / 退役口径 | — |
| pricing-enterprise（企业宿主授权价） | [saas_plans.json](../config/saas_plans.json) | 体验 ¥99；永久授权 ¥49,999–¥999,999 | — |
| pricing-membership（市场会员价） | [base.py](../../成都修茈科技有限公司/MODstore_deploy/modstore_server/db/base.py) | `init_default_plan_templates()`；VIP ¥9.9 – SVIP8 ¥4,999 | — |
| licensing（许可边界，非定价） | [guides/LICENSING.md](guides/LICENSING.md) | Apache-2.0 vs EULA 触发条件；具体金额见 pricing SSOT | — |
| project-state（项目真实状态） | [PROJECT_STATE.md](PROJECT_STATE.md) | 项目健康度/完成度诚实仪表盘 | — |
| mobile-flutter（移动日常入口） | [guides/MOBILE_FLUTTER.md](guides/MOBILE_FLUTTER.md) | Flutter 本地开发、发版与归档规则 | — |
| mobile-android（Flutter 渠道） | [guides/MOBILE_ANDROID.md](guides/MOBILE_ANDROID.md) | Flutter Android Runner、签名和发布指南 | — |
| local-data（本地数据安全） | [security/LOCAL_DATA_POLICY.md](security/LOCAL_DATA_POLICY.md) | 桌面/Web 本地数据分类、诊断包与上传鉴权策略 | — |
| customer-ticket-bus（客服工单闭环） | [CUSTOMER_TICKET_BUS_SSOT.md](architecture/CUSTOMER_TICKET_BUS_SSOT.md) | MODstore incident_bus + incident_team 的闭环事实源 | — |

## 已退役 SSOT（指针化）

| 原文档 | 指向 | 原因 |
|--------|------|------|
| reports/COVERAGE_GAP.md | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
| reports/FHD_DEPTH_ASSESSMENT_REVISED_2026-05-03.md（覆盖率章节） | reports/COVERAGE_RAMP.md | 覆盖率 SSOT 收敛 |
| XCAGI/BUSINESS_MODEL.md（定价章节） | account_system_ssot.md + saas_plans.json + PlanTemplate | 2026-07 定价 SSOT 收敛；BUSINESS_MODEL 保留战略叙事 |
