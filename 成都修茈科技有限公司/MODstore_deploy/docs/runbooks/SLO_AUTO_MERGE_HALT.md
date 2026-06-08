# SLO 探针与 auto-merge 阻断（脚手架）

> **状态**：文档 + env 开关；生产 Alertmanager 路由仍须人工配置（见 RELEASE_TRAIN_DEEP_CLOSURE §A8）。

## CI 侧

| 工作流 | 用途 |
|--------|------|
| `FHD/.github/workflows/sla-probe.yml` | 夜间 `/api/health` 延迟预算（`tests/test_sla_health_probe.py`） |
| `FHD/.github/workflows/test.yml` → `performance-gate` | PR 上 k6 smoke（advisory） |

## 生产侧（MODstore）

环境变量（`.env`）：

| 变量 | 说明 |
|------|------|
| `MODSTORE_SLO_HALT_AUTO_MERGE` | `1` 时：最近一次 `post_deploy_smoke` 失败则 `daily_orchestrator` 跳过 auto-merge 路径 |
| `MODSTORE_POST_DEPLOY_SMOKE_ENABLED` | 默认 `1` |
| `MODSTORE_POST_DEPLOY_MARKET_URL` | 默认 `https://xiu-ci.com/market/download` |

实现位置：`modstore_server/post_deploy_smoke.py` · `modstore_server/daily_orchestrator_job.py`（读取最近一次 smoke 结果日志）。

## 推荐接线（后续）

1. Grafana 告警 → webhook → MODstore `incident_bus`。
2. 告警持续 15 分钟 → 设 `MODSTORE_SLO_HALT_AUTO_MERGE=1` 直至人工清除。
3. installer 日前强制跑 `sla-probe` workflow_dispatch 并要求绿。
