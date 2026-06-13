# XCAGI 日常入口（START HERE）

> **版本线**：v10.0.0（全产品线锚点见 [`VERSION.md`](../VERSION.md)）  
> **公开文档站**：<https://docs.xiu-ci.com/>  
> **仓根一键启动**：`make setup && make dev`（Windows：`make -f Makefile.win setup`）

本页是 **18 份可直接执行** 的文档索引；更全的分层见 [`DOCUMENTATION_MAP.md`](DOCUMENTATION_MAP.md)。

---

## 0. 环境变量（克隆后先做）

**勿提交** 含密钥/令牌的 env 文件。从 example 复制到本地（均在 `.gitignore` 内）：

| 场景 | 复制命令 |
|------|----------|
| FHD Docker 全栈 | `cp .env.fhd-docker.example .env.fhd-docker` |
| Web / PostgreSQL | `cp .env.example .env` 并编辑 `DATABASE_URL`、`SECRET_KEY` |
| 前端 Vite 开发 | `cp frontend/.env.development.example frontend/.env.development` |
| 本地 MODstore 日更 | `cp XCAGI/.env.local-market.example XCAGI/.env.local-market` |
| 企业桌面 SQLite | `cp XCAGI/.env.enterprise-desktop.example XCAGI/.env.enterprise-desktop` |
| 公网市场联调 | `cp XCAGI/.env.online-market.example XCAGI/.env.online-market` |

`frontend/.env.generic` 与 `frontend/.env.minimal` 为 **无密钥** 的 Vite 构建预设，可留在仓库内。

---

## 1. 启动与验收（8 份）

| # | 文档 | 用途 |
|---|------|------|
| 1 | [`QUICK_START.md`](QUICK_START.md) | 5 分钟跑通宿主 + MOD |
| 2 | [`guides/快速启动说明.md`](guides/快速启动说明.md) | 桌面 / Docker 命令速查 |
| 3 | [`guides/PRODUCT_USER_FLOW.md`](guides/PRODUCT_USER_FLOW.md) | 安装 → 首启 → 行业 MOD → 日常使用 |
| 4 | [`DELIVERABLE_PRODUCT.md`](DELIVERABLE_PRODUCT.md) | 交付物清单与验收 API |
| 5 | [`guides/RELEASE_TWO_SKUS.md`](guides/RELEASE_TWO_SKUS.md) | personal / enterprise 双 SKU 发版 |
| 6 | [`guides/DESKTOP_DATABASE_DELIVERY.md`](guides/DESKTOP_DATABASE_DELIVERY.md) | 桌面 SQLite 交付 |
| 7 | [`guides/DEPLOYMENT_GUIDE.md`](guides/DEPLOYMENT_GUIDE.md) | 生产部署 |
| 8 | [`customer/CUSTOMER_SUPPORT.md`](customer/CUSTOMER_SUPPORT.md) | 客户升级 / 日志 / 回滚 |

**本地命令（仓根）**

```bash
make setup && make dev          # 依赖 + 开发服务
make test                       # pytest（FHD/tests/）
make lint                       # ruff / 前端 lint
make openapi-check              # OpenAPI 一致性
make e2e                        # Playwright（见 frontend/e2e/）
```

---

## 2. 架构与扩展（5 份）

| # | 文档 | 用途 |
|---|------|------|
| 9 | [`ARCHITECTURE.md`](ARCHITECTURE.md) | 系统架构与设计决策 |
| 10 | [`FEATURE_MAP.md`](FEATURE_MAP.md) | 功能边界与目录职责 |
| 11 | [`guides/MOD_AUTHORING_GUIDE.md`](guides/MOD_AUTHORING_GUIDE.md) | Mod 开发与 SSOT（`FHD/mods/`） |
| 12 | [`guides/PLATFORM_SHELL.md`](guides/PLATFORM_SHELL.md) | 宿主壳与 edition |
| 13 | [`MIGRATION_REGISTRY.md`](MIGRATION_REGISTRY.md) | 迁移与入口统一登记 |

---

## 3. 工程与质量（5 份）

| # | 文档 | 用途 |
|---|------|------|
| 14 | [`TECH_STACK.md`](TECH_STACK.md) | 技术栈摘要 |
| 15 | [`guides/DEPENDENCY_LOCKS.md`](guides/DEPENDENCY_LOCKS.md) | uv / pip 锁定与 CI 安装 |
| 16 | [`guides/ALEMBIC_MIGRATION_GUIDE.md`](guides/ALEMBIC_MIGRATION_GUIDE.md) | 数据库迁移 |
| 17 | [`reports/COVERAGE_RAMP.md`](reports/COVERAGE_RAMP.md) | 覆盖率目标与补测清单 |
| 18 | [`MIGRATION_v2_DROP_PLAN.md`](MIGRATION_v2_DROP_PLAN.md) | `*_v2` 应用服务收敛策略 |

