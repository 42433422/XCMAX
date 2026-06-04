# FHD / K8s 混沌演练（索引）

## MODstore Compose 演练（标准场景）

- **Runbook**：`成都修茈科技有限公司/MODstore_deploy/docs/runbooks/chaos-game-day.md`
- **执行器**：`MODstore_deploy/chaos/chaos_drill.py`
- **场景**：`redis-stop`、`rabbitmq-stop`、`postgres-stop`、`payment-restart`、`api-restart`
- **记录**：`…/docs/runbooks/exercises/`

演练前：`python scripts/sre_smoke_check.py` 建立基线。

## K8s 集群演练

- **Workflow**：`FHD/.github/workflows/k8s-staging-e2e.yml`
  - `workflow_dispatch` → `chaos_enabled=true`
  - 随机 kill Pod，验证 PDB + HPA + 探针自愈
- **Feature flag**：`FHD_FF_EXPERIMENTAL__K8S_CHAOS`（`.env.example`）

## Redis 失效切换验证清单

1. 触发 `redis-stop`（dry-run → `--confirm`）或 K8s 删除 Redis Pod
2. 确认告警：`RedisDown` / 基础设施仪表盘
3. 恢复后 10 分钟内 5xx / 延迟回基线
4. 登记复盘到 `exercises/YYYY-MM-DD/EXERCISE.md`

## 阶段 6 门禁

见 [DUAL_LINE_SRE_GATE.md](../../../docs/guides/DUAL_LINE_SRE_GATE.md) · `scripts/verify_dual_line_sre_gate.py`
