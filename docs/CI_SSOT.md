# CI SSOT（XCMAX 根仓）

**GitHub Actions 唯一调度入口**：[`.github/workflows/`](../.github/workflows/)

子目录 `FHD/.github/workflows/`、`MODstore_deploy/.github/workflows/` 仅保留 **README 指针**与 Issue/PR 模板，**不会**被 GitHub 执行。

## 仓库 git 历史说明（2026-08-01）

本仓当前工作区的 git 历史**始于 2026-07-21**（首个 commit `1b6ae8560`，`fix(deploy): bootstrap FHD staging on single CVM`）。
该日期之前的提交历史不在当前本地克隆中；远程仓库 `github.com/42433422/XCMAX` 的
旧分支/标签与 GitHub 侧 PR/Actions 记录仍是历史追溯的补充渠道。
对早于 2026-07-21 的变更归因，请查 GitHub 远程历史而非本地 `git log`。

## 分层

| 层级 | 路径 | 说明 |
|------|------|------|
| **仓根 SSOT** | `.github/workflows/*.yml` | push/PR/schedule 在此触发 |
| **FHD 实现源** | `FHD/.github/workflows/*.yml` | 编辑后运行 `python scripts/dev/publish_ci_workflows_to_root.py` 同步到根 |
| **MODstore 实现源** | `成都修茈科技有限公司/MODstore_deploy/.github/workflows/*.yml` | 同上 |

> **生成 vs 手写**：根仓 `fhd-*.yml` / `modstore-*.yml` 由 publish 脚本从实现源生成，文件头为
> `# CI SSOT: generated from … — DO NOT edit here`。**请改实现源后重跑 publish**，勿直接改根副本。
> 以下 **6 个根仓 workflow 为手写**（无生成头，直接在根仓维护）：
> `archive-hygiene.yml`、`corp-site-deploy.yml`、`desktop-macos-smoke.yml`、
> `e2e.yml`、`e2e-playwright-reusable.yml`、`frontend-unit.yml`。

## 常用 workflow

| 用途 | 根 workflow |
|------|-------------|
| FHD 后端 + 前端 + Docker | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) |
| FHD 轻量 smoke（path 过滤） | [`fhd-test.yml`](../.github/workflows/fhd-test.yml) |
| FHD Release gate | [`fhd-release-gate-ci.yml`](../.github/workflows/fhd-release-gate-ci.yml) |
| 前端 Vitest | [`frontend-unit.yml`](../.github/workflows/frontend-unit.yml) |
| Playwright P0 | [`e2e.yml`](../.github/workflows/e2e.yml) → [`e2e-playwright-reusable.yml`](../.github/workflows/e2e-playwright-reusable.yml) |
| Flutter Android+iOS CI | [`fhd-ci-mobile-flutter.yml`](../.github/workflows/fhd-ci-mobile-flutter.yml) |
| Flutter Android 发布 | [`fhd-release-android.yml`](../.github/workflows/fhd-release-android.yml) |
| Flutter iOS / TestFlight 发布 | [`fhd-release-ios.yml`](../.github/workflows/fhd-release-ios.yml) |
| MODstore Python CI | [`modstore-ci-backend-python.yml`](../.github/workflows/modstore-ci-backend-python.yml) |
| Archive 卫生 | [`archive-hygiene.yml`](../.github/workflows/archive-hygiene.yml) |
| FHD 服务器 API 发布包校验 | [`fhd-ci-cd.yml`](../.github/workflows/fhd-ci-cd.yml) → job `pack-verify` |
| FHD 全产品线 tag 编排 | [`fhd-release-orchestrator.yml`](../.github/workflows/fhd-release-orchestrator.yml) |
| FHD 单机 CVM 手动 rolling | [`fhd-deploy.yml`](../.github/workflows/fhd-deploy.yml) |

## 稳定版发布 tag 约定

- **产品版本锚点**：产品 `1.0.0.0`，工具链 `1.0.0`（见 `FHD/VERSION.md`）。
- **Git tag（发版触发）**：`FHD/v1.0.0.0`；制品身份同时记录 `git_sha` + `sha256`。
- **串联（单一编排入口）**：`FHD/v*` tag 仅触发两个 workflow —— `fhd-ci-cd.yml`（测试+镜像+CVM）与 `fhd-release-orchestrator.yml`。后者先跑 `verify-version-anchors`，再 **dispatch** 客户端 `fhd-release-desktop/web/android.yml`（**仅 Android**；服务器由 `fhd-ci-cd` 的 `cvm-push-release` 负责）。这些被编排的 workflow **已移除自身 `FHD/v*` tag 触发**，避免 tag 推送时双重运行。详见 [FHD/docs/deploy/RELEASE_CHECKLIST.md](FHD/docs/deploy/RELEASE_CHECKLIST.md)。

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

