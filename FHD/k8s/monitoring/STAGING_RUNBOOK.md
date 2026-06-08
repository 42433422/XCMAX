# Staging 监控栈 Runbook（k6 / Prometheus / Grafana / Loki）

> v10 线内迭代 · SSOT 脚本与 manifest 在 `FHD/k8s/monitoring/` 与 `FHD/scripts/observability/`

## 前置

- 命名空间：`xcagi-staging`
- 远程一键部署：仓根 [`deploy_k8s_staging.sh`](../../../deploy_k8s_staging.sh)（K3s + FHD API + 监控栈）
- 阻塞项：[`specs/BLOCKERS.md`](../../../specs/BLOCKERS.md) T36–T37（7 天窗口截图）

## 1. k6 7 天合同流量

### SSOT

| 资源 | 路径 |
|------|------|
| 脚本 | `FHD/scripts/observability/k6_7d_contract.js` |
| Job | `FHD/k8s/monitoring/k6-7day-job.yaml` |
| ConfigMap | `FHD/k8s/monitoring/k6-configmap.yaml`（由 sync 生成） |

### 同步 ConfigMap（部署前必跑）

```bash
cd FHD
bash scripts/observability/sync_k6_configmap.sh
# 或直连集群：
bash scripts/observability/sync_k6_configmap.sh --apply --namespace xcagi-staging
```

### 应用 Job（勿在 7 天窗口中途重启）

```bash
kubectl apply -f k8s/monitoring/k6-configmap.yaml
kubectl apply -f k8s/monitoring/k6-7day-job.yaml
```

**警告**：若 T36 验收窗口已在进行，更新 ConfigMap 后 **不要** 删除/重建 `k6-7day` Job，否则 168h 计数清零。仅在新窗口启动前同步并 apply。

### 验收

```bash
kubectl -n xcagi-staging get configmap k6-7day-contract -o jsonpath='{.data.k6_7d_contract\.js}' | head -5
# 应看到 import http from 'k6/http' 与 contract_7d scenario，而非 placeholder
kubectl -n xcagi-staging logs job/k6-7day -f
```

### 7 天收尾

```bash
bash FHD/scripts/observability/run_staging_7d_acceptance.sh --prefix staging
# 或仓根 collect_7day_k8s.sh（停 k6 + 读 Prometheus + Grafana PNG）
```

## 2. Prometheus

- Manifest：`k8s/monitoring/prometheus/`（Deployment + PVC）
- Retention：`--storage.tsdb.retention.time=8d`（与 staging 对齐）
- NodePort（staging）：`http://127.0.0.1:30090`

```bash
kubectl -n monitoring get pvc prometheus-data
kubectl -n monitoring rollout restart deployment/prometheus  # 验证 PVC 后数据保留
```

## 3. Grafana

- Manifest：`k8s/monitoring/grafana/`
- NodePort：`http://127.0.0.1:30300`（admin / admin123）
- 导入：`k8s/monitoring/grafana/dashboards/xcagi-revenue.json`

## 4. Loki + Promtail

- Manifest：`k8s/monitoring/loki/`（Loki Deployment + PVC + Promtail DaemonSet）
- 配置：`loki/loki.yml`、`loki/promtail.yml`
- Grafana 数据源：添加 Loki `http://loki:3100`

## 5. 镜像 pin 与存储

| 组件 | 镜像 |
|------|------|
| k6 | `grafana/k6:0.54.0` |
| Prometheus | `prom/prometheus:v2.53.0` |
| Loki | `grafana/loki:3.0.0` |
| Grafana | 见 grafana-deployment.yml |

PVC 默认 `storageClassName: local-path`（k3s）；Prometheus 15Gi、Loki 10Gi。

## 6. 故障排查

| 现象 | 检查 |
|------|------|
| k6 仅打 health | ConfigMap 未 sync；跑 `sync_k6_configmap.sh --apply` |
| Prometheus 重启丢数据 | Deployment 仍用 emptyDir；确认 PVC 已挂载 |
| Grafana 无日志 | Loki/Promtail 未部署或数据源未配 |
| 7d 截图缺失 | 见 BLOCKERS T36–T37；确认 Job 跑满 168h |
