# MODstore API 文档约定

## FastAPI 主服务

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`
- Prometheus metrics: `/metrics`

`modstore_server/api/app_factory.py` 的 `_OPENAPI_TAGS` 与各领域路由标签已对齐主要分组（见 [`SERVICE_BOUNDARIES.md`](./SERVICE_BOUNDARIES.md)）。新增稳定接口时应同时补充：

- `tags`：优先使用 `_OPENAPI_TAGS` 已有名称或在 `create_app` 中补充词条描述。
- `summary` / docstring：面向前端和第三方调用者说明用途。
- `response_model`：对稳定返回体提供 Pydantic 模型。
- `responses`：对 401/403/404/422 等显式错误补说明。

**关联 Runbook**：知识库入库流程见 [`runbooks/openapi-knowledge-base-sync.md`](./runbooks/openapi-knowledge-base-sync.md)；实时通知 WebSocket 与 Nginx 超时对齐见 [`runbooks/websocket-proxy-timeouts.md`](./runbooks/websocket-proxy-timeouts.md)。

## Rust 网关类预研

在未通过延迟分解门禁前不进行实施；见 [`adr/0013-rust-gateway-evaluation-gate.md`](./adr/0013-rust-gateway-evaluation-gate.md)。

## Java 支付服务

- Swagger UI: `/swagger-ui.html`
- OpenAPI JSON: `/v3/api-docs`
- Prometheus metrics: `/actuator/prometheus`
- Health: `/actuator/health`

Java controller 新增接口时优先使用 request/response DTO 或 record，避免 `Map<String, Object>` 让 OpenAPI schema 退化为无结构对象。管理端接口仍应保留 JWT 鉴权，只有 actuator health/info/prometheus 和 Swagger 开发文档路径默认放行。

## 契约冻结

跨服务业务事件以 `docs/service-boundaries-and-events.md` 和两端 `EventContracts` 为准。REST API 的运行时 spec 可由 CI 或发布流程导出保存为版本快照，用于对比 breaking changes。
