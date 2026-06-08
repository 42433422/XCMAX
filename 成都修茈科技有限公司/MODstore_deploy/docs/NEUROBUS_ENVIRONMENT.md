# NeuroBus 环境变量

进程内领域事件总线由 [`modstore_server/eventing/global_bus.py`](../modstore_server/eventing/global_bus.py) 构建。

## `MODSTORE_BUS`

- **默认**：未设置或 `memory` → 使用 `InMemoryNeuroBus`（单进程内投递）。
- **可选**：`rabbitmq` / `rmq` / `amqp` → 尝试 `RabbitMqNeuroBus`；初始化失败时回退内存总线并打日志。

## `MODSTORE_BUS_SHADOW`

- **默认**：空、`0`、`false`、`no`、`off` → 不启用影子双写，仅主总线。
- **启用**：设为上述以外的真值时，主总线仍处理订阅与投递；影子总线尽力 `subscribe` / `publish`，失败仅记录日志（灰度双写）。

## 预发 / 生产建议

- 单机或尚无 RabbitMQ 时保持默认即可。
- 切 RabbitMQ 前先在预发打开 `MODSTORE_BUS=rabbitmq` 验证连接与权限。
- 影子双写仅在明确灰度窗口开启；避免在生产长期双写未监控的次要总线。

## 与测试

单测可通过替换 `neuro_bus` 或避免调用 `install_default_subscribers` 保持总线安静；勿依赖「默认开启影子」行为。