---

## 覆盖率：从 CI Artifact 下载

主 CI：[`.github/workflows/fhd-ci-cd.yml`](../../.github/workflows/fhd-ci-cd.yml)（`working-directory: FHD`）。  
轻量 smoke（FHD 路径变更）：[`fhd-test.yml`](../../.github/workflows/fhd-test.yml)。

| 产物 | Artifact 名称 | 路径 | 保留 |
|------|---------------|------|------|
| 后端 HTML/XML | Codecov（`codecov-action`） | `FHD/coverage.xml`、本地 `htmlcov/` | PR 注释 |
| 前端 Vitest | `frontend-coverage` | `FHD/frontend/coverage/` | 7 天 |

**GitHub Actions 下载步骤**

1. 打开仓库 → **Actions** → 选择 **CI/CD Pipeline**（或对应 PR 运行）。
2. 在 run 页面底部 **Artifacts** → 下载 `frontend-coverage`。
3. 解压后在浏览器打开 `index.html` 查看前端覆盖率。
4. 后端：同一 workflow 的 **Upload coverage report** 步骤将 `coverage.xml` 推送到 Codecov；本地复现：

```bash
cd FHD
python -m pytest tests/ --cov=app --cov-report=html --cov-report=xml \
  --cov-fail-under=70 --ignore=tests/test_intent.py
open htmlcov/index.html   # macOS
```

**声称 vs 实测**：[CLAIMED_VS_ACTUAL.md](CLAIMED_VS_ACTUAL.md) · **测试索引**：[`tests/INDEX.md`](../tests/INDEX.md)

---

## 4. 生产服务器部署（FHD API · 双模：tarball + compose）

> v10 线内迭代；详见仓根 [`docs/CI_SSOT.md`](../../docs/CI_SSOT.md)（Phase 1 tarball + Phase 2 compose runbook）。

| 步骤 | 命令（`FHD/` 根目录） |
|------|------------------------|
| 锚点校验 | `python3 scripts/dev/verify_version_anchors.py` |
| 打包 | `bash scripts/deploy/fhd-pack-release.sh` |
| 发布到 update 站 | `bash scripts/deploy/fhd-push-release.sh` |
| 安装/切换 cron | 服务器：`bash /opt/fhd-full/scripts/deploy/fhd-install-server-cron.sh` |

- **默认模式**：`deploy_mode: tarball` → systemd `fhd-full.service`，端口 `5100`
- **compose 模式**：manifest `deploy_mode: image` → `fhd-apply-release-compose.sh` + `docker/docker-compose.fhd-prod.yml`（digest 钉扎，GHCR 拉取）
- **可选覆盖**：服务器 cron 环境设 `FHD_DEPLOY_MODE=image|tarball` 可覆盖 manifest（见 `fhd-auto-update.sh`）
- **manifest**：`/var/www/update/releases/stable/server/fhd-manifest.json`（v2 含 `image` / `image_digest`）
- **约定**：生产机 **不 git pull、不手改** 业务代码；失败自动回滚：

```bash
# tarball
FHD_RELEASE_TARBALL=/opt/fhd-full/.deploy-last.tar.gz \
  bash /opt/fhd-full/scripts/deploy/fhd-apply-release.sh

# compose（digest 见 manifest）
FHD_API_IMAGE=ghcr.io/42433422/XCMAX/xcagi-fhd-api \
FHD_API_IMAGE_DIGEST=sha256:... \
  bash /opt/fhd-full/scripts/deploy/fhd-apply-release-compose.sh
```

- **健康检查**：`curl -sf http://127.0.0.1:5100/api/health`
- **冻结错误制品**：`mv .../fhd-manifest.json{,.hold}`

---

## 相关链接

- 仓根地图：[`README.md`](../../README.md)
- **发版检查清单**：[`docs/deploy/RELEASE_CHECKLIST.md`](deploy/RELEASE_CHECKLIST.md)（tag `FHD/v*` → CVM + K8s + 客户端）
- **国际化**：[`docs/I18N_ROLLOUT.md`](I18N_ROLLOUT.md) · 前端 `src/i18n/`（zh-CN / en-US）；`localStorage.xcagi_locale` 切换
- CI SSOT：[`docs/CI_SSOT.md`](../../docs/CI_SSOT.md)
- OpenAPI：启动后 `http://127.0.0.1:5000/docs`
- Android 实验骨架（非签约级）：`guides/MOBILE_ANDROID.md`