manifest 含 `"channel": "stable"|"staging"`。同一台 CVM（119.27.178.147）可并存两目录。

**Staging 首次引导（CVM root）**：

```bash
bash /opt/fhd-full/scripts/deploy/fhd-bootstrap-staging-cvm.sh
# 或仓库副本: bash FHD/scripts/deploy/fhd-bootstrap-staging-cvm.sh
```

会创建 `/root/fhd-staging.env`、`/opt/fhd-staging`、`fhd-staging.service:5101`、
nginx 路径 `https://xiu-ci.com/fhd-staging-api/`，以及 staging manifest。
`staging.xiu-ci.com` 需另配 DNS A → `119.27.178.147`（可选；workflow 已用 path health）。

staging cron 示例：

```bash
FHD_MANIFEST_PATH=/var/www/update/releases/staging/server/fhd-manifest.json \
FHD_DEPLOY_ROOT=/opt/fhd-staging \
FHD_SERVICE_NAME=fhd-staging.service \
FHD_HEALTH_PORT=5101 \
FHD_ENV_FILE=/root/fhd-staging.env \
FHD_AUTO_UPDATE_LOCK=/tmp/fhd-staging-auto-update.lock \
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

## 单机 CVM 手动 rolling（`fhd-deploy.yml`）

生产唯一路径：单台腾讯云 CVM（`119.27.178.147`）上的 **tarball + docker compose**。
自动 CD 见上文 `cvm-push-release` → 服务器 cron `fhd-auto-update.sh`。

`fhd-deploy.yml` 仅为 **break-glass**：SSH 到该机执行 `apply-latest`（强制跑 `fhd-auto-update.sh`）或 `restart-only`（`docker compose restart`）。

> 2026-07-14：已删除 `FHD/k8s/`、`FHD/helm/` 及 blue-green/canary/GitOps/预览环境等从未接通真实集群的清单与文档路径。
> 历史脚本在 `archive/ops/`；需要时从 git 历史取回。


## Secrets / Variables 清单

**Settings → Secrets and variables → Actions**（Secrets 与 Variables 两页）。标「跳过」者缺失时对应步骤跳过（不致 CI 失败）。

| 名称 | 类型 | 用途 | 缺失行为 |
|------|------|------|---------|
| `GITHUB_TOKEN` | 自动 | GHCR 推送、`gh workflow run` dispatch、GitHub Release | 自动注入 |
| `FHD_PUSH_HOST` | Secret / Var | CVM 推送目标（默认 `119.27.178.147`） | CVM/桌面推送跳过 |
| `FHD_PUSH_SSH_KEY` | Secret | CVM SSH 私钥（**勿入库**） | CVM 推送跳过 |
| `FHD_PUSH_USER` | Secret | CVM SSH 用户（默认 `root`） | 用默认 |
| `SERVER_SSH_KEY` | Secret | 桌面安装包上传 SSH 私钥（缺失则回退 `FHD_PUSH_SSH_KEY`） | 桌面上传跳过 |
| `CODECOV_TOKEN` | Secret | 覆盖率上传 | 步骤 `continue-on-error` |
| `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` / `APPLE_TEAM_ID` | Secret | macOS 公证 / 签名 | 出未公证包 |
| `CSC_LINK` / `CSC_KEY_PASSWORD` | Secret | **macOS Developer ID Application** `.p12`（base64 或路径）+ 导出密码；`fhd-release-desktop` 导入钥匙串签名，**不再**用 API 现场签发（Account Holder 限制） | 缺则 macOS job 失败 |
| `STAGING_BASE_URL` | Var | 容量 k6 目标（`fhd-capacity-staging-monthly`） | 容量测试跳过 |
| `STAGING_PROMETHEUS_URL` | Var / Secret | SLO 采集 Prometheus 端点 | SLO 采集降级 |
| `XCMAX_GIT_BRANCH` / `XCMAX_REMOTE_ROOT` | Var | 企业站 `corp-site-deploy` 同步参数 | 用默认 |
| `COSIGN_VERIFY_DISABLE` | Var | 置 `1` 临时跳过部署前 `cosign verify`（break-glass） | 不设=强制验证 |

> Phase 1（供应链）起 cosign **keyless**（Sigstore + GitHub OIDC）签名**免私钥**，不新增长期密钥。生产部署不依赖 kubeconfig。

## Branch protection（main）

已通过 API 配置（2026-06-13，2026-07 发版红线扩展）：required status checks 含 `guard-temp-scripts`、`backend-test`、`frontend-test`、`frontend-e2e`、`arch-fitness`、`security-scan`、`pack-verify`、`container-scan`、`docker-build-fhd-api`，以及 **`release-verify`**、**`desktop-build-smoke`**、**`SSOT Drift Gate`**、**`Release gate (hard block)`**；`vue-tsc` / `mypy` / `build:strict` 已在 `frontend-test` / `backend-test` 内硬失败。**覆盖率门禁**（2026-08-05 诚实化）：`backend-test` 内以 `coverage_ratchet.py --check --behavior --require-backend` 为唯一硬 gate（排除 `coverage_ramp` stub 的行为口径）；`frontend-test` 内以 `coverage_ratchet.py --check --require-frontend` 硬阻断前端覆盖率回退。本地等价：`bash FHD/scripts/dev/release_verify.sh`。

> **Public 仓库**：`42433422/XCMAX` 已为 **PUBLIC**；Actions 对 public repo 有免费额度。若 job 仍报 `payments have failed or spending limit`，在 [Payment information](https://github.com/settings/billing/payment_information) 添加有效支付方式。

> **Actions 账单**：若所有 job 在数秒内失败且 annotation 为 `recent account payments have failed or your spending limit needs to be increased`，须在 **Settings → Billing & plans** 修复付款或提高 spending limit；此阻断与 workflow/代码无关。

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

**原则**：与 tarball **双模共存**；manifest `deploy_mode` 决定 cron 路由。镜像身份用 digest 钉扎，产品版本保持 `1.0.0.0`。

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
| **black / isort** | **禁用** — 与 Ruff 冲突；CI、本地 pre-commit、FHD dev 依赖均不得重新启用 |

`guard-temp-scripts` 使用 `FHD/scripts/ci/guard_temp_scripts.py`：对 `_find_zero.py` / `_analyze_coverage.py` 做全量 tracked 扫描，对新增 `_fail*.txt`、`*.v1_backup`、根级/直挂 `scripts/` 的 `fix_` / `check_` / `final_` / `recover_` / `debug_` / `test_` 临时脚本做增量拦截（合法后端单元测试位于 `FHD/tests/`，不受影响）。本地 pre-commit 同步执行同一脚本。

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
- 制品身份仍为 `git_sha` + `sha256` + cosign digest，产品版本保持 `1.0.0.0`。

## Codecov（FHD 后端）

`fhd-ci-cd.yml` → job `backend-test` 上传 `coverage.xml` 至 Codecov。**可选**：需在 GitHub **Settings → Secrets → Actions** 配置 `CODECOV_TOKEN`；无 token 时步骤 `continue-on-error`（不阻断 CI）。本地 `coverage.xml` / `htmlcov/` 仍为 SSOT。

**覆盖率门槛 SSOT**：唯一真值 = `FHD/pyproject.toml` → `[tool.coverage.report] fail_under`（当前 `88`，对应 `source=[app]` 全量行覆盖 floor，2026-07-25 bump 收录）。分支 floor（81）与前端 floor 见 `FHD/metrics/coverage_ratchet_baseline.json`；对外现状口径见 `FHD/metrics/coverage-dual-summary.json`。

**后端覆盖率门禁唯一硬 gate = 行为口径（Delta A，2026-08-05）**：`backend-test` 的 `Behavior coverage gate` 步骤用 `coverage_ratchet.py --check --behavior --require-backend --record` 排除 `coverage_ramp` 注水 stub（`-m 'not coverage_ramp'`）后做硬阻断，floor 见 `coverage_ratchet_baseline.json` 的 `behavior_floors {lines, branches}`。全量 `coverage.json` + `fail_under` 保留为参考/趋势口径，不再作为唯一硬 gate。`backend-test` **不再**用 CLI `--cov-fail-under` 硬编码阈值；标准命令传 `--cov-fail-under=0`。

`FHD/scripts/ci/check_coverage_ssot.py` 在 smoke/full CI 中校验上述三个文件互相一致，并禁止 `pyproject.toml` 复制动态 pytest passed/failed 快照；动态实测只允许出现在 `coverage-dual-summary.json`。

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
git commit -m "ci: sync root workflows from FHD and MODstore_deploy sources"
```

