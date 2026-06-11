# 多仓拆分迁移指南

本文档是 [`split_repo_ci` 计划](../../.cursor/plans/split_repo_ci_8f1d8f57.plan.md)
Phase 2 的落地说明：如何把当前 monorepo 按组件拆成若干独立仓库，并完成
CI / 部署工作流的迁移。

## 1. 目标仓库边界

| 目标仓库 | 源路径 | 迁移优先级 |
| --- | --- | --- |
| `modstore-payment-java` | `MODstore_deploy/java_payment_service/` | **P0**（跨语言链路风险最高，先切） |
| `modstore-backend` | `MODstore_deploy/modstore_server/`、`modman/`、`tests/`、`pyproject.toml`、`alembic/`、`scripts/python-*.sh` | **P0** |
| `modstore-frontend` | `MODstore_deploy/market/` | P1 |
| `xiuci-marketing-site` | 根 `*.html`、`styles.css`、`main.js`、`assets/`、`site/`、`new/` | P1 |
| `modstore-deploy-infra` | `MODstore_deploy/docker-compose.yml`、`deploy/`、`MODstore_deploy/deploy/`、`MODstore_deploy/monitoring/`、`MODstore_deploy/scripts/` | P2 |
| `vibe-coding` | `vibe-coding/` | P2 |

## 2. 拆分顺序（风险从高到低）

```mermaid
flowchart LR
    startMono[monoRepo] --> step1[splitPaymentJava]
    step1 --> step2[splitModstoreBackend]
    step2 --> step3[splitMarketFrontend]
    step3 --> step4[splitMarketingSite]
    step4 --> step5[splitDeployInfra]
    step5 --> step6[splitVibeCoding]
```

## 3. 通用流程（每个目标仓库执行一次）

1. 在 GitHub / 内部托管上创建空仓库，名字遵循上表命名约定。
2. 在本仓库执行对应的 `scripts/split/split-<target>.sh`（基于
   [`git-filter-repo`](https://github.com/newren/git-filter-repo)）。脚本会生成
   `.split-out/<target>/` 目录，里面是一个带**干净历史**的 git 仓库，仅保留目标路径。
3. 把 `.split-out/<target>/` 推到新仓库：
   ```bash
   cd .split-out/<target>
   git remote add origin git@github.com:<org>/<target>.git
   git push -u origin main
   ```
4. 在新仓库启用对应的独立 CI/部署工作流（模板已放在
   [`docs/migration/new-repo-templates/`](new-repo-templates/) 下，源自当前仓库
   的 `.github/workflows/ci-*.yml` 与 `deploy*.yml`）。
5. 在新仓库配置 Secrets/Variables（参考 [`release-contracts.md`](../../MODstore_deploy/docs/migrations/release-contracts.md)）。
6. 把新仓库加为本仓库的上游（Git submodule 或 Docker 镜像依赖），并在本仓库
   删除被迁走的路径（见"双跑期 → 切换期 → 退役期"）。
7. 如果组件间有 API 契约（例如 Python 后端 ↔ Java 支付），通过 **版本化 API 契约**
   或 **固定 Docker 镜像 tag** 对齐，而不是把两个仓库绑在一个 monorepo。

## 4. 双跑期 → 切换期 → 退役期

| 阶段 | 说明 | 本仓库状态 |
| --- | --- | --- |
| 双跑期（1 周） | 新仓库 CI/部署生效；本仓库同名工作流仍跑做对照 | 保留 `MODstore_deploy/<component>` 目录 |
| 切换期（1 周） | 生产环境切到新仓库产物；旧目录只读 | 本仓库禁用对应 CI（workflow disabled） |
| 退役期 | 从本仓库删除源码目录；保留一个 `<component>/MIGRATED.md` 指向新仓库 | 彻底移除 |

每个组件都按这三段走，避免一次性切换导致的发布事故。

## 5. 契约与门禁

- 所有新仓库都复用 [`release-contracts.md`](../../MODstore_deploy/docs/migrations/release-contracts.md)
  中定义的"版本号来源 / 健康检查端口 / 回滚步骤"。
- 每个新仓库都必须在 GitHub branch protection 中把自己的 CI job 设为 required check。
- 跨仓库调用必须通过稳定 API（Python ↔ Java 走 `JAVA_PAYMENT_SERVICE_URL`、HTTP
  contract），不允许通过 git submodule + 源码导入的方式耦合。

## 6. 风险与缓解

1. **.env / 密钥分散**：拆仓前统一梳理 `.env.*.example` 并把只属于某组件的变量搬到
   对应仓库；通过 SSM/Secret Manager 收敛机密。
2. **事件契约漂移**：`MODstore_deploy/docs/contracts/events/*.json` 是跨组件事件
   schema，抽出到独立仓库或作为 Java + Python 两侧都引用的 `modstore-event-contracts`
   子包。
3. **文档引用断链**：本仓库内有大量相对 `../` 的引用，拆仓前运行
   `scripts/split/audit-cross-refs.sh` 列出需要改写的链接，迁移脚本里一并处理。

## 7. 相关文件

- 拆分脚本：[`scripts/split/`](../../scripts/split/)
- 发布契约：[`MODstore_deploy/docs/migrations/release-contracts.md`](../../MODstore_deploy/docs/migrations/release-contracts.md)
- 新仓库工作流模板：[`docs/migration/new-repo-templates/`](new-repo-templates/)
- 工作流 README：[`.github/workflows/README.md`](../../.github/workflows/README.md)
