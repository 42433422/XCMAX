# CI SSOT（XCMAX 根仓）

**GitHub Actions 唯一调度入口**：[`.github/workflows/`](../.github/workflows/)

子目录 `FHD/.github/workflows/`、`MODstore_deploy/.github/workflows/` 仅保留 **README 指针**与 Issue/PR 模板，**不会**被 GitHub 执行。

## 分层

| 层级 | 路径 | 说明 |
|------|------|------|
| **仓根 SSOT** | `.github/workflows/*.yml` | push/PR/schedule 在此触发 |
| **FHD 实现源** | `FHD/.github/workflows/*.yml` | 编辑后运行 `python scripts/dev/publish_ci_workflows_to_root.py` 同步到根 |
| **MODstore 实现源** | `成都修茈科技有限公司/MODstore_deploy/.github/workflows/*.yml` | 同上 |

> **生成 vs 手写**：根仓 `fhd-*.yml` / `modstore-*.yml` 由 publish 脚本从实现源生成，文件头为
> `# CI SSOT: generated from … — DO NOT edit here`。**请改实现源后重跑 publish**，勿直接改根副本。
> 以下 **7 个根仓 workflow 为手写**（无生成头，直接在根仓维护）：
> `android-build.yml`、`archive-hygiene.yml`、`corp-site-deploy.yml`、`desktop-macos-smoke.yml`、
> `e2e.yml`、`e2e-playwright-reusable.yml`、`frontend-unit.yml`。

## 常用 workflow

| 用途 | 根 workflow |
|------|-------------|
| FHD 后端 + 前端 + Docker | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) |
| FHD 轻量 smoke（path 过滤） | [`fhd-test.yml`](../.github/workflows/fhd-test.yml) |
| FHD Release gate | [`fhd-release-gate-ci.yml`](../.github/workflows/fhd-release-gate-ci.yml) |
| 前端 Vitest | [`frontend-unit.yml`](../.github/workflows/frontend-unit.yml) |
| Playwright P0 | [`e2e.yml`](../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../.github/workflows/e2e-playwright-reusable.yml) |
| Android assembleDebug | [`android-build.yml`](../.github/workflows/android-build.yml) |
| MODstore Python CI | [`modstore-ci-backend-python.yml`](../.github/workflows/modstore-ci-backend-python.yml) |
| Archive 卫生 | [`archive-hygiene.yml`](../.github/workflows/archive-hygiene.yml) |
| FHD 服务器 API 发布包校验 | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) → job `pack-verify` |
| FHD 全产品线 tag 编排 | [`fhd-release-orchestrator.yml`](../.github/workflows/fhd-release-orchestrator.yml) |
| FHD K8s 部署 | [`fhd-deploy.yml`](../.github/workflows/fhd-deploy.yml) |

## 发布 tag 约定（v10 线内）

- **产品版本锚点**：恒 `10.0.0`（见 `FHD/VERSION.md`），**不因功能发版 bump 主版本**。
- **Git tag（发版触发）**：`FHD/v10.0.0` 或 `FHD/v10.*`；**制品身份**用 tarball 内 `git_sha` + `sha256`，非 tag 名。
- **串联（单一编排入口）**：`FHD/v*` tag 仅触发两个 workflow —— `fhd-ci-cd.yml`（测试+镜像+CVM）与 `fhd-release-orchestrator.yml`。后者先跑 `verify-version-anchors`，再 **dispatch** `fhd-deploy.yml`（K8s，`-rc`→staging / 否则 production）与客户端 `fhd-release-desktop/web/android.yml`。这些被编排的 workflow **已移除自身 `FHD/v*` tag 触发**，避免 tag 推送时双重运行。详见 [FHD/docs/deploy/RELEASE_CHECKLIST.md](FHD/docs/deploy/RELEASE_CHECKLIST.md)。

## 多环境 channel（stable / staging）

| Channel | 远端 manifest 目录 | 用途 |
|---------|-------------------|------|
| `stable`（默认） | `/var/www/update/releases/stable/server/` | 生产 compose（5100） |
| `staging` | `/var/www/update/releases/staging/server/` | 预发 / dry-run（建议 5101 + 独立 `FHD_DEPLOY_ROOT`） |