根 workflow 文件头含 `# CI SSOT: generated from ...` 注释，标识生成来源。

## 克隆与提交

```bash
git clone https://github.com/42433422/XCMAX.git
cd XCMAX
# commit / push 均在仓根
```

历史子仓 remote（`ai-excel-helper`、`XCMAX-roadmap`、`xcagi-modstore`）已退役；旧 `.git` 备份见 `~/XCMAX-archives/nested-git-backup-20260608/`。


## 分支生命周期策略（branch lifecycle）

仓库历史上积累了大量远端/本地分支（886 / 193），部分 `behind main` 达 121–517，
合并冲突成本爆炸。遵循以下策略控制分支增量，并配套安全清理工具。

> **2026-08-05 受控清理已完成**：远端分支 **888 → 324**（删除 564 个，含 32 个已合并
> `devfleet/*sub-1*` + 530 个未合并 devfleet agent 分支，另 2 个运行中新生成）。`prune_stale_branches.py`
> 默认 dry-run 报告曾显示 `active=862 / stale=6 / deletable=0`（因 2026-07-21 git 历史重置，
> 所有分支提交时间均在旧阈值内，安全口径下无可自动删除项）。真正的僵尸来源是 **562 个
> 未合并自动 agent 分支**（`devfleet/cursor` + `codex` + `trae` + `claude_code`），它们领先
> `main` 巨大（ahead 1389+）且从未合并；本次按人工逐个审查后删除（保留当时 6 个开放 PR
> 分支，其 PR 随清理一并关闭）。**事后约定**：devfleet 子任务分支为一次性 agent 快照，
> 任务完成后由编排器自行清理，不再沉淀为长期分支。

