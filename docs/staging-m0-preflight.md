# Staging M0 最低验收（无 Docker 本机）

> **用途**：本机**无 Docker**（或不用 `local_stack_up.sh`）时，用 **kubectl + 脚本**完成 staging 监控与 **T36–T37** 最低验收链。  
> **阻塞 SSOT**：[`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) **T36–T37**（最早 2026-09；需 7 天真实 scrape 或 k6 补量 + 真实时序）。  
> **完整部署**：[`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md) · 证据目录 [`docs/evidence/slo/README.md`](evidence/slo/README.md)

**禁止**：无流量时导出/提交占位 PNG、在 `acceptance-*.yaml` 填假基线、用本地 compose 曲线冒充 staging 7 天窗口。

---

## 0. 本机前提（无需 Docker）

| 工具 | 用途 |
|------|------|
| `kubectl` + `KUBECONFIG` | 访问 staging 命名空间 `xcagi-staging` |
| `curl` | API / Grafana `/api/health` |
| `bash` | `staging_preflight.sh`、`export_m0_panels.sh` |
| `promtool`（可选） | 校验 `alert_rules.yml` |

**不需要**：Docker、`docker compose`、`local_stack_up.sh` 起栈。

---

## 1. 仓内路径检查（无集群亦可）

```bash
cd FHD

# 文档、模板、告警规则路径；可选 kubectl / BASE_URL / GRAFANA_URL
bash scripts/observability/staging_preflight.sh --check-only
```

通过标准：脚本 exit 0；日志含 `✓ 文档路径 OK`；无集群时 `kubectl` / API 警告可接受，**不得**因此生成 PNG。

---

## 2. kubectl 最低栈检查（需集群）

```bash
export KUBECONFIG=/path/to/staging.kubeconfig
export NS=xcagi-staging

kubectl get ns "${NS}"
kubectl -n "${NS}" get pods -l 'app in (prometheus,grafana)'
kubectl -n "${NS}" wait --for=condition=ready pod -l app=prometheus --timeout=120s
kubectl -n "${NS}" wait --for=condition=ready pod -l app=grafana --timeout=120s
```

未部署时按 [`STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md) §2 执行 `kubectl apply -k`。

可选：Prometheus targets 是否 UP（port-forward 后浏览器或 API）：

```bash
kubectl -n "${NS}" port-forward svc/prometheus 9090:9090 &
# http://localhost:9090/targets — job=xcagi-backend 应为 UP
```

---

## 3. Grafana 可达 + 导出预检（仍不生成 PNG）

```bash
kubectl -n "${NS}" port-forward svc/grafana 3000:3000 &
export GRAFANA_URL=http://127.0.0.1:3000
export GRAFANA_USER=admin
export GRAFANA_PASS='***'   # 见 grafana-secret，勿提交仓库

# 仅探活，不写入 docs/evidence/slo/*.png
bash scripts/observability/export_m0_panels.sh --prefix staging --check-only
```

浏览器确认 **Dashboards → XCAGI** 存在 `xcagi-slo`、`xcagi-mod-store` 等（见 STAGING_RUNBOOK §2.3）。

---

## 4. T36–T37 正式验收链（有真实流量后）

**前置**：连续 **≥ 7 天** staging scrape **或** k6 补量且面板有**真实**时序（k6 alone 不能替代 7 天窗口，须在 `acceptance-*.yaml` 说明 `observation_mode`）。

```bash
# port-forward 保持；时间范围与 Grafana「Last 7 days」一致
export GRAFANA_URL=http://127.0.0.1:3000
export GRAFANA_USER=admin
export GRAFANA_PASS='***'

TIME_RANGE=now-7d bash scripts/observability/export_m0_panels.sh --prefix staging
```

产出（示例命名，以脚本 `DATE_SUFFIX` 为准）：

- `docs/evidence/slo/grafana-staging-m0-api-availability-*.png`
- `docs/evidence/slo/grafana-staging-m0-db-mod-sqlite-copies-*.png`
- `docs/evidence/slo/grafana-staging-m0-ai-chat-p95-*.png`
- `docs/evidence/slo/grafana-staging-m0-neurobus-delivery-*.png`

若 render API 失败：Grafana UI → 面板 → **Share → Export PNG**（同名入库），**禁止**手工 P 图或复制本地 `grafana-local-m0-*`。

填验收 YAML（**仅从面板读数**）：

```bash
cp docs/evidence/slo/acceptance-TEMPLATE.yaml docs/evidence/slo/acceptance-YYYYMMDD.yaml
# meta.blocker_ref 保持 specs/BLOCKERS.md#T36-T37
```

可选 k6 补量（仍需真实时序）：

```bash
export BASE_URL=https://api.staging.example
bash scripts/observability/k6_smoke.sh --check-only
bash scripts/observability/k6_smoke.sh
```

解阻塞后：更新 [`CLAIMED_VS_ACTUAL.md`](CLAIMED_VS_ACTUAL.md) SLO 行，并在 BLOCKERS 中核销 T36–T37。

---

## 5. 最低验收清单（勾选）

| # | 步骤 | 命令 / 产物 | T36–T37 |
|---|------|-------------|---------|
| 1 | 仓内预检 | `staging_preflight.sh --check-only` | 准备 |
| 2 | 集群 Pod Ready | `kubectl -n xcagi-staging get/wait pods` | 准备 |
| 3 | Scrape / targets UP | Prometheus `/targets` | 准备 |
| 4 | Grafana 预检 | `export_m0_panels.sh --prefix staging --check-only` | 准备 |
| 5 | 7 天或合规补量 | 自然流量 / k6 + 说明 | **阻塞项** |
| 6 | 四域 PNG 入库 | `--prefix staging` + `TIME_RANGE=now-7d` | **阻塞项** |
| 7 | 验收 YAML | `acceptance-YYYYMMDD.yaml` 自模板 | **阻塞项** |

步骤 1–4 可在无 Docker 本机完成；**5–7** 未满足前 [`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) T36–T37 保持阻塞。

---

## 6. 关联

| 文档 / 脚本 | 说明 |
|-------------|------|
| [`k8s/monitoring/STAGING_RUNBOOK.md`](../k8s/monitoring/STAGING_RUNBOOK.md) | 部署、回滚、故障排查 |
| [`scripts/observability/staging_preflight.sh`](../scripts/observability/staging_preflight.sh) | 前置检查 |
| [`scripts/observability/export_m0_panels.sh`](../scripts/observability/export_m0_panels.sh) | 四域 PNG 导出 |
| [`docs/evidence/slo/README.md`](evidence/slo/README.md) | 命名与 YAML 字段 |
| [`docs/M0-remaining-gaps.md`](M0-remaining-gaps.md) | M0 缺口 #1、#3 |
| [`specs/BLOCKERS.md`](../../specs/BLOCKERS.md) | **T36–T37** SSOT |
