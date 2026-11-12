# 技能：推送与部署前上下文检查

## 目标

在将代码从本地 → Mac mini（staging）→ 生产 的任意一步之前，确认**环境**与**版本**一致，避免误推分支或未提交变更。

## 事实来源（优先级）

1. 服务端：`GET /api/health` → `deploy_tier`、`git_sha`、`hostname`
2. 运维工具：`shell_exec` → `git-repo-context`（仓库根路径 `.`），输出 `DEPLOY_TIER`、`HOSTNAME`、`GIT_SHA`、`BRANCH`、`STATUS`
3. 各机环境变量：`MODSTORE_DEPLOY_TIER` 为 `local` | `staging` | `production`（或别名 `dev` / `sandbox` / `prod`）

## 检查清单（晋升 staging 前）

- [ ] `MODSTORE_DEPLOY_TIER` 与当前机器角色一致（开发机 `local`、Mac mini `staging`、生产 `production`）
- [ ] 当前分支 = 预期分支（如 `staging` 或 `dev`）
- [ ] `git status` 无意外未提交变更，或已明确要带的 WIP
- [ ] `GIT_SHA` 与 CI/预期 tag 可对应（若使用构建注入的 `MODSTORE_GIT_SHA` 更准）

## 检查清单（合并到 main / 生产发布前）

- [ ] staging 或预发已跑通关键用例
- [ ] 与「发布部署主管」runbook 中的闸门一致（人工确认、灰度等）
- [ ] 生产机 `deploy_tier=production` 且密钥非占位值

## 与发布部署主管的分工

- **你**：上下文与可推性（where / what commit / dirty or clean）
- **发布部署主管**：如何构建、发哪、回滚与探活

完成后将结论同步给责任人类，不自动执行高风险 `git push --force` 等操作。
