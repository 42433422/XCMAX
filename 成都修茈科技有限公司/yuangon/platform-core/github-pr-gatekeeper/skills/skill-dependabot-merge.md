# skill-dependabot-merge — Dependabot PR 自动合并

## 一句话

Dependabot PR 自动合并：patch/minor + 测试通过自动 merge，major 派发验证。

## 触发场景

- `skill-pr-review` 决策为 `approved` 后调用本 skill 完成合并
- Dependabot security PR 直接走本 skill（跳过 major 限制）

## 输入

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `pr_number` | int | 是 | PR 编号 |
| `repo` | string | 是 | `owner/repo` |
| `merge_method` | string | 否 | `squash`（默认）/ `merge` / `rebase` |
| `dry_run` | bool | 否 | true 时只返回"会合并"，不实际调 merge API |

## 处理步骤

1. 复核 PR 状态：`GET /repos/{owner}/{repo}/pulls/{pull_number}`，确认 `mergeable=true` 且 `mergeable_state=clean`。
2. 复核 CI 状态：`GET /repos/{owner}/{repo}/commits/{sha}/check-runs`，确认全部 success。
3. 检查 labels：
   - 含 `security` → 跳过 major 限制
   - 含 `dependencies` + `major` → 必须 `vibe-coding-maintainer` 验证
4. 调 GitHub API `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`：
   - `commit_title`：`{PR title} (#{pr_number})`
   - `commit_message`：PR body 摘要
   - `merge_method`：默认 `squash`
5. 删除分支（可选，看仓库配置）：`DELETE /repos/{owner}/{repo}/git/refs/heads/{branch}`

## 决策矩阵

| PR 类型 | CI 状态 | 行为 |
|---------|---------|------|
| Dependabot patch/minor + 仅依赖文件 | 通过 | 自动 merge（squash） |
| Dependabot major + 仅依赖文件 | 通过 | **不** merge，派发 `vibe-coding-maintainer` |
| Dependabot security | 通过 | 自动 merge（跳过 major 限制） |
| Dependabot any | 失败 | **不** merge，request_changes |

## 输出

```json
{
  "ok": true,
  "action": "merged",
  "pr_number": 123,
  "sha": "abc123def456...",
  "merge_method": "squash",
  "summary": "Dependabot patch 升级 axios 0.27.2 → 0.28.0，已 squash merge",
  "warnings": [],
  "evidence": {
    "mergeable": true,
    "mergeable_state": "clean",
    "ci_status": "success"
  }
}
```

## 失败处置

- `mergeable=false` → 等待 5 秒重试一次；仍失败则 request_changes + 通知
- `mergeable_state=blocked` → 有未解决 review，不强行 merge
- `mergeable_state=dirty` → 冲突，通知 PR 作者解决

## 边界

- **不**直接合并到主干分支（`main` / `master`）：本岗只合 PR 到 base 分支，主干合并归 `deploy-release-officer`
- **不**绕过 major 限制（除 security PR）
- **不**删除 base 分支，只删 PR 的 head 分支
