# 监控与 Grafana 统一说明

## MODstore

- 应用指标：`modstore_server/metrics.py`，路径 `/metrics`。  
- 本地编排：`docker-compose.yml` 中 `prometheus` + `grafana` profile（`monitoring/prometheus`、`monitoring/grafana`）。

## XCAGI（FHD）

- `FHD/app/fastapi_app.py` 已注册 `/metrics`（`prometheus_client` 可选）。  
- 请在 **Grafana** 中为 FHD 实例增加 Prometheus data source（抓 `/metrics`），与 MODstore 面板并列或合并为一个 Dashboard（按 `job` / `instance` 区分）。

## 建议抓取标签

- `job=modstore-api` / `job=xcagi-api`  
- 统一告警：5xx 率、`llm_calls` 配额 403、支付回调失败、`workflow-hooks` 403（Webhook secret 错误）。