**打包 / 推送**（`FHD/` 根目录）：

```bash
# 生产
bash scripts/deploy/fhd-pack-release.sh
bash scripts/deploy/fhd-push-release.sh

# 预发 channel
FHD_RELEASE_CHANNEL=staging bash scripts/deploy/fhd-pack-release.sh
FHD_RELEASE_CHANNEL=staging bash scripts/deploy/fhd-push-release.sh
```

manifest 含 `"channel": "stable"|"staging"`。同一台 CVM（119.27.178.147）可并存两目录；staging cron 示例：

```bash
FHD_MANIFEST_PATH=/var/www/update/releases/staging/server/fhd-manifest.json \
FHD_DEPLOY_ROOT=/opt/fhd-staging \
FHD_API_PORT=5101 \
bash /opt/fhd-staging/scripts/deploy/fhd-auto-update.sh
```

## CVM 自动 CD（GitHub Actions）

`fhd-ci-cd.yml` job **`cvm-push-release`**：`main` push 且 `docker-build-fhd-api` 成功后，若配置了 secrets 则自动 scp 制品；**无 secrets 时跳过（不失败）**。

| Secret / 变量 | 说明 |
|---------------|------|
| `FHD_PUSH_HOST` | 默认 `119.27.178.147` |
| `FHD_PUSH_SSH_KEY` | SSH 私钥（**勿入库**） |
| `FHD_PUSH_USER` | 可选，默认 `root` |
| GitHub Environment `production` / `staging` | 可选审批门；`workflow_dispatch` 可选 channel |

手动触发：`Actions → CI/CD Pipeline → Run workflow` → 勾选 **Push release artifacts to CVM**，选 channel。

**仍需人工（仓外）**：GHCR `read:packages` PAT 写入服务器、`/root/fhd-full.env`、首次 cron 安装、branch protection。

## K8s 部署（Phase 3 · 并行轨，不替代 CVM prod）

| 触发 | Workflow | 前提 |
|------|----------|------|
| `FHD/v*` tag（非 `-rc` → prod；`-rc` → staging） | `fhd-deploy.yml` | Secret `KUBE_CONFIG` 或 `KUBE_CONFIG_B64` |
| `workflow_dispatch` | 同上，选 environment + strategy | 同上 |
| 可选 `image_digest` input | 钉扎 `xcagi-fhd-api@sha256:...` | CI 已推 GHCR |

镜像 SSOT：`ghcr.io/<org>/<repo>/xcagi-fhd-api:sha-<git_sha>`（与 `docker-build-fhd-api` 一致）。Manifest 在 `FHD/k8s/`；staging 默认 namespace `xcagi-staging`。

本地 / 119.27.178.147 K3s 一键：`deploy_k8s_staging.sh`（见 `FHD/k8s/monitoring/STAGING_RUNBOOK.md`）。

## GitOps（Phase 2 · ArgoCD App-of-Apps）

声明式部署控制面，逐步取代 `fhd-deploy.yml` 的命令式 `kubectl apply`（后者保留为 break-glass）。

**目录** `FHD/gitops/`：

| 文件 | 角色 | 指向 |
|------|------|------|
| `app-of-apps.yaml` | root Application（bootstrap 一次） | 监听 `FHD/gitops/apps/` |
| `apps/fhd-api-staging.yaml` | staging 自动 sync | `FHD/k8s/overlays/staging`（ns `xcagi-staging`） |
| `apps/fhd-api-production.yaml` | production 自动 sync（K8s 轨，与 CVM prod 并行） | `FHD/k8s/overlays/production`（ns `xcagi-prod`） |
| `apps/monitoring.yaml` | 可观测 CRD | `FHD/k8s/monitoring` |
| `apps/rollouts.yaml` | Argo Rollouts 控制器（Helm，Phase 3 用） | `argo-rollouts` chart |

