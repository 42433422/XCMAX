# 本地可观测性栈（T36–T37 本地部分）

> **2026-06 状态**：`local_stack_up.sh --check-only` 可在无 Docker 时校验路径；起栈需 Docker。Staging **7 天流量与正式 SLA 截图**仍阻塞 — 见 [`k8s/monitoring/STAGING_RUNBOOK.md`](../../k8s/monitoring/STAGING_RUNBOOK.md) 与 [`specs/BLOCKERS.md`](../../../specs/BLOCKERS.md) T36–T37。

## 脚本一览

| 脚本 | 用途 |
|------|------|
| [`local_stack_up.sh`](local_stack_up.sh) | 本地 Prometheus + Grafana compose；可选导出 local M0 PNG |
| [`export_m0_panels.sh`](export_m0_panels.sh) | 单独导出四域面板（`--prefix local\|staging`，`TIME_RANGE=now-7d`） |
| [`k6_smoke.sh`](k6_smoke.sh) | 对 `BASE_URL` 跑 `scripts/loadtest/smoke.js`（`--check-only` 仅探活） |
| [`k6/README.md`](k6/README.md) | k6 冒烟说明与环境变量 |
| [`staging_preflight.sh`](staging_preflight.sh) | staging 部署前检查（kubectl / API / Grafana / promtool） |

## 前置

- Docker Desktop / Colima（含 `docker compose`）
- 可选：本地 FastAPI（`make dev`，默认 `http://127.0.0.1:5000`）用于产生 `/metrics` 时序
- k6（staging 压测）：https://grafana.com/docs/k6/latest/set-up/install-k6/

## 一键启动（本地）

```bash
cd FHD
bash scripts/observability/local_stack_up.sh --check-only   # 仅校验，无需 Docker
bash scripts/observability/local_stack_up.sh                # 起 Prometheus + Grafana
```

成功验收：

| 项 | URL / 路径 |
|----|------------|
| Prometheus | http://localhost:9090（`prometheus.local.yml` 抓取 `host.docker.internal:5000`） |
| Grafana | http://localhost:3000（admin / admin123） |
| M0 四域截图 | [`docs/evidence/slo/`](../../docs/evidence/slo/) `grafana-local-m0-*.png` |
| 7 天验收模板 | [`docs/evidence/slo/README.md`](../../docs/evidence/slo/README.md) §2 |

## 手动流量（无 FastAPI 时）

```bash
# k6 smoke（需 BASE_URL）
export BASE_URL=http://127.0.0.1:5000
bash scripts/observability/k6_smoke.sh

# 或 curl 探针
for i in $(seq 1 50); do curl -sf http://127.0.0.1:5000/api/health; done
```

## Staging 补量（集群就绪后）

```bash
export KUBECONFIG=/path/to/staging.kubeconfig
export BASE_URL=https://api.staging.example
export GRAFANA_URL=http://localhost:3000   # kubectl port-forward svc/grafana 3000:3000

bash scripts/observability/staging_preflight.sh --check-only
bash scripts/observability/k6_smoke.sh --check-only
bash scripts/observability/k6_smoke.sh
TIME_RANGE=now-7d bash scripts/observability/export_m0_panels.sh --prefix staging
```

## 停止

```bash
docker compose -f FHD/scripts/observability/docker-compose.local.yml down
```

## M0 面板 UID（与路径图四域对齐）

| 域 | UID | Panel |
|----|-----|-------|
| API | `xcagi-slo` | 1 |
| DB | `xcagi-mod-store` | 5 |
| AI | `xcagi-slo` | 3 |
| NeuroBus | `xcagi-slo` | 7 |

详见 [`docs/evidence/slo/README.md`](../../docs/evidence/slo/README.md)。

## 与 staging 的区别

| 环境 | 证据文件 | 用途 |
|------|----------|------|
| **本地** | `docs/evidence/slo/grafana-local-m0-*.png` | 验证 compose / JSON / 脚本；**非** 7 天 SLA |
| **staging** | `docs/evidence/slo/grafana-staging-m0-*.png` + `acceptance-*.yaml` | SLO 正式基线（T36–T37，禁止伪造） |
