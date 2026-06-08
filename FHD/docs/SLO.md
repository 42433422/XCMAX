# XCAGI 服务等级目标（SLO）

> **实测证据**：[`docs/evidence/slo/`](evidence/slo/) · **声称对照**：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)  
> **落盘**：[`metrics/sla-snapshot.json`](../metrics/sla-snapshot.json) · **滚动读数**：`metrics/slo-measured-YYYYMMDD.json`

## 核心 SLO（M0 五域）

| ID | 名称 | 目标 | PromQL（窗口可配 7d/30d） | Grafana 面板 |
|----|------|------|---------------------------|--------------|
| SLO-API-01 | API 可用性 | ≥ 99.9% | `1 - (sum(rate(api_requests_total{status=~"5.."}[WINDOW])) / clamp_min(sum(rate(api_requests_total[WINDOW])),1))` | `xcagi-slo:4` |
| SLO-API-02 | 登录 P95 | < 500ms | `histogram_quantile(0.95, sum by (le) (rate(login_request_duration_seconds_bucket[WINDOW]))) * 1000` | `xcagi-slo:6` |
| SLO-API-03 | API 错误率 | < 0.1% | `sum(rate(api_requests_total{status=~"5.."}[WINDOW])) / sum(rate(api_requests_total[WINDOW]))` | `xcagi-slo:5` |
| SLO-AI-01 | 聊天首包 P95 | < 1500ms | `histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket[WINDOW]))) * 1000` | `xcagi-slo:3` |
| SLO-BUS-01 | NeuroBus 投递 | ≥ 99.95% | `1 - (sum(rate(neurobus_events_dead_lettered_total[WINDOW])) + sum(rate(neurobus_events_lost_total[WINDOW]))) / clamp_min(sum(rate(neurobus_events_published_total[WINDOW])),1)` | `xcagi-slo:7` |

将 `WINDOW` 替换为 `7d`（验收）或 `30d`（合同滚动）。

## 数据源

| 层 | 路径 |
|----|------|
| 应用指标 | `GET /metrics` — [`app/utils/metrics.py`](../app/utils/metrics.py) |
| Prometheus | [`k8s/monitoring/prometheus/`](../k8s/monitoring/prometheus/)（静态 ConfigMap） |
| Prometheus Operator | [`k8s/monitoring/servicemonitor-xcagi-backend.yaml`](../k8s/monitoring/servicemonitor-xcagi-backend.yaml) · [`prometheusrule-xcagi-alerts.yaml`](../k8s/monitoring/prometheusrule-xcagi-alerts.yaml) — `kubectl apply -k k8s/monitoring/` |
| Grafana 看板 | [`k8s/monitoring/grafana/dashboards/xcagi-slo.json`](../k8s/monitoring/grafana/dashboards/xcagi-slo.json) |
| 本地栈 | `bash scripts/observability/local_stack_up.sh` |
| Staging runbook | [`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md) |

## 探针与 CI

| 探针 | 命令 |
|------|------|
| Health 延迟 | `pytest tests/test_sla_health_probe.py`（nightly [`sla-probe.yml`](../.github/workflows/sla-probe.yml)） |
| 前端 SLA | `npm run test:e2e:sla` |
| Prometheus 采集 | `python scripts/observability/collect_slo_metrics.py --window 30d` |
| 7 天验收 | `bash scripts/observability/run_staging_7d_acceptance.sh` |

## 验收模式

| 模式 | 适用 | 证据 |
|------|------|------|
| `ab_supplement` | 内部 demo | `acceptance-20260605.yaml` |
| `k6_7d` / `staging_natural` | **合同签署** | `docs/evidence/slo/grafana-staging-m0-*.png` + `reading_7d` 非 null |

`ab_supplement` **不适用** 99.9% SLA 合同（见 [`M0-remaining-gaps.md`](M0-remaining-gaps.md)）。
