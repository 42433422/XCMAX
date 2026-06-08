# ADR：routes_registry 与 app_factory 双轨现状

## 状态

- **主入口**：[`modstore_server/api/app_factory.py`](../modstore_server/api/app_factory.py) 的 `create_app` 为生产与 `modstore_server.app` 使用的 FastAPI 工厂。
- **并行模块**：[`modstore_server/routes_registry.py`](../modstore_server/routes_registry.py) 体量较大，历史上可能用于独立挂载或迁移期路由聚合；当前仓库内**未发现**主工厂 `include_router` 引用该模块。

## 决策（草案）

| 里程碑 | 动作 |
|--------|------|
| **M0（当前）** | 保留文件；新功能不得向 `routes_registry` 增加路由，一律走 `app_factory` 或独立 `APIRouter` 模块。 |
| **M1** | 全仓库检索 `routes_registry` / `register_all_routes` 引用；若有脚本或分叉入口，登记到运维 Runbook。 |
| **M2** | 若无运行时引用：删除 `routes_registry.py` 或拆分为已命名域的小路由模块并删除壳文件。 |
| **M3** | 更新 `docs/ARCHITECTURE.md` 与 `docs/FRONTEND_AND_GATEWAY_ROADMAP.md` 中的路由来源描述。 |

## 退役触发条件

- 连续两个发布周期无 import / 无 issue 引用；
- 或代码审查确认与 `app_factory` 路由集 100% 重叠且无测试依赖。

## 备注

若曾存在 `fastapi_compat_routes` 等目录，应以本 ADR 的 **M1 检索** 结果为准，避免同名路径在不同分支漂移。