**Kustomize 布局**：`FHD/k8s/base/`（聚合 `../*.yaml` 7 份清单，唯一 base）→ overlays `resources: ../../base` + `images:` 钉扎镜像 tag。overlay 引用父级 base 需 `--load-restrictor LoadRestrictionsNone`（`bootstrap_argocd.sh` 已在 `argocd-cm` 设 `kustomize.buildOptions`；本地手动加该 flag）。

**集群 bootstrap**：`bash FHD/scripts/gitops/bootstrap_argocd.sh`（用现有 `KUBE_CONFIG`，幂等：装 ArgoCD → patch argocd-cm → apply App-of-Apps）。

**镜像更新声明式化**：
- `fhd-ci-cd.yml` job `gitops-image-bump`（**opt-in**：仓库变量 `GITOPS_BUMP_ENABLE=1`）：main push 构建成功后，把 staging overlay 的 `newTag` 写为 `sha-<gitsha>`、`[skip ci]` 提交回 main（`GITHUB_TOKEN` 推送不触发递归 CI），ArgoCD 自动 sync。
- main 受保护无法直推时：保持开关关闭，改用 **ArgoCD Image Updater** 或经 orchestrator 晋级。
- 生产晋级：`bash FHD/scripts/gitops/bump_image.sh production <sha-tag> --commit`（人工 / orchestrator）。
- 制品身份恒 `git_sha` + `sha256` + cosign digest，**不 bump 版本**（v10 锁 `10.0.0`）。

## 渐进式交付（Phase 3 · Argo Rollouts + SLO 分析门）

GitOps overlays（`staging` / `production`）引用 `FHD/k8s/rollouts/`（`Deployment` → `Rollout`），由 Argo Rollouts 控制器执行金丝雀 + Prometheus 自动分析 + 失败自动 abort/回滚。

| 组件 | 路径 | 说明 |
|------|------|------|
| Rollout | `FHD/k8s/rollouts/rollout.yaml` | 金丝雀 20% → 50% → 100%，每步 `xcagi-slo-gate` 分析 |
| AnalysisTemplate | `FHD/k8s/rollouts/analysis-template.yaml` | 查 `prometheus.monitoring:9090` 的 `xcagi:api_error_ratio:rate5m`（<5%）与 `xcagi:api_latency_p95:5m`（<1.5s） |
| 控制器 | `FHD/gitops/apps/rollouts.yaml`（sync-wave -2） | Helm `argo-rollouts`；或 `bash FHD/scripts/gitops/bootstrap_rollouts.sh` |
| 旧清单 | `FHD/k8s/archive/` | `canary.yaml` / `blue-green-deployment.yaml` 已归档 |

**staging 环境覆盖**：`replicas-patch.yaml` 改 Rollout 副本；`config-patch.yaml` 改 `xcagi-config` ConfigMap（`FHD_ENV=staging` 等）——避免对 CRD 容器列表做 strategic-merge（会丢 image/probes）。

**break-glass**：`fhd-deploy.yml` 的 `strategy=canary|blue-green` 仅打 warning，始终 rolling `Deployment`；渐进式交付走 GitOps。

**运维 CLI**（可选插件）：
```bash
kubectl argo rollouts get rollout xcagi -n xcagi-staging --watch
kubectl argo rollouts promote xcagi -n xcagi-staging   # 手动晋级
kubectl argo rollouts abort   xcagi -n xcagi-staging   # 手动 abort
```

## 可观测性（Phase 4 · 一键全栈 + DORA）

| 路径 | 用途 |
|------|------|
| `FHD/k8s/monitoring/overlays/full/` | GitOps 全栈（Prometheus/Grafana/Loki/Alertmanager + 看板） |
| `bash FHD/scripts/observability/bringup_stack.sh` | 非 GitOps 一键 `kubectl apply -k` |
| `bash FHD/scripts/observability/local_stack_up.sh` | 本地 Docker Prometheus `:9091` + Grafana `:3000` |
| `FHD/scripts/observability/emit_deploy_event.py` | 部署事件 → `metrics/deploy_events.jsonl` |
| `FHD/scripts/observability/collect_dora.py` | DORA 四指标 → `metrics/dora-YYYYMMDD.json` |
| `fhd-slo-metrics-collect.yml` | 每日 08:00 UTC 采集 SLO + DORA 并 commit |

