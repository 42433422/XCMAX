# XCAGI 监控栈：Grafana 仪表盘 + Prometheus 告警

## 4 块核心仪表盘

放在 `grafana/dashboards/`，由 Kustomize 注入到 ConfigMap 后挂载到 Grafana：

| 文件 | 关注点 | 关键指标 |
| --- | --- | --- |
| `xcagi-api-overview.json` | API 总览 | P50/P95/P99 延迟、QPS、5xx 错误率、Top10 慢接口 / Top10 错误接口 |
| `xcagi-mod-store.json` | Mod 商店 | catalog RPS、Mod 加载成功率、Mod 数量、扫描 P95、SQLite 副本、Mod header 拒绝原因 |
| `xcagi-neurobus.json` | 神经总线 | 按 domain 事件数、丢弃原因、意图识别 P95、断路器状态、按 domain 处理 P95 |
| `xcagi-infrastructure.json` | 基础设施 | Pod CPU/内存/网络/重启、磁盘、Pod status |

## 告警规则（`prometheus/alert_rules.yml`）

按 group 拆分，severity + team label 双维度路由：

- `xcagi_api` — `HighErrorRate`（critical）、`HighLatencyP95/P99`（warning/critical）
- `xcagi_mod_store` — `ModLoadFailure`、`MissingSQLiteCopy`
- `xcagi_neuro_bus` — `CircuitBreakerOpen`、`NeuroBusDrops`
- `xcagi_infrastructure` — `ServiceDown`、`HighMemoryUsage`、`HighCPUUsage`、`DiskSpaceLow`、`PodCrashLooping`、`AIRequestFailures`

## Staging 部署

完整步骤见 **[`STAGING_RUNBOOK.md`](STAGING_RUNBOOK.md)**（计划 T34–T38；截图与真数据待 staging）。

## 部署（Kustomize）

```bash
# Prometheus（注入 alert_rules.yml）
kubectl apply -k k8s/monitoring/prometheus

# Grafana（注入 4 块仪表盘 + provisioning）
kubectl apply -k k8s/monitoring/grafana
```

## 本地调试（仅 rules）

```bash
# 启动 Prometheus 容器，把 rules 目录挂进去
docker run --rm -p 9090:9090 \
  -v "$PWD/k8s/monitoring/prometheus/alert_rules.yml:/etc/prometheus/rules/alert_rules.yml:ro" \
  -v "$PWD/k8s/monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  prom/prometheus:latest

# 验证 rules 语法
promtool check rules k8s/monitoring/prometheus/alert_rules.yml
```

## 添加新仪表盘

1. 在 Grafana UI 中导出 JSON 放到 `grafana/dashboards/`
2. 在 `grafana/kustomization.yml` 的 `grafana-dashboards` `files:` 列表里加一行
3. `kubectl apply -k k8s/monitoring/grafana`

## 添加新告警

1. 在 `prometheus/alert_rules.yml` 对应 group 下追加
2. `promtool check rules` 通过即可
3. 重载 Prometheus：`curl -X POST http://prom:9090/-/reload`（需要 `--web.enable-lifecycle`）
