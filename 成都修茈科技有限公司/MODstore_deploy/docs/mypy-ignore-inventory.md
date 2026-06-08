# mypy ignore 模块清单（SSOT：`pyproject.toml`）

生成日期：2026-06-04  
历史旁路文件 `_mypy_legacy_ignore.json` 已删除（无引用）。

## 统计

| 类别 | 数量 |
|------|------|
| **严格**（`ignore_errors = false`） | `infrastructure.db`、`api.deps`、`api.csrf`、`eventing.*`、5 个 catalog/notification 模块 |
| **遗留 ignore**（分批收缩目标 ≤30） | **30** 模块 |
| 第三方 `ignore_missing_imports` | chromadb、redis、pika 等 8 包 |

## 遗留 ignore 列表（30，批次 C 维持）

| 模块 | 标注 |
|------|------|
| `modstore_server.api.app_factory` | 分批 strict |
| `modstore_server.api.market_routes` | 分批 strict（P2 路由迁入 api/ 后） |
| `modstore_server.api.payment_routes` | 分批 strict |
| `modstore_server.employee_api` | 分批 strict |
| `modstore_server.llm_api` | 高风险遗留 |
| `modstore_server.workflow_engine` | 分批 strict |
| `modstore_server.workbench_api` | 分批 strict |
| `modstore_server.knowledge_ingest` | 分批 strict |
| `modstore_server.knowledge_v2_api` | 分批 strict |
| `modstore_server.customer_service_api` | 分批 strict |
| `modstore_server.customer_service_orchestrator` | 分批 strict |
| `modstore_server.agent_butler_api` | 高风险遗留 |
| `modstore_server.agent_butler_orchestrate` | 高风险遗留 |
| `modstore_server.butler_qq_bridge` | 高风险遗留 |
| `modstore_server.script_agent.agent_loop` | 沙箱遗留 |
| `modstore_server.script_agent.sandbox_runner` | 沙箱遗留 |
| `modstore_server.script_workflow_api` | 沙箱遗留 |
| `modstore_server.employee_ai_pipeline` | 分批 strict |
| `modstore_server.employee_change_request_service` | 分批 strict |
| `modstore_server.mod_employee_agent_runner` | 分批 strict |
| `modstore_server.workflow_fhd_bridge` | 分批 strict |
| `modstore_server.workflow_nl_graph` | 分批 strict |
| `modstore_server.integrations.vibe_adapter` | 集成遗留 |
| `modstore_server.integrations.vibe_action_handlers` | 集成遗留 |
| `modstore_server.services.employee` | 分批 strict |
| `modstore_server.services.llm` | 分批 strict |
| `modstore_server.services.knowledge` | 分批 strict |
| `modstore_server.vector_store` | 分批 strict |
| `modstore_server.llm_chat_proxy` | 高风险遗留 |
| `modstore_server.eskill_runtime` | 高风险遗留 |
| `modstore_server.employee_executor` | 分批 strict |

## 已从 ignore 拉出（批次 A/B，2026-06-04）

约 56 个模块自 ignore 列表移除，纳入默认 mypy 检查或 strict 子块；重生成片段：

```bash
python scripts/export_mypy_ignore_modules.py --toml-fragment
```

## FHD 对照

FHD 严格模块见 [`FHD/pyproject.toml`](../../../FHD/pyproject.toml) `[[tool.mypy.overrides]]`：`app.domain.*`、`app.application.ports.*`、`excel_vector_app_service`、`inventory_repository_impl` 等。
