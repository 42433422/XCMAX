# MODstore 服务边界与 NeuroBus 事件契约

## 服务职责

MODstore 当前由 Python FastAPI 主服务、Java 支付服务、前端 market 应用和基础设施组件组成。

- Python FastAPI (`modstore_server`) 是默认业务入口，负责市场、Mod 库、工作流、员工制作、LLM、通知、退款审核、Webhook 管理和静态市场前端挂载。
- Java payment service (`java_payment_service`) 在 `PAYMENT_BACKEND=java` 时承接 `/api/payment/**` 与 `/api/wallet/**`，负责订单、钱包、支付宝对接、权益发放和支付事件外发。
- NeuroBus 是 Python 进程内域事件总线，入口为 `modstore_server.eventing.global_bus.neuro_bus`。它用于本进程订阅和 outbox 落盘，不是跨进程消息中间件。
- Business Webhook 是跨服务/外部系统事件出口，由 Python `webhook_dispatcher` 与 Java `WebhookDispatcher` 使用同一 JSON envelope 投递。
- Redis 当前用于缓存、重放防护或未来队列能力；RabbitMQ 当前在 compose 与 Java 配置中预留，不承担 NeuroBus 的默认传输层。

## 边界规则

- Python 是 API 网关和主业务协调者；只有 `PaymentGatewayService.should_proxy_to_java()` 返回 true 的路径才代理给 Java。
- Java 支付服务是支付/钱包状态的权威写入方时，支付成功事件由 Java 发布，Python 管理端通过 `/api/webhooks/admin/replay` 转发到 Java 重放。
- 退款申请与审核仍由 Python `refund_api` 负责，因此退款事件由 Python 发布。
- 事件消费者必须按 `type + version` 识别契约，按 `id` 或 `idempotency_key` 做幂等。

## Webhook Envelope

```json
{
  "id": "payment.paid:MOD123",
  "type": "payment.paid",
  "version": 1,
  "source": "modstore-python",
  "aggregate_id": "MOD123",
  "created_at": 1710000000,
  "data": {}
}
```

HTTP 投递头：

- `X-Modstore-Webhook-Id`: 事件 id
- `X-Modstore-Webhook-Event`: 事件 type
- `X-Modstore-Webhook-Timestamp`: 秒级时间戳
- `X-Modstore-Webhook-Signature`: 可选，`sha256=<hmac>`，由 `MODSTORE_WEBHOOK_SECRET` 启用

## 事件注册表

事件常量定义在：

- Python: `modstore_server/eventing/contracts.py`
- Java: `com.modstore.event.EventContracts`

| 事件 | 版本 | 聚合 | 发布方 | 关键字段 |
| --- | --- | --- | --- | --- |
| `payment.paid` | 1 | payment_order | Python 或 Java | `out_trade_no`, `user_id`, `subject`, `total_amount`, `order_kind` |
| `wallet.balance_changed` | 1 | wallet | Python | `user_id`, `amount`, `source_order_id`, `transaction_type` |
| `refund.approved` | 1 | refund | Python | `refund_id`, `order_no`, `user_id`, `amount`, `status` |
| `refund.rejected` | 1 | refund | Python | `refund_id`, `order_no`, `user_id`, `amount`, `status` |
| `refund.failed` | 1 | refund | Python | `refund_id`, `order_no`, `user_id`, `amount`, `status` |

`payment.order_paid` 是 legacy alias，发布时会规范化为 `payment.paid`。

## 运维约定

- `MODSTORE_WEBHOOK_URL` 为空时事件仍会写入本地事件文件，投递结果为 skipped。
- Python outbox 文件由 `MODSTORE_WEBHOOK_EVENTS_DIR` 控制；compose 中默认为 `/data/webhook_events`。
- 如需跨进程 NeuroBus，应新增 outbox consumer 或 RabbitMQ adapter，不能直接假设 `InMemoryNeuroBus` 跨服务可见。
