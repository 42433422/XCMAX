# 成都修茈科技有限公司 — Monorepo

本仓库当前承载多个业务组件，正按照 [`docs/migration/split-repos.md`](docs/migration/split-repos.md)
拆分为多个独立仓库。在拆仓完成前，**本仓库使用"组件级 CI + 组件级部署"** 做边界隔离。

## 组件一览

| 组件 | 路径 | 语言/框架 | 独立 CI | 独立部署 |
| --- | --- | --- | --- | --- |
| 营销官网静态页 | `*.html`、`styles.css`、`main.js`、`assets/`、`site/`、`new/` | 原生 HTML/CSS/JS | [`ci-marketing-site.yml`](.github/workflows/ci-marketing-site.yml) | — |
| 根 Vue 3 项目（modstore-market） | `src/`、`package.json`、`vite.config.ts` | Vue 3 + Vite | [`ci-root-frontend.yml`](.github/workflows/ci-root-frontend.yml) | — |
| MODstore market 前端 | `MODstore_deploy/market/` | Vue 3 + Vite | [`ci-market.yml`](.github/workflows/ci-market.yml) | [`market-live-deploy.yml`](.github/workflows/market-live-deploy.yml) |
| MODstore Python 后端 | `MODstore_deploy/modstore_server/` 等 | FastAPI / Python 3.11 | [`ci-backend-python.yml`](.github/workflows/ci-backend-python.yml) | [`deploy.yml`](.github/workflows/deploy.yml) |
| Java 支付子服务 | `MODstore_deploy/java_payment_service/` | Spring Boot 17 | [`ci-payment-java.yml`](.github/workflows/ci-payment-java.yml) | [`deploy-payment-java.yml`](.github/workflows/deploy-payment-java.yml) |
| vibe-coding 独立 Python 包 | `vibe-coding/` | Python | [`ci-vibe-coding.yml`](.github/workflows/ci-vibe-coding.yml) | — |

## 工程原则

1. 每个组件有自己的 CI（独立 `concurrency` group + 路径过滤），改一处不会触发所有组件的构建。
2. 部署流水线按组件独立；不再默认依赖 monorepo 路径硬编码。
3. 跨语言全链发布脚本（`MODstore_deploy/scripts/remote_sync_extract.sh`、
   `_remote_deploy_extract.sh`）已标记 `[DEPRECATED]`，仅为未拆仓服务器过渡保留；
   新发布请使用 `python-release.sh` / `node-release.sh` / `java-release.sh`。
4. 运行期产物（outbox、webhook 投递 JSON、payment_orders、chroma）不进入源码仓库；
   由 `MODSTORE_RUNTIME_DIR` / `MODSTORE_WEBHOOK_EVENTS_DIR` 指向数据盘。
   提交门禁见 [`ci-runtime-artifacts-guard.yml`](.github/workflows/ci-runtime-artifacts-guard.yml)。

## 关键文档

- [仓库治理与多仓拆分计划](docs/migration/split-repos.md)
- [组件化发布契约](MODstore_deploy/docs/migrations/release-contracts.md)
- [CI workflow 约定](.github/workflows/README.md)
- [MODstore 架构](MODstore_deploy/docs/ARCHITECTURE.md)
- [MODstore 贡献指南](MODstore_deploy/CONTRIBUTING.md)

## 拆仓后的导航

当某个组件抽离到独立仓库后，本文件的对应行会改为指向新仓库 URL，
同时在本仓库保留一个 `<组件>/MIGRATED.md` 指路短文。
