# 事故响应 Runbook

## 快速判断

```bash
python scripts/sre_smoke_check.py \
  --base-url http://127.0.0.1:8765 \
  --market-url http://127.0.0.1:4173 \
  --payment-url http://127.0.0.1:8080 \
  --prometheus-url http://127.0.0.1:9090
```

同时打开 Grafana `MODstore Overview`，确认：

- `up` 是否有 target down。
- FastAPI 5xx 和 p95 是否异常。
- 支付代理 5xx 和 p95 是否异常。
- Java heap/Hikari 是否接近饱和。
- 当前 firing alerts。

## SEV1 止血动作

| 现象 | 优先动作 |
| --- | --- |
| 整站不可用 | 检查 `market`、`api`、Nginx/DNS；必要时回滚前端或重启入口 |
| 登录不可用 | 查看 FastAPI 日志、数据库连接、JWT/环境变量 |
| 支付不可用 | 执行支付灰度预检；必要时按 `PAYMENT_GRAY_RELEASE.md` 回滚 |
| 数据库不可用 | 停止高风险写入，按灾备 Runbook 恢复或切备机 |
| Redis/RabbitMQ 不可用 | 先恢复依赖容器，再观察业务错误是否自动恢复 |

## 沟通模板

- 事故等级：
- 开始时间：
- 影响范围：
- 当前状态：
- 正在执行的止血动作：
- 下一次更新时间：

## 复盘模板

- 时间线：
- 用户影响：
- 根因：
- 哪些告警触发：
- 哪些告警缺失：
- 止血是否及时：
- 后续行动项：
- 负责人和截止时间：
