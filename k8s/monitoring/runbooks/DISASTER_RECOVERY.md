# FHD / K8s 灾备与恢复（索引）

FHD 集群侧不重复 MODstore 单机备份细节；按环境组合下列 Runbook。

## MODstore 单机（SoT 业务数据）

- **主文档**：`成都修茈科技有限公司/MODstore_deploy/docs/runbooks/disaster-recovery.md`
- **备份**：`python scripts/backup_modstore.py`（postgres / redis / modstore_data）
- **恢复**：`scripts/restore_postgres.py` + `scripts/sre_smoke_check.py`

## Redis / PostgreSQL 失效切换要点

| 组件 | 止血 | 恢复 |
|------|------|------|
| PostgreSQL | 停写、切只读或维护页 | `restore_postgres.py --confirm` |
| Redis | 重启 Pod/容器；应用降级缓存未命中 | 恢复 `redis-data.tar.gz` 或允许重建 |
| K8s 工作负载 | `kubectl rollout restart` / Helm 回滚 | 见 `FHD/charts/xcagi/` 与 `deploy.yml` |

## K8s 发布与流量

- Blue-Green：`scripts/k8s/promote-blue-green.sh`、`DEPLOY_BG_AUTO_PROMOTE`
- 健康：`/api/health`、`/health/ready`（DB/Redis/AI 子检查）

## 相关

- [CHAOS_GAME_DAY.md](./CHAOS_GAME_DAY.md)
- [OBSERVABILITY_ALERTS.md](./OBSERVABILITY_ALERTS.md)
- `FHD/docs/SLO.md`
