# MODstore 混沌演练

本目录提供单机/少量服务器部署下的低风险混沌演练入口。脚本默认 dry-run，不会真正停止或重启服务；只有显式传入 `--confirm` 才会执行。

## 支持场景

| 场景 | 影响验证 |
| --- | --- |
| `redis-stop` | Redis 不可用时缓存、防重放、支付和 RAG 的降级与告警 |
| `rabbitmq-stop` | RabbitMQ 不可用时预留消息链路和 Java 服务健康 |
| `payment-restart` | Java 支付服务重启时 FastAPI 代理、前端提示和恢复时间 |
| `postgres-stop` | 数据库不可用时 health/readiness、Java 连接池和 5xx 告警 |
| `api-restart` | FastAPI 重启时入口恢复、Prometheus target 和前端体验 |

## dry-run

```bash
python chaos/chaos_drill.py --scenario payment-restart
```

## 预发执行

```bash
python chaos/chaos_drill.py \
  --scenario payment-restart \
  --duration 60 \
  --confirm
```

执行前后脚本会调用 `scripts/sre_smoke_check.py`。如果只想观察命令执行本身，可加 `--skip-smoke`。

## 生产约束

- 默认只在预发、测试或隔离环境执行。
- 生产演练必须先确认回滚窗口、值班人员、业务低峰期和备份状态。
- `postgres-stop`、`redis-stop` 属于高风险场景，生产不建议执行。
- 每次演练后要把结果写入 `docs/runbooks/chaos-game-day.md` 的复盘模板。
