# XCAGI 服务等级目标（SLO）

> **实测证据**：[`docs/evidence/slo/`](evidence/slo/) · **声称对照**：[`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md)  
> **落盘**：[`metrics/sla-snapshot.json`](../metrics/sla-snapshot.json) · **滚动读数**：`metrics/slo-measured-YYYYMMDD.json`

## 核心 SLO（M0 五域）

| ID | 名称 | 目标 | PromQL（窗口可配 7d/30d） | Grafana 面板 |
|----|------|------|---------------------------|--------------|
| SLO-API-01 | API 可用性 | ≥ 99.9% | `1 - (sum(rate(api_requests_total{status=~"5.."}[WINDOW])) / clamp_min(sum(rate(api_requests_total[WINDOW])),1))` | `xcagi-slo:4` |
| SLO-API-02 | 登录 P95 | < 500ms | `histogram_quantile(0.95, sum by (le) (rate(api_request_duration_seconds_bucket{endpoint="/api/auth/login"}[WINDOW]))) * 1000` | `xcagi-slo:6` |
| SLO-API-03 | API 错误率 | < 0.1% | `sum(rate(api_requests_total{status=~"5.."}[WINDOW])) / sum(rate(api_requests_total[WINDOW]))` | `xcagi-slo:5` |
| SLO-AI-01 | 聊天首包 P95 | < 1500ms | `histogram_quantile(0.95, sum by (le) (rate(chat_stream_first_byte_seconds_bucket[WINDOW]))) * 1000` | `xcagi-slo:3` |
| SLO-BUS-01 | NeuroBus 投递 | ≥ 99.95% | `1 - (sum(rate(neurobus_events_dead_lettered_total[WINDOW])) + sum(rate(neurobus_events_lost_total[WINDOW]))) / clamp_min(sum(rate(neurobus_events_published_total[WINDOW])),1)` | `xcagi-slo:7` |

将 `WINDOW` 替换为 `7d`（验收）或 `30d`（合同滚动）。

## 业务 SLO（BIZ 五域）

> **场景**：补齐 SME 业务数据自动化的核心业务可观测性（客户/文档/导出/MOD）。
> **指标定义**：[`app/utils/metrics.py`](../app/utils/metrics.py) "业务 SLI 指标" 段 + `record_customer_op` / `record_doc_recognition` / `record_export_task` / `record_mod_install` 辅助函数。
> **采集**：与 M0 五域共用 `collect_slo_metrics.py`，产物同落 `metrics/slo-measured-YYYYMMDD.json`。

| ID | 名称 | 目标 | PromQL（窗口可配 7d/30d） | 埋点位置 |
|----|------|------|---------------------------|---------|
| SLO-BIZ-01 | 客户 CRUD P95 | < 800ms | `histogram_quantile(0.95, sum by (le) (rate(customer_op_duration_seconds_bucket[WINDOW]))) * 1000` | 客户路由（create/update/delete/query） |
| SLO-BIZ-02 | 客户 CRUD 错误率 | < 0.5% | `sum(rate(customer_op_total{status="error"}[WINDOW])) / clamp_min(sum(rate(customer_op_total[WINDOW])),1)` | 同上 |
| SLO-BIZ-03 | 文档识别 P95 | < 5s | `histogram_quantile(0.95, sum by (le) (rate(doc_recognition_duration_seconds_bucket[WINDOW]))) * 1000` | OCR / Excel / Word 解析路径 |
| SLO-BIZ-04 | 数据导出 P95 | < 30s | `histogram_quantile(0.95, sum by (le) (rate(export_task_duration_seconds_bucket[WINDOW]))) * 1000` | Excel / CSV / PDF 导出任务 |
| SLO-BIZ-05 | MOD 安装成功率 | ≥ 99% | `1 - sum(rate(mod_install_total{status="error"}[WINDOW])) / clamp_min(sum(rate(mod_install_total[WINDOW])),1)` | MOD 安装/卸载路径 |

### 标签约束

| 指标 | 标签 | 基数 | 取值 |
|------|------|------|------|
| `customer_op_total` | `operation`, `status` | 4 × 2 | `create/update/delete/query` × `success/error` |
| `customer_op_duration_seconds` | `operation` | 4 | 同上 |
| `doc_recognition_total` | `doc_type`, `status` | 4 × 2 | `excel/word/ocr/pdf` × `success/error` |
| `doc_recognition_duration_seconds` | `doc_type` | 4 | 同上 |
| `export_task_total` | `export_type`, `status` | 3 × 2 | `excel/csv/pdf` × `success/error` |
| `export_task_duration_seconds` | `export_type` | 3 | 同上 |
| `mod_install_total` | `operation`, `status` | 4 × 2 | `install/uninstall/activate/deactivate` × `success/error` |

均满足"标签基数 < 20"（铁律 8）；禁止使用 `user_id` / `tenant_id` / `request_id` 等高基数标签。

### 埋点示例

```python
from app.utils.metrics import record_customer_op, record_doc_recognition
import time

# 客户 CRUD 路由
start = time.time()
try:
    customer = await customer_app_service.create(...)
    record_customer_op("create", "success", time.time() - start)
    return customer
except Exception:
    record_customer_op("create", "error", time.time() - start)
    raise

# 文档识别
start = time.time()
try:
    result = await ocr_service.recognize(file_bytes)
    record_doc_recognition("excel", "success", time.time() - start)
    return result
except Exception:
    record_doc_recognition("excel", "error", time.time() - start)
    raise
```

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

## 覆盖率门禁口径（质量 SLO · Delta A）

后端覆盖率门禁唯一硬 gate 为**行为口径**（2026-08-05 起）：CI 用
`coverage_ratchet.py --check --behavior --require-backend --record` 排除
`coverage_ramp` 注水 stub（`-m 'not coverage_ramp'`）后硬阻断。floor 见
`metrics/coverage_ratchet_baseline.json` 的 `behavior_floors {lines, branches}`
（只升不降）；全量 `fail_under` 保留为参考/趋势口径。

## 验收模式

| 模式 | 适用 | 证据 |
|------|------|------|
| `ab_supplement` | 内部 demo | `acceptance-20260605.yaml` |
| `k6_7d` / `staging_natural` | **合同签署** | `docs/evidence/slo/grafana-staging-m0-*.png` + `reading_7d` 非 null |

`ab_supplement` **不适用** 99.9% SLA 合同（见 [`M0-remaining-gaps.md`](M0-remaining-gaps.md)）。

## Tier C 压测 SLO（高并发验收）

与 M0 五域并列；证据目录 [`docs/evidence/tier-c/`](evidence/tier-c/)。

| ID | 名称 | 目标 | k6 场景 | 证据 |
|----|------|------|---------|------|
| SLO-TIER-C-01 | 简单 API 吞吐 | 集群持续 ≥1000 RPS × 10min | `scripts/loadtest/tier_c_sustained.js` | `tier-c/sustained-report.json` |
| SLO-TIER-C-02 | 简单 API 错误率 | < 0.1%（与 SLO-API-03 一致） | 同上 | 同上 |
| SLO-TIER-C-03 | 简单 API P95 | health/login/只读列表 P95 < 500ms | 同上 | Grafana `xcagi-slo:6` |
| SLO-TIER-C-04 | AI 流式并发 | ≥200 路并发流 × 15min | `scripts/loadtest/tier_c_chat_streams.js` | `tier-c/chat-streams-report.json` |
| SLO-TIER-C-05 | AI 首包 P95 | < 1500ms（SLO-AI-01） | 同上 | Grafana `xcagi-slo:3` |
| SLO-TIER-C-06 | Celery 队列延迟 | OCR/导出 P95 < 60s | Prometheus `celery_task_duration` | `tier-c/celery-latency.png` |
| SLO-TIER-C-07 | 7 天自然流量 | k6 阶梯流量 + M0 全绿 | `k8s/monitoring/k6-configmap.yaml` `tier_c_ramp` | `docs/evidence/slo/` |

本地冒烟：

```bash
k6 run scripts/loadtest/tier_c_smoke.js
k6 run -e STREAM_CONCURRENCY=50 scripts/loadtest/tier_c_chat_streams.js
```
