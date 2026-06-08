# MODstore 开发者文档

把 MODstore 的 AI 员工与工作流当成可调用的"业务 API"，接入到任何外部系统。

## 入门

| 文档 | 适合谁 |
| --- | --- |
| [01 Quickstart](./01-quickstart.md) | 5 分钟跑通：拿到 Token → 触发员工 → 收到 webhook |
| [02 Authentication](./02-authentication.md) | 理解 PAT 与 JWT 双认证、scope、过期策略 |
| [03 REST API](./03-rest-api.md) | 全量接口索引（指向 OpenAPI 静态快照与 Swagger UI） |
| [04 Webhooks](./04-webhooks.md) | 出站订阅、HMAC 签名、入站工作流触发器 |
| [04a 事件参考](./04a-event-reference.md) | 所有可订阅事件清单（自动生成） |
| [05 SDK 示例](./05-sdk-examples.md) | Python / TypeScript / curl 范例 |
| [06 错误码与限流](./06-errors-and-limits.md) | 常见错误、重试策略、生产建议 |
| [07 多账号数据隔离](./07-account-data-isolation.md) | `user_id` / owner 模型、接口绑定当前用户、与公开目录的区别 |
| [08 桌面密钥包导出](./08-key-export-desktop.md) | Web→桌面 `.msk1` 加密包、ECDH+AES-GCM、审计与 scope 说明 |
| [性能公开基线](../perf-benchmark-public.md) | k6 全链路摘要、复现命令；与 FHD `scripts/loadtest` 对照说明 |
| [贡献指南：代码分层与质量门禁](../../CONTRIBUTING.md) | T1 核心 / T2 脚本 / T3 兼容层 / T4 生成产物 的边界与门禁 |
| [前端 API 契约与 `api.ts`](./frontend-api-contract.md) | OpenAPI diff 门禁 vs 自动生成客户端的路径选择 |
| [员工执行器弹性与观测](./employee-executor-resilience.md) | 术语（重试/降级/熔断）、并发槽与 `employee.execution.recovery` 事件 |

## 在线交互

- **Swagger UI**: `https://<your-host>/docs`
- **ReDoc**: `https://<your-host>/redoc`
- **OpenAPI JSON**: `https://<your-host>/openapi.json`
- **Java 支付服务 OpenAPI**: `https://<payment-host>/v3/api-docs`
- **静态 OpenAPI 快照**（用于 CI diff）：[`/contracts/openapi/modstore-server.json`](../contracts/openapi/modstore-server.json)

## 自动化生成

- 接口文档 (`/contracts/openapi/modstore-server.json`)：`python scripts/export_openapi.py`
- 事件参考 (`04a-event-reference.md`)：`python scripts/generate_event_reference.py`

CI 在每个 PR 跑：

```bash
python scripts/export_openapi.py --check
```

如果你改了 API 但忘了 commit 新的 OpenAPI 快照，CI 会以非 0 状态码拦截。
