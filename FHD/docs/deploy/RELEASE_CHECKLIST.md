# FHD 发版检查清单（v10 线）

Tag：`FHD/v10.0.0` 或 `FHD/v10.0.0-rc.1`（预发）。

## GitHub Secrets（必填）

| Secret | 用途 |
|--------|------|
| `FHD_PUSH_HOST` | CVM update 服务器 |
| `FHD_PUSH_SSH_KEY` | CVM + 桌面 rsync（统一） |
| `KUBE_CONFIG_B64` 或 `KUBE_CONFIG` | 生产 K8s deploy（**缺则 production fail**） |
| `SERVER_SSH_KEY` | 桌面 Windows 部署（可选，缺则跳过 deploy job） |

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

1. `fhd-ci-cd.yml` — 测试、镜像 push GHCR、CVM push（secrets 就绪时）
2. `fhd-release-orchestrator.yml` — 锚点校验、GitHub Release、触发 K8s + 桌面/Web/Android
3. `fhd-deploy.yml` — K8s apply（production 无 kubeconfig 则 **失败**）

## CVM 首次 / bootstrap

- `/root/fhd-full.env`、`fhd-install-server-cron.sh`
- GHCR `read:packages` PAT、`docker login ghcr.io`
- manifest `deploy_mode` 与 compose 切换见 [docs/CI_SSOT.md](../../../docs/CI_SSOT.md)

## K8s

- 自 [k8s/secret.yaml.example](../../k8s/secret.yaml.example) 创建 `xcagi-secrets`
