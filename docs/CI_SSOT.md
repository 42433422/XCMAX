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
| FHD API 生产镜像（GHCR） | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) → job `docker-build-fhd-api` |

## 发布 tag 约定（v10 线内）

- **产品版本锚点**：恒 `10.0.0`（见 `FHD/VERSION.md`），**不因功能发版 bump 主版本**。
- **Git tag（发版触发）**：`FHD/v10.0.0` 或 `FHD/v10.*`；**制品身份**用 tarball 内 `git_sha` + `sha256`，非 tag 名。
- **串联**：`fhd-ci-cd.yml` 在 `FHD/v*` tag 上触发 `fhd-deploy.yml`（K8s，需 `KUBE_CONFIG`）；**生产 CVM tarball 拉取**由本机 `fhd-push-release.sh` 推送至 update 目录，服务器 cron 应用（见下方 runbook）。

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
| 4. 服务器 GHCR 登录 | **一次性**：`echo $GITHUB_PAT | docker login ghcr.io -u <github_user> --password-stdin`（PAT 需 `read:packages`） |
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
