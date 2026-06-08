# ADR 0012：抽出独立 Workflow 服务评估

## 状态

提议

## 背景

`WorkflowEngineClient` 封装 `workflow_engine`；图数据与执行记录位于同一 PostgreSQL。

## 决策（草案）

- **表面 API**：`execute_workflow` / `validate_workflow` / `run_sandbox`；事件 `workflow.sandbox_completed` 由服务侧统一发布。
- **配置**：`MODSTORE_WORKFLOW_SERVICE_URL`；长时沙箱改 Webhook / SSE 回调。
- **HttpWorkflowEngineClient**：REST + JSON；与 `EmployeeRuntimeClient` / `LlmChatClient` HTTP 版组合。
- **回滚**：进程内 `InProcessWorkflowEngineClient`。
- **灰度**：按 `workflow_id` 或用户分桶；影子双写 `MODSTORE_BUS_SHADOW` 观察事件体积。

## 后果

- 调度器与 `workflow_scheduler` 需决定随迁移或保留在平台层。
