# MODstore Prometheus + Grafana 监控

## 指标端点

- Python FastAPI: `GET /metrics`
- Java payment service: `GET /actuator/prometheus`
- Prometheus UI: `http://localhost:${PROMETHEUS_PORT:-9090}`
- Grafana UI: `http://localhost:${GRAFANA_PORT:-3000}`

## 启动

完整业务栈和监控一起启动：

```bash
docker compose --profile app up -d
```

只启动监控服务时，需要确保 `api:8765` 与 `payment-service:8080` 在同一 compose 网络内可解析，或调整 `monitoring/prometheus/prometheus.yml` 的 targets。

```bash
docker compose --profile monitoring up -d prometheus grafana
```

默认 Grafana 账号密码为 `admin/admin`，可通过 `GRAFANA_ADMIN_USER`、`GRAFANA_ADMIN_PASSWORD` 覆盖。

部署后建议立即执行冒烟检查：

```bash
python scripts/sre_smoke_check.py \
  --base-url http://127.0.0.1:${MODSTORE_API_PORT:-8765} \
  --market-url http://127.0.0.1:${MODSTORE_MARKET_PORT:-4173} \
  --payment-url http://127.0.0.1:${JAVA_PAYMENT_PORT:-8080} \
  --prometheus-url http://127.0.0.1:${PROMETHEUS_PORT:-9090}
```

## 文件位置

- Prometheus 配置：`monitoring/prometheus/prometheus.yml`
- Prometheus 告警规则：`monitoring/prometheus/rules/modstore-alerts.yml`
- Grafana datasource：`monitoring/grafana/provisioning/datasources/prometheus.yml`
- Grafana dashboard provider：`monitoring/grafana/provisioning/dashboards/dashboards.yml`
- 默认 dashboard：`monitoring/grafana/dashboards/modstore-overview.json`
- 部署冒烟检查：`scripts/sre_smoke_check.py`

## 已落地告警

- `ModstoreTargetDown`：核心 Prometheus target 持续 2 分钟不可抓取。
- `ModstoreApiHigh5xxRate`：FastAPI 5xx 速率持续异常。
- `ModstoreApiHighP95Latency`：FastAPI p95 延迟持续超过 1 秒。
- `ModstorePaymentProxyHigh5xxRate`：FastAPI 到 Java 支付代理 5xx 异常。
- `ModstorePaymentProxyHighP95Latency`：支付代理 p95 延迟持续超过 2 秒。
- `ModstoreJavaPaymentHigh5xxRate`：Java 支付服务 5xx 异常。
- `ModstoreJavaHeapHigh`：Java heap 使用率持续超过 85%。
- `ModstoreHikariPoolNearSaturation`：Java 数据库连接池持续接近饱和。

## 初始 SLO

| 服务链路 | SLO | 告警入口 |
| --- | --- | --- |
| 入口健康 | 30 天可用性 >= 99.5% | `ModstoreTargetDown`、冒烟检查 |
| 登录/市场浏览 | p95 < 1s，5xx < 0.5% | FastAPI 请求速率与延迟 |
| 支付/钱包 | p95 < 2s，5xx < 0.2% | 支付代理与 Java HTTP 指标 |
| WebSocket 实时链路 | 连接成功率 >= 99%，异常断开可恢复 | Nginx/FastAPI 日志、压测脚本 |
| LLM/RAG | 首响应可用率优先，外部供应商错误单独归因 | FastAPI path 维度指标 |

## 值班响应

1. 打开 Grafana `MODstore Overview`，确认是入口不可达、应用错误、支付代理、Java 资源还是 Prometheus 自身异常。
2. 执行 `scripts/sre_smoke_check.py`，拿到可复现的失败点和延迟。
3. 查看对应服务日志：`api`、`payment-service`、`market`、`postgres`、`redis`、`rabbitmq`。
4. 支付相关事故优先参考 `docs/PAYMENT_GRAY_RELEASE.md` 的回滚和数据一致性说明。
5. 处理完成后记录：发现时间、影响范围、触发告警、止血动作、恢复时间、后续行动项。