Grafana 预置看板：`xcagi-slo` · `xcagi-rollouts` · `xcagi-dora`（`overlays/full` ConfigMap 挂载）。

## 每 PR 预览环境（Phase 5）

| 触发 | Workflow | 行为 |
|------|----------|------|
| PR opened/synchronize | `fhd-preview-env.yml` | 构建 `pr-<num>` 镜像 → `xcagi-pr-<num>` namespace |
| PR closed | 同上 `teardown` job | `kubectl delete namespace xcagi-pr-<num>` |

Overlay：`FHD/k8s/overlays/preview/`（1 副本、资源收紧）。需 `KUBE_CONFIG`；无则跳过并在 PR 评论说明。

## 日更编排闭环（Phase 6）

| 组件 | 说明 |
|------|------|
| `run_modstore_daily_local.sh` | export `MODSTORE_POST_MERGE_GITOPS_SCRIPT` → `post_merge_promote.sh` |
| `FHD/scripts/gitops/post_merge_promote.sh` | 等 `fhd-ci-cd` 绿 → `bump_image.sh staging`；**SLO 熔断**（`MODSTORE_SLO_HALT_AUTO_MERGE`）时 exit 1 |
| `FHD/config/release_train.json` | MODstore **日更节奏** SSOT（`+0.0.0.1` epoch）；**≠** 产品 v10 锚点 `10.0.0` |
| `GITOPS_BUMP_ENABLE=1` | CI 自动回写 staging tag（与 post_merge **双轨**，二选一或并存） |

闭环：auto-PR → merge main → CI 签名 → GitOps bump → ArgoCD sync → Rollouts 金丝雀 → SLO 分析 → DORA 事件 → 次日 digest。

## Secrets / Variables 清单

**Settings → Secrets and variables → Actions**（Secrets 与 Variables 两页）。标「跳过」者缺失时对应步骤跳过（不致 CI 失败）。

| 名称 | 类型 | 用途 | 缺失行为 |
|------|------|------|---------|
| `GITHUB_TOKEN` | 自动 | GHCR 推送、`gh workflow run` dispatch、GitHub Release | 自动注入 |
| `FHD_PUSH_HOST` | Secret / Var | CVM 推送目标（默认 `119.27.178.147`） | CVM/桌面推送跳过 |
| `FHD_PUSH_SSH_KEY` | Secret | CVM SSH 私钥（**勿入库**） | CVM 推送跳过 |
| `FHD_PUSH_USER` | Secret | CVM SSH 用户（默认 `root`） | 用默认 |
| `SERVER_SSH_KEY` | Secret | 桌面安装包上传 SSH 私钥（缺失则回退 `FHD_PUSH_SSH_KEY`） | 桌面上传跳过 |
| `KUBE_CONFIG` / `KUBE_CONFIG_B64` | Secret | K8s 部署 kubeconfig | staging 跳过 apply；**production 硬失败** |
| `K8S_NAMESPACE` | Var | 部署 namespace（默认 staging=`xcagi-staging`、prod=`default`） | 用默认 |
| `CODECOV_TOKEN` | Secret | 覆盖率上传 | 步骤 `continue-on-error` |
| `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID` | Secret | macOS 公证 / 签名 | 出未公证包 |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | Secret | 桌面代码签名证书（electron-builder） | 出未签名包 |
| `STAGING_BASE_URL` | Var | 容量 k6 目标（`fhd-capacity-staging-monthly`） | 容量测试跳过 |
| `STAGING_PROMETHEUS_URL` | Var / Secret | SLO 采集 Prometheus 端点 | SLO 采集降级 |
| `XCMAX_GIT_BRANCH` / `XCMAX_REMOTE_ROOT` | Var | 企业站 `corp-site-deploy` 同步参数 | 用默认 |
| `GITOPS_BUMP_ENABLE` | Var | 置 `1` 启用 `gitops-image-bump` 回写 staging overlay tag 到 main | 不设=关闭（不回写） |
| `COSIGN_VERIFY_DISABLE` | Var | 置 `1` 临时跳过部署前 `cosign verify`（break-glass） | 不设=强制验证 |

