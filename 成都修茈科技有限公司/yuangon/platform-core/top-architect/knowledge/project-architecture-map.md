# XCMAX/FHD/MODstore 项目架构地图

本文件是顶级架构师员工的首层知识储备。回答架构问题时，先用本文件定位，再回到当前仓库和 SSOT 验证。

## 1. 顶层结构

| 区域            | 作用                                                                       | 关键路径                                                                           |
| --------------- | -------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| XCMAX 根仓      | 总仓、CI、桌面/移动/网站/员工体系汇合点                                    | `.github/**`、`docs/**`、`scripts/dev/**`                                          |
| FHD             | XCAGI 主应用：FastAPI 后端、Vue 前端、Electron 桌面、移动端主线、员工 SSOT | `FHD/app/**`、`FHD/frontend/src/**`、`FHD/desktop/**`、`FHD/mobile-flutter-poc/**` |
| MODstore_deploy | Mod/员工包/工作流/支付/市场平台                                            | `成都修茈科技有限公司/MODstore_deploy/**`                                          |
| yuangon         | 管理端员工岗位包说明、runbook、skill、prompt                               | `成都修茈科技有限公司/yuangon/**`                                                  |

## 2. FHD 主应用架构

FHD 采用 Neuro-DDD 思路：表现层、应用层、领域层、基础设施层分离，并用 NeuroBus/事件契约承接 AI 员工和自动化流程。

| 层         | 典型路径                                                   | 职责                           |
| ---------- | ---------------------------------------------------------- | ------------------------------ |
| 表现层     | `FHD/app/fastapi_routes/**`、`FHD/frontend/src/**`         | API 路由、Vue 页面、移动 API   |
| 应用层     | `FHD/app/application/**`                                   | 用例编排、跨领域协调、服务层   |
| 领域层     | `FHD/app/domain/**`                                        | 领域实体、规则、值对象         |
| 基础设施层 | `FHD/app/infrastructure/**`、`FHD/app/db/**`               | DB、外部服务、Mod 加载、持久化 |
| 事件/AI    | `FHD/app/neuro_bus/**`、`FHD/config/neuro_bus_events.yaml` | 事件契约、追踪、AI 编排        |

桌面形态是 Electron 壳加本地 FastAPI 子进程；Web 形态是 Nginx/服务端 FastAPI；移动端主线是 Flutter UI 调 FastAPI `/api/mobile/v1/*`。

## 3. 移动端主线

移动统一主线以 Flutter 为前端、OpenAPI 为契约、FastAPI 为可信业务后端。

| 主题             | SSOT/入口                                                                                 |
| ---------------- | ----------------------------------------------------------------------------------------- |
| 移动统一策略     | `FHD/docs/mobile_tri_platform_ssot.md`                                                    |
| Flutter 主实现   | `FHD/mobile-flutter-poc/**`                                                               |
| 契约             | `FHD/contracts/openapi.json`                                                              |
| FastAPI 移动接口 | `FHD/app/fastapi_routes/mobile_api.py`、`FHD/app/fastapi_routes/mobile_api_extensions.py` |
| Flutter 收敛边界 | `FHD/mobile-flutter-poc/FLUTTER_UNIFICATION.md`                                           |

原则：Flutter 只做交互、展示、缓存和端侧适配；账号、权限、员工、聊天、支付、审批、同步、数据写入都归 FastAPI。

## 4. 管理端员工体系

员工体系不是单文件 UI 列表。新增管理端员工时必须走这条链：

1. `FHD/config/duty_roster.json`：岗位归属、部门、区域 SSOT。
2. `FHD/mods/_employees/<employee-id>/manifest.json`：员工身份、说明、能力、提示词、scope、handler。
3. `成都修茈科技有限公司/yuangon/<area>/<employee-id>/`：岗位说明、runbook、skill、prompt、知识储备。
4. `scripts/dev/sync_duty_roster.py --generate`：生成 Web、MODstore、Flutter 等派生文件。
5. 移动头像/离线快照按端补充映射，避免离线或弱网状态显示退化。

