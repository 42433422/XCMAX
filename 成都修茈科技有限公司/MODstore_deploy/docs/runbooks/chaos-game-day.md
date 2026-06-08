# 混沌演练 Runbook

## 演练前检查

- 明确演练环境，不在未知生产环境执行。
- 执行 `python scripts/sre_smoke_check.py --base-url ... --market-url ... --payment-url ... --prometheus-url ...`，确认基线健康。
- 打开 Grafana `MODstore Overview`，记录演练前 5 分钟的入口、支付代理、Java JVM、Hikari 和告警状态。
- 确认恢复命令可执行，例如 `docker compose up -d <service>`。

## 标准步骤

1. dry-run：`python chaos/chaos_drill.py --scenario <name>`。
2. 预发执行：`python chaos/chaos_drill.py --scenario <name> --duration 60 --confirm`。
3. 观察告警、日志、前端行为和冒烟检查结果。
4. 恢复后继续观察至少 10 分钟。

## 场景预期

| 场景 | 预期影响 | 恢复标准 |
| --- | --- | --- |
| `redis-stop` | Redis target down，部分缓存/防重放相关功能报错或降级 | Redis healthy，FastAPI/Java 5xx 恢复基线 |
| `rabbitmq-stop` | RabbitMQ target down，Java 预留消息链路告警 | RabbitMQ healthy，payment-service 无持续错误 |
| `payment-restart` | 支付代理短暂 502，Java target 短暂 down | `/actuator/health` UP，支付代理 5xx 归零 |
| `postgres-stop` | API health database degraded，Java 数据库连接失败 | PostgreSQL healthy，Hikari 连接恢复 |
| `api-restart` | FastAPI target 短暂 down，前端 API 请求失败 | `/api/health` 与 `/health/ready` 恢复 |

## 复盘模板

- 演练时间：
- 演练环境：
- 场景：
- 影响范围：
- 告警是否触发：
- 是否符合预期：
- 实际恢复时间：
- 发现的问题：
- 后续行动项：

## 演练记录索引

每次 dry-run 与预发 `--confirm` 都登记到 [`exercises/`](exercises/README.md) 下的日期目录；最近一次见 [`exercises/2026-05-04/EXERCISE.md`](exercises/2026-05-04/EXERCISE.md)。