> Phase 1（供应链）起 cosign **keyless**（Sigstore + GitHub OIDC）签名**免私钥**，不新增长期密钥；集群凭证统一走 `KUBE_CONFIG`。

## Branch protection（须仓库 Owner 在 GitHub UI 配置）

Agent **无法**从本环境开启 branch protection。建议在 **Settings → Branches → main** 启用：

- Required status checks：`backend-test`、`frontend-test`、`frontend-e2e`、`arch-fitness`、`security-scan`、`pack-verify`、`container-scan`、`docker-build-fhd-api`（及 `Release gate CI` 若启用）
- Phase 1+：`cosign verify` 在 `fhd-deploy` 部署门禁（集群侧；非独立 check 名）
- Phase 3+：Rollouts `AnalysisRun` 失败 = 集群内自动 abort（非 branch protection check）
- Phase 5+（可选）：启用 PR 预览时加 `preview` job（`fhd-preview-env.yml`）
- Phase 6+：`MODSTORE_SLO_HALT_AUTO_MERGE=1` 时 SLO 红则日更脚本不 promote
- Require branches up to date before merging
- 可选：Environment `production` 需审批后再跑 `cvm-push-release`

## FHD 生产服务器部署 runbook（tarball 拉取式）

**原则**：生产机 `/opt/fhd-full` **只跑制品、不 git pull、不手改代码**；配置在 `/root/fhd-full.env`（不入库）。

| 步骤 | 命令（在 `FHD/` 根目录） |
|------|--------------------------|
| 1. 锚点校验 | `python3 scripts/dev/verify_version_anchors.py` |
| 2. 打包 | `bash scripts/deploy/fhd-pack-release.sh` |
| 3. 推送到 update 站 | `bash scripts/deploy/fhd-push-release.sh`（需 SSH key 到 `119.27.178.147`） |
| 4. 服务器 cron 应用 | 每 5 分钟 `fhd-auto-update.sh` 读 manifest → `fhd-apply-release.sh` |
| 5. 首次/切换 cron | 服务器：`bash /opt/fhd-full/scripts/deploy/fhd-install-server-cron.sh` |

**健康检查**：`curl -sf http://127.0.0.1:5100/api/health`（服务器）或经 Nginx `https://xiu-ci.com/fhd-api/api/health`。

**若新制品启动失败**：临时冻结 manifest 防止 cron 反复重试：  
`mv /var/www/update/releases/stable/server/fhd-manifest.json{,.hold}`

**回滚**：`fhd-apply-release.sh` 健康检查失败会自动从备份目录回滚；也可手动：

```bash
FHD_RELEASE_TARBALL=/opt/fhd-full/.deploy-last.tar.gz bash /opt/fhd-full/scripts/deploy/fhd-apply-release.sh
```

**产物路径**：`/var/www/update/releases/stable/server/fhd-manifest.json` + `fhd-full-*.tar.gz`。

**manifest v1 字段**：`artifact`、`sha256`、`git_sha`、`deploy_mode: "tarball"`。

## FHD 生产服务器部署 runbook（compose 镜像 · Phase 2）

**原则**：与 tarball **双模共存**；manifest `deploy_mode` 决定 cron 路由（默认 `tarball`，切换前勿改）。镜像身份用 **digest 钉扎**，不用产品版本号 bump（v10 锁 `10.0.0`）。

