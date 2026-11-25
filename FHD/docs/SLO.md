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

将 `WINDOW` 替换为实际观察窗口；正式生产准入使用 `90d`，`7d` / `30d` 仅供阶段观察。生产环境标签、固定目标、查询和最小样本数以 [`collect_slo_metrics.py`](../scripts/observability/collect_slo_metrics.py) 为唯一执行口径，不能省略环境过滤或仅凭图表判定通过。

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
| Prometheus | [`prometheus.production.yml`](../ops/monitoring/prometheus.production.yml)，原生生产采集配置 |
| 告警规则 | [`production-alerts.yml`](../ops/monitoring/production-alerts.yml)，真实 `promtool` 在 [`slo-promql-tests.yml`](../.github/workflows/slo-promql-tests.yml) 执行 |
| Grafana 看板 | [`ops/monitoring/grafana/`](../ops/monitoring/grafana/) 的既有 provisioning |
| 本地栈 | `bash scripts/observability/local_stack_up.sh` |
| 生产采集工作流 | [`slo-metrics-collect.yml`](../.github/workflows/slo-metrics-collect.yml)，正式 Day 0 仍需真实发布身份收敛 |

## 探针与 CI

| 探针 | 命令 |
|------|------|
| Health 延迟 | `pytest tests/test_sla_health_probe.py`；真实 HTTP、前端预算与合成业务规模回归见 [`performance-smoke.yml`](../.github/workflows/performance-smoke.yml)，原始证据上传为 `performance-<源码SHA>`，不替代生产观察窗口 |
| 前端 SLA | `npm run test:e2e:sla` |
| Prometheus 采集 | `python scripts/observability/collect_slo_metrics.py --window 30d` |
| 生产窗口 | `python scripts/observability/verify_production_slo_window.py --evidence-dir <原始证据目录> --release-id <原发布ID>`；默认连续 90 天，最终核对 10 项指标与最小样本 |
| 近期采集观察 | 同一 verifier 的 `--observation-days 7`；以当前 UTC 日期为终点，缺目标、篡改、缺日和采样不足均阻断 |
| Staging 7 天合成对话 | `SOURCE_SHA=<部署完整SHA> K6_EVIDENCE_DIR=<原始输出目录> bash scripts/observability/run_staging_7d_acceptance.sh` |

Staging 使用独立只读验收账号，在受控环境运行真实登录、聊天与原持久轮次回读。设置 `XCAGI_BASE_URL`、`E2E_USER`、`E2E_PASSWORD`、`SOURCE_SHA` 后，从 `FHD/` 启动：

```bash
mkdir -p "$K6_EVIDENCE_DIR"
XCAGI_SOAK_DURATION=168h K6_SUMMARY_PATH="$K6_EVIDENCE_DIR/k6-7d-summary.json" \
  k6 run --out "json=$K6_EVIDENCE_DIR/k6-7d-samples.jsonl" \
  scripts/observability/k6_7d_contract.js
```

`K6_EVIDENCE_DIR` 应为本轮独立且不存在旧输出的目录。`XCAGI_SOAK_DURATION` 控制场景时长；不要设置 k6 原生 `K6_DURATION`，它会替换已固定的到达率场景并被拒绝。短时冒烟保留实际时长，不能通过 7 天收尾验证。收尾要求完整 JSONL、原生 summary、同一运行 SHA、固定 30 次/分钟负载、全部检查通过及每轮原回执已完成；程序不会重发聊天 POST。

## 覆盖率门禁口径（质量 SLO · Delta A）

后端覆盖率门禁唯一硬 gate 为**行为口径**（2026-08-05 起）：CI 用
`coverage_ratchet.py --check --behavior --require-backend --record` 排除
`coverage_ramp` 注水 stub（`-m 'not coverage_ramp'`）后硬阻断。floor 见
`metrics/coverage_ratchet_baseline.json` 的 `behavior_floors {lines, branches}`
（只升不降）；全量 `fail_under` 保留为参考/趋势口径。

## 验收模式

| 模式 | 适用 | 证据 |
|------|------|------|
| 历史 `ab_supplement` | 内部 demo | 历史材料保持原范围，不作生产准入 |
| `k6_7d` | 合成 staging 对话稳定性 | 原生 k6 summary + 7 天完整 JSONL + 同版本持久回执；不能证明真实业务对账或生产 SLA |
| `preflight` / 近期 7 天观察 | 检查采集是否完整连续 | 固定抓取目标、真实成功样本数及当前窗口；不证明正式 SLO 达标 |
| `formal` | 正式生产 SLO 准入 | 已批准 Day 0、同一发布身份、连续 90 天不可变证据链、各目标覆盖率 ≥99%、Prometheus 实测保留 ≥120 天，以及最终指标/样本门槛全部通过 |

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
| SLO-TIER-C-07 | 7 天自然流量 | 真实业务流量 + M0 全绿 | 原始 Prometheus 观察；合成 k6 不能替代自然流量 | `docs/evidence/slo/` |

本地冒烟：

```bash
k6 run scripts/loadtest/tier_c_smoke.js
k6 run -e STREAM_CONCURRENCY=50 scripts/loadtest/tier_c_chat_streams.js
```
