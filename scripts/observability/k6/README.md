# k6 冒烟（T36–T37 流量补量占位）

本目录为 **说明入口**；可执行脚本在上一级 [`k6_smoke.sh`](../k6_smoke.sh)，压测逻辑复用 [`scripts/loadtest/smoke.js`](../../loadtest/smoke.js)。

## 快速用法

```bash
cd FHD
export BASE_URL=https://api.staging.example   # 或本地 http://127.0.0.1:5000

bash scripts/observability/k6_smoke.sh --check-only   # k6 + 脚本 + /api/health
bash scripts/observability/k6_smoke.sh               # 执行 30s smoke
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `BASE_URL` | API 根 URL（必填） |
| `K6_OUT` | 结果 JSON，默认 `scripts/loadtest/results-smoke.json` |

## 与 7 天验收的关系

- k6 **不能单独**替代连续 ≥7 天 scrape；在 `acceptance-*.yaml` 的 `observation_mode` 中标注 `k6_supplement` 或 `natural_7d`。
- 压测期间在 Grafana `xcagi-api-overview` 观察 P95 / 5xx。
- 字段模板：[`docs/evidence/slo/acceptance-TEMPLATE.yaml`](../../../docs/evidence/slo/acceptance-TEMPLATE.yaml)

## 关联

- Staging 部署：[`k8s/monitoring/STAGING_RUNBOOK.md`](../../../k8s/monitoring/STAGING_RUNBOOK.md) §2.6
- 阻塞 SSOT：[`specs/BLOCKERS.md`](../../../../specs/BLOCKERS.md) T36–T37
