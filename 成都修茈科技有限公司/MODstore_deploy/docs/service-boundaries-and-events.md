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

Python 支付兼容入口 `alipay_service.py` 组合三个职责：`alipay_config.py` 负责配置与诊断，
`payments/alipay_gateway.py` 负责 SDK 调用、验签及协议结果，`payments/checkout.py` 负责移动支付、
网页支付、二维码支付的回退顺序。SDK 返回空白或非字符串支付参数时视为失败，继续原有回退流程，
避免返回成功却没有可用支付链接。交易号、金额、回调签名和退款调用契约保持不变。

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

| 事件                     | 版本 | 聚合          | 发布方         | 关键字段                                                           |
| ------------------------ | ---- | ------------- | -------------- | ------------------------------------------------------------------ |
| `payment.paid`           | 1    | payment_order | Python 或 Java | `out_trade_no`, `user_id`, `subject`, `total_amount`, `order_kind` |
| `wallet.balance_changed` | 1    | wallet        | Python         | `user_id`, `amount`, `source_order_id`, `transaction_type`         |
| `refund.approved`        | 1    | refund        | Python         | `refund_id`, `order_no`, `user_id`, `amount`, `status`             |
| `refund.rejected`        | 1    | refund        | Python         | `refund_id`, `order_no`, `user_id`, `amount`, `status`             |
| `refund.failed`          | 1    | refund        | Python         | `refund_id`, `order_no`, `user_id`, `amount`, `status`             |

`payment.order_paid` 是 legacy alias，发布时会规范化为 `payment.paid`。

## 运维约定

- `MODSTORE_WEBHOOK_URL` 为空时事件仍会写入本地事件文件，投递结果为 skipped。
- Webhook 事件记录目录由 `MODSTORE_WEBHOOK_EVENTS_DIR` 控制；compose 中默认为 `/data/webhook_events`。
- NeuroBus 文件事件记录依次采用构造参数、`MODSTORE_EVENT_OUTBOX_PATH`、
  `$MODSTORE_RUNTIME_DIR/event_outbox.jsonl` 或系统临时目录下的 `modstore_runtime/event_outbox.jsonl`。
  所有路径先解析文件及目录符号链接，并复用 `require_private_directory` 拒绝 Git 工作树内目标。
  生产部署应配置外部持久目录，默认临时目录不保证跨清理保留记录。事务 outbox 仍由数据库管理。
- 如需跨进程 NeuroBus，应新增 outbox consumer 或 RabbitMQ adapter，不能直接假设 `InMemoryNeuroBus` 跨服务可见。

巡视依赖由 `surface_audit_runtime`（路径与健康探测）、`surface_audit_processes`（启动与清理）、
`surface_audit_services`（各服务启动流程）和 `surface_audit_readiness`（汇总就绪状态）承担。
`surface_audit_deps` 保留调用入口并显式组合这些职责。PID 与日志根目录使用
`MODSTORE_RUNTIME_STATE_ROOT`、`MODSTORE_RUNTIME_DIR` 或外部系统临时目录 `modstore_runtime`，
拒绝源码工作树目标。清理只针对该次巡视拥有的临时进程，保留长期运行的 MODstore；安装失败、
健康检查失败或启动失败不能记为 ready。对应回归见 `tests/test_surface_audit_dependency_components.py`。

## 工作台职责与资源所有权

`workbench_api.py` 保留公开 Python 调用、FastAPI 路由和鉴权依赖，并在请求或任务入口构造职责组件。
`workbench/` 内部组件接收各自需要的命名依赖，不回查 API 模块，也不接收整个 facade。

| 组件 | 职责 |
| --- | --- |
| `schemas`、`intent` | 请求校验、意图别名和进度步骤词汇 |
| `sessions`、`delivery_sessions` | 外部快照存储、进度状态、HTTP 与客户交付共用的会话 |
| `uploads` | 有界附件读取与全部上传对象的关闭 |
| `coordinator` | 用户查找、需求解释与脚本、Mod 套件、员工或画布流程选择 |
| `script_pipeline`、`canvas_pipeline`、`suite_pipeline` | 三种独立交付流程 |
| `employee_state`、`employee_pipeline` | 员工构建数据、路径约束、重试检查点与流程顺序 |
| `employee_planning`、`employee_generation` | 规划、生成与清单检查 |
| `employee_workflows`、`employee_registration` | 工作流绑定、目录登记与工作流执行证据 |
| `employee_runtime_checks`、`employee_quality`、`employee_delivery` | 运行检查、关键质量裁决与交付产物 |
| `catalog`、`script_delivery` | 目录元数据更新、包刷新与可移植脚本引用 |
| `session_api`、`employee_drafts`、`employee_commands`、`employee_packages` | HTTP 用例和资源生命周期 |
| `research_api`、`speech_api`、`vibe_api`、`task_api` | 研究、语音、编码与派单适配 |
| `planning`、`package_quality`、`vibe_readiness` | 可复用的规划和包就绪策略 |

`EmployeeBuildState` 只保存任务输入与结果；数据库会话、用户、生成、目录和进度操作属于对应依赖端口。
生成失败时没有有效包路径，不能以当前目录冒充产物。重试可复用已生成的包和绑定，但必须重新登记并取得
工作流、包、冒烟、宿主和质量证据。关键质量失败保持 error 状态，不附加完成产物。
`workbench_delivery_bridge.py` 保留两个公开入口，共享实现显式接收存储、执行器、进度操作和内联任务集合。

会话快照写入 `$MODSTORE_RUNTIME_DIR/workbench_sessions`，未配置时使用系统临时目录下的
`modstore_runtime`；需要跨临时目录清理保留会话的部署应配置外部持久目录。私有存储策略拒绝 Git
工作树内的路径，包括解析后指向工作树的符号链接。外部快照不存在时，可读取原
`modstore_server/data/workbench_sessions` 中 ID 匹配的旧快照并迁移到外部目录；旧文件保留，后续只写外部目录。
每次替换使用独立临时文件，避免中间文件冲突；它仍是快照存储，不提供跨工作进程的事务或状态合并。

每个上传文件每次读取最多 1 MiB，在最多读取 30 MiB 加一字节后拒绝超限文件。成功、拒绝或取消都关闭
所有传入对象，包括尚未读取的文件。该限制针对单个文件，不是整个 multipart 请求的总量限制。
元数据校验失败同样释放上传对象。员工草稿 SSE 迭代器拥有生成任务：关闭迭代器时先取消并等待任务，
再关闭数据库作用域，避免生成继续使用已释放的会话。

公开的 63 个函数调用形状和 19 条路径的完整 OpenAPI 契约保持兼容；原根模块依赖注入点在组合入口显式接线。
`tests/test_workbench_components.py` 验证初次生成、质量通过/拒绝、重试证据、私有快照迁移、源码路径拒绝、
附件读取与释放、非法脚本元数据及 SSE 取消顺序。原有员工清单、包保留、私有交付隔离、Word 运行检查、
脚本执行、工作台资产和终态保护测试继续适用。验证环境使用本项目声明的 SQLAlchemy `>=2.0,<2.1`；
真实编译测试还需要现有 esbuild 依赖，本地 HTTP 集成测试需要 loopback 网络。
