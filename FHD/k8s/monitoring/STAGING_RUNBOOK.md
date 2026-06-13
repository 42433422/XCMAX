# Staging 监控栈 Runbook（k6 / Prometheus / Grafana / Loki）

> v10 线内迭代 · SSOT 脚本与 manifest 在 `FHD/k8s/monitoring/` 与 `FHD/scripts/observability/`

## 前置

- 命名空间：`xcagi-staging`
- 远程一键部署：仓根 [`deploy_k8s_staging.sh`](../../../deploy_k8s_staging.sh)（K3s + FHD API + 监控栈）
- Staging 拓扑：**2 副本** `xcagi` + **Gunicorn**（`XCAGI_GUNICORN_WORKERS=2`）— 与生产 [`k8s/deployment.yaml`](../../deployment.yaml) 缩小对齐
- Kustomize overlay（SSOT 方向）：[`k8s/overlays/staging/`](../../overlays/staging/)
- 指标修复 rollout（不重启 k6）：`bash scripts/observability/staging_rollout_metrics.sh`
- Round-1 无效证据：[`docs/evidence/slo/acceptance-round1-invalid-20260612.yaml`](../../docs/evidence/slo/acceptance-round1-invalid-20260612.yaml)
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

### Round-2 启动（Round-1 自然结束后）

```bash
bash FHD/scripts/observability/launch_k6_round2_staging.sh --start
# 48h 门禁：
PROMETHEUS_URL=http://119.27.178.147:30090 bash FHD/scripts/observability/check_round2_metrics_gate.sh
```

### 7 天收尾

```bash
TIME_RANGE=now-7d GRAFANA_URL=http://127.0.0.1:30300 \
  bash FHD/scripts/observability/export_m0_panels.sh --prefix staging --time-range now-7d
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

## 7. GitOps + Rollouts 端到端演练（L3）

前置：`KUBE_CONFIG`、ArgoCD bootstrap、`GITOPS_BUMP_ENABLE=1` 或 `post_merge_promote.sh`。

```bash
# 1) Bootstrap（幂等）
bash FHD/scripts/gitops/bootstrap_argocd.sh
bash FHD/scripts/gitops/bootstrap_rollouts.sh
bash FHD/scripts/observability/bringup_stack.sh

# 2) -rc tag 触发 CI → GitOps bump（或手动）
git tag FHD/v10.0.0-rc1 && git push origin FHD/v10.0.0-rc1
# 或：bash FHD/scripts/gitops/bump_image.sh staging sha-<gitsha> --commit && git push

# 3) 观察 ArgoCD sync + Rollout 金丝雀
kubectl -n argocd get applications
kubectl argo rollouts get rollout xcagi -n xcagi-staging --watch

# 4) SLO 分析门（Prometheus recording rules）
#    xcagi:api_error_ratio:rate5m < 0.05 · xcagi:api_latency_p95:5m < 1.5

# 5) 健康检查
curl -sf https://xiu-ci.com/fhd-api/api/health

# 6) 故意 SLO 违约演练（staging 仅）：注入高错误率后确认 Rollout abort/回滚
kubectl argo rollouts abort xcagi -n xcagi-staging   # 或等待 AnalysisRun 失败
```

DORA 事件：`metrics/deploy_events.jsonl` · 日采集 `fhd-slo-metrics-collect.yml` → `metrics/dora-*.json`。
