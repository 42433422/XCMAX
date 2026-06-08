# 前端 HTTP 契约：OpenAPI 与 `api.ts`（market-frontend-dev）

## 现状

- 后端：FastAPI 暴露 [`/openapi.json`](../../modstore_server/api/app_factory.py)；静态快照见 [`contracts/openapi/modstore-server.json`](../contracts/openapi/modstore-server.json)。
- 前端：[`market/src/api.ts`](../../market/src/api.ts) 为 **手写** 请求封装，配合 [`infrastructure/http/client.ts`](../../market/src/infrastructure/http/client.ts)。

## 两条协作路径（择一为主）

### A. 手写 + 契约门禁（默认、改动面小）

- 每个涉及 REST 契约的 PR：**必须** 运行 `python scripts/export_openapi.py` 并提交更新的 `modstore-server.json`（CI `--check` 已强制）。
- 评审时对照 OpenAPI diff 审核 `api.ts` 是否同步（路径、方法、必填字段、错误码）。
- WebSocket **`/api/realtime/ws`** 仍以代码与 [`realtime_ws.py`](../../modstore_server/realtime_ws.py) 说明为准——OpenAPI 对 WS 的描述能力有限。

### B. 从 spec 生成类型或客户端（可选、需立项）

- 工具候选：`openapi-typescript`、`openapi-fetch` 等；生成物建议落在 `market/src/generated/` 或等价目录，`api.ts` 逐步变薄为对生成函数的 re-export。
- **前置条件**：包管理、lint、CI 中与现有 `vite`/测试链兼容；破坏性变更时需团队约定 semver 或对生成代码做豁免规则。

## 角色分工

| 角色 | 责任 |
| --- | --- |
| 后端 | 路由上补齐 `summary` / `response_model` / `responses`（见 [`api-docs.md`](../api-docs.md)）；保持快照与 CI 门禁绿 |
| **market-frontend-dev** | 保证 `api.ts` 与已合并的 `modstore-server.json` 一致；若选路径 B，维护生成脚本与导入边界 |
| 评审 | Breaking change 须在 PR 描述中显式写明，并 `@` 前端对接人 |
