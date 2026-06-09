# payment_orders（运行时目录 · 不入库）

本目录存放 MODstore 支付订单 JSON 快照，由服务在运行时写入。

- **禁止**将 `order_*.json` 提交到 Git（含真实 `out_trade_no`、金额、用户 ID）。
- 尽调/试点留证请使用脱敏示例：[`docs/evidence/`](../../docs/evidence/) 或 `order_*.example.json` 模式。
- 本地开发：服务启动后自动创建；删除本目录内容不影响源码。
