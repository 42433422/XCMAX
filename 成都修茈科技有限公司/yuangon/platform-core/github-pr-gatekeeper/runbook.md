# Runbook — GitHub PR 守门员 (`github-pr-gatekeeper`)

| 字段 | 值 |
|------|----|
| 员工 ID | `github-pr-gatekeeper` |
| 负责区域 | `platform-core` · `build-release` |
| 最后更新 | 2026-06-28 |
| 应急联系 | admin |

## 触发条件

| 事件 | 来源 | 动作 |
|------|------|------|
| `dependabot.pr.opened` | Dependabot webhook | 跑 `skill-pr-review` 决策矩阵 |
| `dependabot.autofix.triggered` | 内部 `auto_fix_loop.py` | 跑 `skill-pr-review` 决策矩阵 |
| 人工 PR 提交 | GitHub webhook / 人工派发 | 派发 `test-qa-runner` 验证后决策 |
| major 升级 PR | Dependabot | 派发 `vibe-coding-maintainer` 兼容性验证 |

## 标准流程

### 流程 1：Dependabot patch/minor PR

1. 收到 `dependabot.pr.opened` 事件。
2. 调 GitHub API 拉 PR 详情：`title`、`changed_files`、`additions`、`deletions`、`labels`。
3. 检查变更范围：必须仅 `package.json` / `package-lock.json` / `requirements.txt` / `pyproject.toml` / `go.mod` 等依赖文件。
4. 调 GitHub API 拉 CI 状态（`GET /repos/{owner}/{repo}/commits/{sha}/check-runs`）。
5. CI 全绿 → 自动 `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`（event=APPROVE）。
6. 自动 `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`（merge_method=squash）。
7. 输出结构化结果。

### 流程 2：Dependabot major PR

1. 同流程 1 的步骤 1-4。
2. **不**自动 approve，派发 `vibe-coding-maintainer` 做兼容性验证：
   - 调 `employee.task.dispatch:vibe-coding-maintainer`，传入 PR URL + 影响范围。
3. 等 `employee.task.done:vibe-coding-maintainer` 事件回填。
4. 验证通过 → approve + merge；验证失败 → request_changes + 通知 admin。

### 流程 3：Dependabot security PR

1. 同流程 1 的步骤 1-4。
2. 检查 labels 是否含 `security`。
3. **跳过 major 限制**，直接 approve + merge（安全补丁优先）。
4. 通知 admin 与 `security-secrets-guard`。

### 流程 4：人工 PR

1. 收到人工 PR 提交事件。
2. 派发 `test-qa-runner` 跑测试：
   - 调 `employee.task.dispatch:test-qa-runner`，传入 PR URL + diff。
3. 等 `employee.task.done:test-qa-runner` 事件回填。
4. 测试通过 → 跑 `skill-pr-review` 决策矩阵（变更范围 + CI 状态 + 风险评分）。
5. 测试失败 → request_changes + 通知 PR 作者。

## GitHub API 调用约定

- Token 来源：`security-secrets-guard` 持有，本岗只读引用。
- API 版本：REST v3（`/repos/...`），GraphQL v4 仅用于复杂查询。
- Rate limit：60 req/min（无 token）/ 5000 req/min（有 token），必须用 token。
- 失败重试：429 / 5xx 重试 1 次（指数退避），其他不重试。

## 输出契约

```json
{
  "ok": true,
  "action": "approved|merged|dispatched_verification|requested_changes|commented",
  "pr_number": 123,
  "pr_url": "https://github.com/owner/repo/pull/123",
  "summary": "Dependabot patch 升级 axios 0.27.2 → 0.28.0，CI 全绿，已自动 approve + merge",
  "warnings": [],
  "evidence": {
    "ci_status": "success",
    "changed_files": ["package.json", "package-lock.json"],
    "additions": 12,
    "deletions": 8
  },
  "requires_human": false
}
```

## 故障处置

| 场景 | 处置 |
|------|------|
| GitHub API 401 | Token 失效 → 上报 `security-secrets-guard` 轮换；本岗不直接改 `.env` |
| GitHub API 403 | 权限不足 → 检查 Token scope 是否含 `repo` / `pull-requests:write`；上报 admin |
| GitHub API 429 | Rate limit → 指数退避重试 1 次；仍失败则排队等下个窗口 |
| CI 状态 fetching 失败 | 不 approve，等 CI 重跑或人工确认 |
| `vibe-coding-maintainer` 验证超时 | 升级到 admin，不抢跑 merge |
| 上游依赖未完成 | 等待 `employee.task.done:change-request-auditor` + `employee.task.done:test-qa-runner` 事件，不自行推进 |

## 验收检查清单

- [ ] `employee.yaml.depends_on` 与 manifest 根级一致（`change-request-auditor` / `test-qa-runner`）
- [ ] `actions.handlers` 三方一致（yaml / manifest / `_DISPATCH`）
- [ ] scope_globs 路径存在（`.github/dependabot.yml` 等）
- [ ] `employee_pack_consistency_warnings` 无 handler warning
- [ ] echo smoke 测试通过

## 应急升级路径

1. GitHub 平台性故障 → 暂停所有自动 merge → 通知 admin 与 `daily-orchestrator`。
2. Token 泄露风险 → 立即联动 `security-secrets-guard` 旋转 → 本岗出影响评估报告。
3. major 升级引发线上故障 → 立即 revert PR → 通知 `deploy-release-officer` 与 `change-request-auditor` 复盘。

---
*本文件由 admin 在 2026-06-28 录入 yuangon 编制，与 change-request-auditor 分工（外部 PR vs 内部 CR）。*
