# FHD 发版检查清单（v10 线）

Tag：`FHD/v10.0.0` 或 `FHD/v10.0.0-rc.1`（预发）。

## GitHub Secrets（必填）

| Secret | 用途 |
|--------|------|
| `FHD_PUSH_HOST` | CVM update 服务器 |
| `FHD_PUSH_SSH_KEY` | CVM + 桌面 rsync（统一） |
| `SERVER_SSH_KEY` | 桌面 Windows 部署（可选，缺则跳过 deploy job） |

> K8s/`KUBE_CONFIG` 已退役（2026-07-01 运维根治）：从未有真实集群，
> 生产 = 单 CVM 拉取式发布链。

## 发版前本地

```bash
cd FHD
python scripts/dev/verify_version_anchors.py
python scripts/dev/count_type_debt.py
python scripts/dev/count_raw_sql.py
pytest tests/ -q --tb=line
cd frontend && npm run lint && npm run type-check
```

## Tag 后自动链路

1. `fhd-ci-cd.yml` — 测试、镜像 push GHCR、**cvm-push-release**（tarball+sha256
   manifest → 服务器 `fhd-auto-update.sh` 校验/备份/健康门/失败自动回滚）
2. `fhd-release-orchestrator.yml` — 锚点校验、GitHub Release、触发桌面/Web/Android

验证上线：服务器 `cat /opt/fhd-full/.deploy-sha256` 对比 manifest `sha256`，
或 `tail /var/log/fhd-auto-update.log`。运维全貌见仓库根 [ops/README.md](../../../ops/README.md)。

## CVM 首次 / bootstrap

- `/root/fhd-full.env`、服务器上 `cd /root/XCMAX && bash ops/install.sh`
  （装哨兵/夜备/漂移检测 + fhd-auto-update cron）
- GHCR `read:packages` PAT、`docker login ghcr.io`（仅 `deploy_mode=image` 需要）
- manifest `deploy_mode` 与 compose 切换见 [docs/CI_SSOT.md](../../../docs/CI_SSOT.md)
