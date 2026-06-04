# 本地可观测性栈（T36–T37 本地部分）

> **2026-06 状态**：`local_stack_up.sh --check-only` 可在无 Docker 时校验路径；起栈需 Docker。Staging **7 天流量与正式 SLA 截图**仍阻塞 — 见 [`docs/staging-runbook.md`](../../docs/staging-runbook.md) 与 [`specs/BLOCKERS.md`](../../../specs/BLOCKERS.md) T36–T37。

## 前置

- Docker Desktop / Colima（含 `docker compose`）
- 可选：本地 FastAPI（`make dev`，默认 `http://127.0.0.1:5000`）用于产生 `/metrics` 时序

## 一键启动

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
| M0 四域截图 | [`docs/evidence/slo/`](../docs/evidence/slo/) `grafana-local-m0-*.png` |
| 兼容截图 | [`docs/observability/grafana-local-202606.png`](../docs/observability/grafana-local-202606.png) |

## 手动流量（无 FastAPI 时）

```bash
# k6（若已安装）
cd FHD/scripts/loadtest
BASE_URL=http://127.0.0.1:5000 k6 run smoke.js

# 或 curl 探针
for i in $(seq 1 50); do curl -sf http://127.0.0.1:5000/api/health; done
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

详见 [`docs/evidence/README.md`](../../docs/evidence/README.md)。

## 与 staging 的区别

| 环境 | 证据文件 | 用途 |
|------|----------|------|
| **本地** | `docs/evidence/slo/grafana-local-m0-*.png` | 验证 compose / JSON / 脚本；**非** 7 天 SLA |
| **staging** | `docs/evidence/slo/grafana-staging-*.png` | SLO 正式基线（T36–T37，禁止伪造） |