| 步骤 | 命令 / 说明 |
|------|-------------|
| 1. CI 构建镜像 | `fhd-ci-cd.yml` job `docker-build-fhd-api`：`docker/Dockerfile.fhd-api` → `ghcr.io/<org>/<repo>/xcagi-fhd-api:sha-<git_sha>` |
| 2. manifest v2 | 同次流水线合并 `image` + `image_digest`（`fhd-merge-manifest-image.sh`）；仍含 tarball 字段 |
| 3. 本机推送 | `bash scripts/deploy/fhd-push-release.sh`（manifest + tarball 原子 scp 到 update 站） |
| 4. 服务器 GHCR 登录 | **一次性**：`echo $GITHUB_PAT | docker login ghcr.io -u <github_user> --password-stdin`（PAT 需 **`read:packages`**；`gh auth token` 默认不含此 scope，pull 会 `denied`） |
| 4b. 无 PAT 时引导 | CI artifact / update 站 `fhd-api-image.tar.gz` → `bash scripts/deploy/fhd-load-release-image.sh`（`fhd-apply-release-compose.sh` 在 pull 失败时会自动尝试） |
| 5. compose 文件 | 首次 tarball 应用后位于 `/opt/fhd-full/docker/docker-compose.fhd-prod.yml` |
| 6. cron 路由 | `fhd-auto-update.sh`：`deploy_mode=image` → `fhd-apply-release-compose.sh` |
| 7. 健康检查 | `curl -sf http://127.0.0.1:5100/api/health`（与 tarball 相同；容器内 5000，宿主机 5100） |

**manifest v2 额外字段**：

```json
{
  "deploy_mode": "tarball",
  "image": "ghcr.io/42433422/XCMAX/xcagi-fhd-api",
  "image_digest": "sha256:..."
}
```

切换至 compose：将远端 manifest 的 `deploy_mode` 改为 `"image"`（或服务器设 `FHD_DEPLOY_MODE=image`），并确保 Docker + ghcr 登录就绪。

**手动 compose 应用**：

```bash
FHD_API_IMAGE=ghcr.io/42433422/XCMAX/xcagi-fhd-api \
FHD_API_IMAGE_DIGEST=sha256:<from-manifest> \
bash /opt/fhd-full/scripts/deploy/fhd-apply-release-compose.sh
```

**compose 回滚**：健康检查失败自动回滚至 `.deploy-image-digest` 上一值；也可手动指定旧 digest 再执行 apply-compose。

**生产切换 checklist（需 SSH，勿在 CI 自动执行）**：

1. 确认 `docker compose version` 与 `docker login ghcr.io` 成功  
2. `systemctl stop fhd-full.service && systemctl disable fhd-full.service`（避免与 5100 端口冲突）  
3. 确认 `/root/fhd-full.env` 中 `DATABASE_URL`、`SECRET_KEY`、`CACHE_REDIS_URL`（可用外部 Redis，无需 `--profile bundled-redis`）  
4. 数据卷：`/opt/fhd-full/data`、`uploads`、`logs`、`mods` 已由 compose 挂载  
5. 将 manifest `deploy_mode` 改为 `image`，或导出 `FHD_DEPLOY_MODE=image` 于 cron 环境  
6. 手动跑一次 `fhd-apply-release-compose.sh` 验证，再依赖 cron  

**冻结错误制品**（两种模式通用，**手动运维操作**，CI 不自动执行）：`mv .../fhd-manifest.json{,.hold}`；cron 见 manifest 缺失即跳过，不会反复重试坏制品。

## Python 格式化 / lint（FHD）

| 工具 | CI 状态 |
|------|---------|
| **Ruff** | `fhd-ci-cd.yml` / `fhd-test.yml` — 唯一 formatter + linter（`ruff check` + `ruff format --check`） |
| **black / isort** | **不在 CI** — 与 Ruff 冲突；本地 pre-commit 可保留，勿在 CI 重加除非统一配置 |

## 安全扫描门禁策略（FHD）

| 扫描 | Job / 工具 | 策略 |
|------|-----------|------|
| 容器漏洞 | `container-scan`（Trivy，`severity: CRITICAL,HIGH`，`exit-code 1`） | **硬门禁**：决策矩阵"安全扫描 CRITICAL → 阻断"指此项 |
| 依赖 CVE | `security-scan`（safety `--full-report`） | **Advisory**（非阻断）：输出 `::warning::`，需人工 triage |
| 静态代码（广） | `security-scan`（bandit `-lll --skip B101,B601,B110 --exit-zero`） | **Advisory** |
| 静态代码（SQL 注入） | `security-scan`（bandit `-lll -s B608`，无 `--exit-zero`） | **硬门禁** |

