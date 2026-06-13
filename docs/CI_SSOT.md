# CI SSOT（XCMAX 根仓）

**GitHub Actions 唯一调度入口**：[`.github/workflows/`](../.github/workflows/)

子目录 `FHD/.github/workflows/`、`MODstore_deploy/.github/workflows/` 仅保留 **README 指针**与 Issue/PR 模板，**不会**被 GitHub 执行。

## 分层

| 层级 | 路径 | 说明 |
|------|------|------|
| **仓根 SSOT** | `.github/workflows/*.yml` | push/PR/schedule 在此触发 |
| **FHD 实现源** | `FHD/.github/workflows/*.yml` | 编辑后运行 `python scripts/dev/publish_ci_workflows_to_root.py` 同步到根 |
| **MODstore 实现源** | `成都修茈科技有限公司/MODstore_deploy/.github/workflows/*.yml` | 同上 |

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
- **串联**：`FHD/v*` tag 触发 `fhd-ci-cd.yml`（测试+镜像+CVM）、`fhd-release-orchestrator.yml`（GitHub Release + 触发 K8s/客户端）、`fhd-deploy.yml`（K8s）。详见 [FHD/docs/deploy/RELEASE_CHECKLIST.md](FHD/docs/deploy/RELEASE_CHECKLIST.md)。

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

## Branch protection（须仓库 Owner 在 GitHub UI 配置）

Agent **无法**从本环境开启 branch protection。建议在 **Settings → Branches → main** 启用：

- Required status checks：`backend-test`、`frontend-test`、`pack-verify`、`docker-build-fhd-api`、`container-scan`（及 `Release gate CI` 若启用）
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

**冻结错误制品**（两种模式通用）：`mv .../fhd-manifest.json{,.hold}`

## Python 格式化 / lint（FHD）

| 工具 | CI 状态 |
|------|---------|
| **Ruff** | `fhd-ci-cd.yml` / `fhd-test.yml` — 唯一 formatter + linter（`ruff check` + `ruff format --check`） |
| **black / isort** | **不在 CI** — 与 Ruff 冲突；本地 pre-commit 可保留，勿在 CI 重加除非统一配置 |

## Codecov（FHD 后端）

`fhd-ci-cd.yml` → job `backend-test` 上传 `coverage.xml` 至 Codecov。**可选**：需在 GitHub **Settings → Secrets → Actions** 配置 `CODECOV_TOKEN`；无 token 时步骤 `continue-on-error`（不阻断 CI）。本地 `coverage.xml` / `htmlcov/` 仍为 SSOT。

## E2E 分层

| 场景 | Workflow | 模式 | 用例 |
|------|----------|------|------|
| FHD 全量 CI（PR） | `fhd-ci-cd.yml` → `frontend-e2e` | `E2E_VITE_MOCK_API=1` + Vite :5001 | `npm run test:e2e:p0` → **9 pass / 5 skip** |
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
