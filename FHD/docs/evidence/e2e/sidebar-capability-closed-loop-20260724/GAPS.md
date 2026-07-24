# 闭环缺口（修复后）

## 已修复（2026-07-24）

- **组织管理读写不一致**：`GET /api/customers` 原先只读 legacy 行，与 `POST /api/customers`（service/facade）不同源；已改为委托 `customers_list`，创建后列表可见。
- **智能对话写入 405**：补 `POST /api/chat/send`、`POST /api/planner/chat` → 同 `/api/ai/chat`；补 `POST /api/conversations/{id}/messages` 写入会话消息。
- **知识库/员工台/数据来源/打印模板短路径 404**：新增 `sidebar_capability_compat` 门面，对齐探测路径到真实能力（knowledge/v1、workflow-employee-catalog、templates 等）。

## 说明

- 前端主路径仍是 `/api/ai/chat`、`/api/knowledge/v1/*`、`/api/system/workflow-employee-catalog`、`/api/templates`；兼容短路径仅为闭环与旧客户端。
- 模板列表可为空（无上传模板时属正常）；打印机以本机 CUPS 为准。
- 需重启桌面内嵌后端后，上述修复才会在 `:17500` 生效。