派生目标包括：

- `FHD/frontend/src/domain/yuangonDutyRoster.ts`
- `成都修茈科技有限公司/MODstore_deploy/market/src/domain/yuangonDutyRoster.ts`
- `成都修茈科技有限公司/MODstore_deploy/modstore_server/duty_roster.py`
- `FHD/mobile-flutter-poc/lib/src/data/duty_roster_ssot.dart`
- `FHD/app/infrastructure/mods/catalog_visibility.py`
- `FHD/frontend/src/constants/enterpriseWorkflowEstablishment.ts`

## 5. MODstore 架构

MODstore 是 Mod、AI 员工包、工作流、支付/钱包/权益的平台。当前是同进程模块化为主，支付域已有 Java 服务边界。

| 域          | 典型路径                                                       | 职责                                           |
| ----------- | -------------------------------------------------------------- | ---------------------------------------------- |
| 市场前端    | `成都修茈科技有限公司/MODstore_deploy/market/**`               | Vue 3 + Vite 页面、市场、工作台                |
| Python 网关 | `成都修茈科技有限公司/MODstore_deploy/modstore_server/**`      | FastAPI 网关、Catalog、员工、工作流、LLM、通知 |
| Java 支付   | `成都修茈科技有限公司/MODstore_deploy/java_payment_service/**` | 订单、支付、钱包、权益                         |
| 文档/ADR    | `成都修茈科技有限公司/MODstore_deploy/docs/**`                 | 架构、服务边界、支付契约、运行手册             |

关键边界见 `成都修茈科技有限公司/MODstore_deploy/docs/ARCHITECTURE.md`、`SERVICE_BOUNDARIES.md`、`PAYMENT_CONTRACT.md`。

## 6. SSOT 与真实状态

回答问题时优先核对这些真相源：

| 领域      | 文件                                   |
| --------- | -------------------------------------- |
| SSOT 索引 | `FHD/docs/SSOT_INDEX.md`               |
| 项目状态  | `FHD/docs/PROJECT_STATE.md`            |
| 员工编制  | `FHD/config/duty_roster.json`          |
| 移动统一  | `FHD/docs/mobile_tri_platform_ssot.md` |
| OpenAPI   | `FHD/contracts/openapi.json`           |
| 事件契约  | `FHD/config/neuro_bus_events.yaml`     |
| 账号体系  | `FHD/docs/account_system_ssot.md`      |
| 版本      | `FHD/VERSION.md`                       |

`PROJECT_STATE.md` 是诚实仪表盘。它可能比旧架构文档更接近当前风险和落地状态。架构建议必须同时看“目标架构”和“真实进度”。

## 7. 学习路线

1. 先读 `FHD/docs/PROJECT_STATE.md`，理解项目真实完成度和风险。
2. 再读 `FHD/docs/ARCHITECTURE.md`，理解 Neuro-DDD、桌面/Web 形态和目录结构。
3. 读 `FHD/docs/mobile_tri_platform_ssot.md` 与 `FHD/mobile-flutter-poc/FLUTTER_UNIFICATION.md`，理解 Flutter 唯一移动主线。
4. 读 `FHD/config/duty_roster.json` 与 `scripts/dev/sync_duty_roster.py`，理解管理端员工体系怎么生成到三端。
5. 读 `成都修茈科技有限公司/MODstore_deploy/docs/ARCHITECTURE.md`，理解 MODstore 和支付边界。
6. 最后按任务进入源码：FastAPI 路由、应用服务、Vue 页面、Flutter 页面、员工 manifest。

## 8. 升级评审模板

每次升级方案至少回答：

- 要改的源头 SSOT 是什么？
- 哪些派生文件会变化？
- 影响哪些端：Web、桌面、Flutter Android/iOS、MODstore、后端？
- 是否涉及账号、权限、支付、安全、数据库 schema 或发布上架？
- 应由哪个员工执行？
- 验证命令是什么？
- 失败怎么回滚？
