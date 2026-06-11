# Event Driven Architecture

目标：让关键业务副作用可追踪、可重放、可被通知和运营指标消费。

已落点：

- `MODstore_deploy/modstore_server/eventing/events.py`：标准 `DomainEvent` envelope。
- `MODstore_deploy/modstore_server/eventing/bus.py`：`InMemoryNeuroBus`。
- `MODstore_deploy/modstore_server/eventing/outbox.py`：文件 outbox，默认写入 `modstore_server/data/event_outbox.jsonl`。
- `MODstore_deploy/docs/contracts/events/README.md`：事件契约说明。

首批事件：

- `payment.order_paid`
- `wallet.balance_changed`
- `employee.pack_registered`
- `workflow.sandbox_completed`
- `catalog.package_published`
- `llm.quota_consumed`

当前消费者：

- outbox 持久化消费者订阅 `*`，所有事件写入 JSONL。
- `webhook_dispatcher` 仍保持同步 webhook 兼容，同时也向 NeuroBus 发布事件。

后续扩展：

- 数据库 outbox 表。
- 事件重放后台任务。
- Redis Streams / RabbitMQ adapter。
- 通知、指标、审计各自独立消费者。
