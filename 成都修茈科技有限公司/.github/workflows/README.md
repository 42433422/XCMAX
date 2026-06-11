# GitHub Actions workflow 组织约定

本目录按"组件级独立 CI + 组件级独立部署"的模式组织。
每个业务单元都拥有自己的 CI 与部署工作流，仅在自身路径变更时触发。

## CI 工作流（按组件）

| 工作流 | 覆盖范围 | 触发路径 |
| --- | --- | --- |
| `ci-marketing-site.yml` | 根层营销静态官网 | `*.html`、`styles.css`、`main.js`、`assets/**`、`site/**`、`new/**` |
| `ci-root-frontend.yml` | 根层 Vue 3 + Vite（modstore-market） | `src/**`、`package.json`、`vite.config.*`、`tsconfig*.json`、`vitest*`、`playwright*` |
| `ci-market.yml` | MODstore 市场前端 | `MODstore_deploy/market/**` |
| `ci-backend-python.yml` | MODstore FastAPI 网关 | `MODstore_deploy/modstore_server/**`、`modman/**`、`tests/**`、`pyproject.toml`、`alembic/**` |
| `ci-payment-java.yml` | Spring Boot 支付子服务 | `MODstore_deploy/java_payment_service/**` |
| `ci-vibe-coding.yml` | vibe-coding 独立 Python 包 | `vibe-coding/**` |

**原则**：每个 workflow 拥有独立 `concurrency` group，互不取消彼此；`paths` 过滤避免"改一处全量构建"。

## 部署工作流（按组件）

| 工作流 | 监听的 CI（workflow_run） | 部署目标 |
| --- | --- | --- |
| `deploy.yml` | `CI - Backend Python` | Python 后端（`modstore-uvicorn`/`modstore` systemd，或 `docker compose up api`） |
| `market-live-deploy.yml` | `CI - Market` | market 前端 dist |
| `deploy-payment-java.yml` | `CI - Payment Java` | Spring Boot `modstore-payment` |

**关键变更**：
- 部署路径不再默认硬编码到 `/root/成都修茈科技有限公司`；
- 使用新的组件化 Variables：`DEPLOY_BACKEND_REMOTE_DIR`、`DEPLOY_MARKET_REMOTE_DIR`、`DEPLOY_PAYMENT_REMOTE_DIR`；
- `DEPLOY_REMOTE_REPO` 仅作为"未拆仓兼容"的回退路径保留，且不再提供 monorepo 默认值（未设置任何变量会直接失败，避免误发布）；
- 每个部署都优先调用 `scripts/python-release.sh` / `scripts/node-release.sh` / `scripts/java-release.sh`（组件化发布脚本），没有则走内联回退。

## Branch protection / Required checks（手工配置）

拆 CI 之后，需要在 GitHub → Settings → Branches → Branch protection rules (`main`) 勾选下列 required checks：

- `Marketing site (static pages)`（来自 `ci-marketing-site.yml` 的 job name）
- `Root project (Vue 3 + Vite)`（来自 `ci-root-frontend.yml`）
- `Market subproject (MODstore_deploy/market)`（来自 `ci-market.yml`）
- `MODstore (Python — lint + tests + coverage)`（来自 `ci-backend-python.yml`）
- `MODstore (Java payment service)`（来自 `ci-payment-java.yml`）
- `vibe-coding (Python package)`（来自 `ci-vibe-coding.yml`）

其中每个检查仅在路径过滤命中时才会执行；GitHub 对未被 `paths` 触发的 required check 会自动放行（"skipped"），不会阻塞 PR。

## 拆仓后的迁移清单

当某个组件抽离到独立仓库时，对应工作流 + 部署文档随之迁移：
1. 把 `.github/workflows/ci-<component>.yml` 复制到新仓库根的 `.github/workflows/` 并去掉 `paths` 前缀；
2. 把 `deploy-*.yml` 复制并同样去掉路径前缀；
3. 在新仓库配置同名 Secrets/Variables；
4. 移除本仓库对应的 workflow 文件，避免双重触发。
