# Runbook — 推送更新员工

## 日常：开工前 30 秒

1. 读取 `/api/health` 或使用 `git-repo-context`。
2. 若 `deploy_tier` 与机器不符（例如生产机显示 `local`），**停止**并修正 `.env` / 编排中的 `MODSTORE_DEPLOY_TIER`。

## 晋级 staging（Mac mini）

1. 确认本机 `MODSTORE_DEPLOY_TIER=staging`。
2. 确认分支指向团队约定的 `staging`（或你们的分支模型）。
3. 将 `git-repo-context` 输出粘贴到工单或聊天，再交给 CI / Runner。

## 晋级生产

1. 仅在 `deploy_tier=production` 的生产机上由「发布部署主管」执行发布脚本；本岗位只做发布前最后一遍上下文确认。