### 命名规范
- 特性分支：`feature/<module>-<short-desc>`（如 `feature/admin-orders-foundation-ui`）
- 修复分支：`fix/<short-desc>`（如 `fix/lane-payload-loop`）
- 热修分支：`hotfix/<short-desc>`（如 `hotfix/cvm-autonomy-watcher-incident`）
- 发布分支：`release/<version>`（**受保护，永不删除**）
- 自动化/工具分支：`auto/`、`codex/`、`devfleet/`、`trae/`、`backup/`、`recover/`、`split/`、`merge/` 等
- 长期主线：`main`、`develop`（**受保护，永不删除**）

### 合并即删
- 合并进 `main` 的功能/修复分支，合并完成后原则上立即删除远端+本地分支。
- 有开放 PR 的分支**永不删除**（防止误删进行中的工作）。

### 陈旧阈值
- 默认：超过 **30 天无提交** 即视为 `stale`。
- `deletable` = 已合并进 `main` + 超过陈旧阈值无提交 + `behind main` 超过阈值。
- 人工清理时可按需放宽（`--stale-days` / `--before` / `--behind`）。

### 清理工具（安全 dry-run 优先）
`FHD/scripts/dev/prune_stale_branches.py` 默认 **dry-run 只输出分类报告**，
仅 `--apply` 才真正 `git push origin --delete`。分类：`active` / `stale` /
`deletable` / `protected`。保护清单（main / develop / release/* / 当前分支 /
开放 PR 分支）永不删除。

```bash
cd FHD
.venv/bin/python scripts/dev/prune_stale_branches.py            # dry-run 报告
.venv/bin/python scripts/dev/prune_stale_branches.py --list-all # 全量清单（dry-run）
.venv/bin/python scripts/dev/prune_stale_branches.py --apply    # 真正删除可删远端分支
.venv/bin/python scripts/dev/prune_stale_branches.py --apply --prune-local  # 追加清本地
.venv/bin/python scripts/dev/prune_stale_branches.py --before 2026-06-01 --behind 50 --stale-days 60
```

> **安全护栏**：删除前务必先跑 dry-run 核对报告；`--apply` 是不可逆操作，建议
> 分阶段（先 `--before` 框定范围）执行。


## 单机部署速查（替代已删除的 K8s/Helm 节）

```bash
# 自动：main/tag → fhd-ci-cd → cvm-push-release → 服务器 fhd-auto-update.sh
# 手动 break-glass：
gh workflow run fhd-deploy.yml -f environment=production -f action=apply-latest
# 或仅重启 compose：
gh workflow run fhd-deploy.yml -f environment=production -f action=restart-only
```

健康检查：

```bash
curl -sf https://xiu-ci.com/fhd-api/api/health
```

## 自治闭环（Autonomy）

> **详细手册**：[autonomy.md](./autonomy.md)
> **范围**：桌面 / 服务器 / CI 三端一体化自治系统，覆盖用户三大痛点 — 触发闭环 / 非代码故障 / 副作用预测。

### 三端自治链路

| 端 | 实现 | 触发方式 | 主要职责 |
|---|---|---|---|
| 桌面 | `FHD/desktop/autonomy/controller.ts` | main.ts start() + backend exit ingest | backend 崩溃回滚 / 降级状态修复 / OTA 失败回滚 |
| 服务器 | `FHD/scripts/autonomy/cvm_autonomy_watcher.py` | GitHub Actions cron `*/10 * * * *` SSH 触发 | health_down / manifest_drift / disk_full / compose_unhealthy |
| CI | `FHD/scripts/ci/ai_self_heal.py` + `ai_review.py` | `workflow_run(failure)` + `pull_request(opened/synchronize)` | CI 失败自愈 + PR 自动 review |

### CI Workflows

| Workflow | 触发 | 文件 |
|---|---|---|
| `fhd-ai-self-heal.yml` | `workflow_run` completed(failure) | `.github/workflows/fhd-ai-self-heal.yml` |
| `fhd-ai-review.yml` | `pull_request` opened/synchronize | `.github/workflows/fhd-ai-review.yml` |
| `fhd-cvm-autonomy-watcher.yml` | `schedule(*/10 * * * *)` + workflow_dispatch | `.github/workflows/fhd-cvm-autonomy-watcher.yml` |

### 关键约束

| 约束 | 说明 |
|---|---|
| 同指纹 24h 去重 | `ai-self-heal` 对相同错误指纹 24h 内不重复创建 PR（budget 限制） |
| `autonomy/` 分支不递归 | ai-self-heal 不处理 `autonomy/*` 分支失败，避免自愈自愈递归 |
| LLM fail-open | LLM 调用 30s 超时不阻断主流程，降级到纯规则匹配 |
| `confirmed-high` 才阻断 | ai-review 仅 LLM 高置信度（confirmed-high）高危问题才阻断合并 |
| 跨端门禁默认禁用 | env `XCAGI_CROSS_TIER_GATE=1` 启用，fail-open（查询失败不阻断） |
| ImpactPredictor 拦截不阻断 | 误判仅写 audit，不抛错；deny 时不执行但记录原因 |
| Policy 纯函数 | 禁止 `Date.now()`，时间窗口用 signals 自身 `ts`（取最新信号 ts 作为"现在"） |
| 所有动作必审计 | AuditEntry 是唯一事后真相，三端共用语义；通过 `audit_query.py` CLI 查询 |

### 触发条件矩阵

| 信号源 | 触发动作 | 自动/人工 |
|---|---|---|
| 桌面 backend 5min 内 ≥3 次 exit | `rollback_version`（high） | 自动决策 + CrossTierGate 预检 + 人工 escalate 兜底 |
| 桌面 disk_full | `clear_cache`（low） | 自动执行 |
| 桌面 disk_low / db_corrupt / network_down | `escalate`（high） | 直接人工 |
| 桌面 ota_install_failed | `rollback_version`（high） | 自动决策 + 预检 |
| 服务器 /api/health 持续 503 | `restart_service`（max_attempts=2） | 自动 + 失败 escalate |
| 服务器 manifest_drift | `freeze_manifest` | 自动（防 cron 反复重试） |
| 服务器 disk_full | `clear_logs` | 自动 |
| 服务器 compose_unhealthy | `restart_service` | 自动 |
| CI fhd-ci-cd 失败 | 创建修复 PR + 标 `needs-human` | 自动诊断 + 人工合并 |
| PR opened/synchronize | ai-review 行级评论 | 自动（confirmed-high 才阻断） |

### 跨端门禁场景

| 场景 | 检查项 | 防止问题 |
|---|---|---|
| 桌面 `rollback_version` | `server_manifest_frozen` | 桌面回滚到服务器已冻结的版本 |
| 服务器 `rollback_to_last_tarball` | `desktop_pending_rollback_marker` | 嵌套回滚导致数据丢失 |
| CI `cvm-push-release` | `server_manifest_frozen` | CI 推送覆盖运维手动冻结的 manifest |

### Audit 查询

```bash
# 查桌面端最近 24h 的所有 rollback 动作
python scripts/autonomy/audit_query.py --source desktop --since 24h \
  --filter 'action.type=rollback_version'

# 查服务器端最近 1h 失败的动作
python scripts/autonomy/audit_query.py --source server --since 1h \
  --filter 'result.ok=false'
```

完整用法与运维剧本见 [autonomy.md](./autonomy.md)。

