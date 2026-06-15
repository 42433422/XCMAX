# FHD GitOps (ArgoCD App-of-Apps)

声明式部署控制面。**唯一入口** = `app-of-apps.yaml`：bootstrap 一次后，ArgoCD 自动管理
`apps/` 下的子 Application，按仓库声明状态持续 sync。

```
app-of-apps.yaml          # root Application → 监听 FHD/gitops/apps/
apps/
  fhd-api-staging.yaml     # → FHD/k8s/overlays/staging  (ns: xcagi-staging, auto-sync)
  fhd-api-production.yaml  # → FHD/k8s/overlays/production(ns: xcagi-prod,   auto-sync)
  monitoring.yaml          # → FHD/k8s/monitoring         (ns: monitoring)
  rollouts.yaml            # → argo-rollouts Helm chart   (ns: argo-rollouts, Phase 3)
```

## Bootstrap（需 `KUBE_CONFIG` 指向目标集群）

```bash
bash FHD/scripts/gitops/bootstrap_argocd.sh
```

脚本会：安装 ArgoCD → 在 `argocd-cm` 打开 `kustomize.buildOptions: --load-restrictor
LoadRestrictionsNone`（overlay 引用父级 base 目录需要）→ 应用 App-of-Apps。

## 镜像更新（声明式）

CI 推送 `xcagi-fhd-api:sha-<gitsha>` 后，更新对应 overlay 的镜像 tag 并提交，ArgoCD 即 sync：

```bash
# staging（main / -rc）；production（正式 tag）。--commit 让脚本直接提交。
bash FHD/scripts/gitops/bump_image.sh staging sha-<gitsha> --commit
```

> 由 Phase 6 日更编排（`run_modstore_daily_local.sh`）或人工调用；亦可改用 ArgoCD Image Updater。
> 制品身份恒用 `git_sha` + `sha256` + cosign digest，**不 bump 产品版本**（v10 锁 `10.0.0`）。

## 安全

- 部署镜像在 CI 经 cosign keyless 签名；集群侧信任校验见 Phase 1（`fhd-deploy.yml`）与
  Phase 3 Rollouts 分析门。
- 生产 K8s 轨与 CVM tarball/compose 轨**并存**，互不替代。