> 把 safety / bandit-broad 设为 advisory 是有意为之（传递依赖 CVE 常需评估、不宜直接红）；真正的供应链信任在 **Phase 1** 由 SBOM + cosign 签名 + SLSA provenance + 部署前 `cosign verify` 补强。

## 供应链信任（Phase 1 · SBOM + 签名 + Provenance）

`fhd-ci-cd.yml` → job `docker-build-fhd-api` 在推送 `xcagi-fhd-api`（按 digest）后：

| 步骤 | 工具 | 产物 |
|------|------|------|
| 镜像签名 | cosign **keyless**（Sigstore + GitHub OIDC，`id-token: write`，**无私钥**） | GHCR `.sig` |
| SBOM | `anchore/sbom-action`（syft，SPDX-JSON） | `fhd-api-sbom` artifact + cosign attest 附着 |
| Provenance | `actions/attest-build-provenance`（SLSA，`push-to-registry`） | GHCR attestation |

**部署门禁**：`fhd-deploy.yml` 两个环境在 `kubectl apply` 前 `cosign verify`（keyless，校验 OIDC issuer + 本仓 workflow 身份）；验证失败 **拒绝部署**。

- 身份正则：`^https://github.com/<org>/<repo>/.github/workflows/.+@refs/(heads/main|tags/FHD/v.+)$`
- **Break-glass**：设仓库变量 `COSIGN_VERIFY_DISABLE=1` 临时跳过验证（仅紧急；恢复后清除）。
- 制品身份仍为 `git_sha` + `sha256` + cosign digest，**不 bump 版本**（v10 锁）。

## Codecov（FHD 后端）

`fhd-ci-cd.yml` → job `backend-test` 上传 `coverage.xml` 至 Codecov。**可选**：需在 GitHub **Settings → Secrets → Actions** 配置 `CODECOV_TOKEN`；无 token 时步骤 `continue-on-error`（不阻断 CI）。本地 `coverage.xml` / `htmlcov/` 仍为 SSOT。

**覆盖率门槛 SSOT**：唯一真值 = `FHD/pyproject.toml` → `[tool.coverage.report] fail_under`（当前 `35`，对应 `source=[app]` 全量诚实基线 ~36%）。`backend-test` **不再**用 CLI `--cov-fail-under` 硬编码阈值（旧 `58` 来自已废弃窄 include 口径，与全量口径不可比）。提升覆盖率请单独立项、上调 `fail_under`，禁止用窄 include 凑数。

## E2E 分层

| 场景 | Workflow | 模式 | 用例 |
|------|----------|------|------|
| FHD 全量 CI（PR） | `fhd-ci-cd.yml` → `frontend-e2e` | `E2E_VITE_MOCK_API=1` + Vite :5001 | `npm run test:e2e:p0` → **8 pass / 6 skip** |
| 前端 path 过滤 / nightly | `e2e.yml` → `e2e-playwright-reusable.yml` | mock 同上；`schedule` / `workflow_dispatch` 额外 `E2E_FULL_STACK=1` | 全栈 **14/14**（含 `plan2026-skeleton`） |

SSOT 脚本：`FHD/frontend/package.json` → `test:e2e:p0`；编排见 `FHD/scripts/dev/e2e-full.sh`。

## 同步根 workflow

```bash
# 改 FHD 或 MODstore 下 workflow 后，重新发布到根
python scripts/dev/publish_ci_workflows_to_root.py
git add .github/workflows/
git commit -m "ci: sync root workflows from FHD/MODstore sources"
```

根 workflow 文件头含 `# CI SSOT: generated from ...` 注释，标识生成来源。

## 克隆与提交

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX
# commit / push 均在仓根
```

历史子仓 remote（`ai-excel-helper`、`XCMAX-roadmap`、`xcagi-modstore`）已退役；旧 `.git` 备份见 `~/XCMAX-archives/nested-git-backup-20260608/`。
