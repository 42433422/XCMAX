# skill-pr-review — GitHub PR 审查

## 一句话

GitHub PR 审查：CI 状态聚合、变更范围分析、自动 approve 低风险 PR。

## 触发场景

- Dependabot/Renovate PR 打开时（事件 `dependabot.pr.opened`）
- 内部 `auto_fix_loop.py` 触发的 PR（事件 `dependabot.autofix.triggered`）
- 人工派发本岗对某个 PR 做审查

## 输入

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `pr_number` | int | 是 | PR 编号 |
| `pr_url` | string | 是 | PR URL（用于审计回查） |
| `repo` | string | 是 | `owner/repo` 格式 |
| `dry_run` | bool | 否 | true 时只返回审查结论，不执行 approve/comment |

## 处理步骤

1. 调 GitHub API `GET /repos/{owner}/{repo}/pulls/{pull_number}` 拉 PR 详情。
2. 调 GitHub API `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` 拉变更文件列表。
3. 调 GitHub API `GET /repos/{owner}/{repo}/commits/{sha}/check-runs` 聚合 CI 状态。
4. 判定变更范围：
   - **仅依赖文件**（`package.json`、`package-lock.json`、`requirements.txt`、`pyproject.toml`、`go.mod`、`go.sum`、`Cargo.lock` 等）
   - **混合变更**（含业务源码）
   - **禁区文件**（`.env`、`_local_secrets/**`、`*.key`、`*.pem`）
5. 按决策矩阵评估风险。
6. 输出结构化结论。

## 决策矩阵

| PR 类型 | CI 状态 | 变更范围 | 决策 |
|---------|---------|---------|------|
| Dependabot patch/minor | 通过 | 仅依赖文件 | 自动 approve + merge |
| Dependabot major | 通过 | 仅依赖文件 | 派发 `vibe-coding-maintainer` 验证 |
| Dependabot security | 通过 | 仅依赖文件 | 自动 approve + merge（跳过 major 限制）|
| Dependabot any | 失败 | - | request_changes + 通知 |
| 人工 PR | - | - | 跑 `test-qa-runner` 验证 |

## 输出

```json
{
  "ok": true,
  "action": "approved|dispatched_verification|requested_changes|commented",
  "pr_number": 123,
  "pr_url": "https://github.com/owner/repo/pull/123",
  "summary": "Dependabot patch 升级 axios 0.27.2 → 0.28.0，CI 全绿",
  "warnings": [],
  "evidence": {
    "ci_status": "success",
    "changed_files": ["package.json", "package-lock.json"],
    "additions": 12,
    "deletions": 8,
    "labels": ["dependencies", "javascript"]
  },
  "requires_human": false
}
```

## 失败处置

- GitHub API 401 / 403 → 上报 `security-secrets-guard`，不重试。
- GitHub API 429 → 指数退避重试 1 次。
- CI 状态 fetching 失败 → 不 approve，输出 `action=requested_changes` 等待人工确认。

## 边界

- **不**改业务源码（即使审查发现 bug，只 comment，不改）
- **不**直接合并到主干（merge_method=squash 合到 PR 自己的分支可以）
- **不**绕过 major 限制（除 security PR）
