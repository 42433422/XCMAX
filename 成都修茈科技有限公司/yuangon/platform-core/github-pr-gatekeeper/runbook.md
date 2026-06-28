# Runbook - GitHub PR 守门员

| 字段 | 值 |
|------|----|
| 员工 ID | `github-pr-gatekeeper` |
| 负责区域 | `platform-core` |
| 应急联系 | admin |

## 决策矩阵

| PR 类型 | CI 状态 | 变更范围 | 动作 |
|---------|---------|----------|------|
| Dependabot patch/minor | 通过 | 仅依赖文件 | approve + merge 建议 |
| Dependabot major | 通过 | 仅依赖文件 | 派发 `vibe-coding-maintainer` 验证 |
| security update | 通过 | 仅依赖文件 | approve + merge 建议 |
| 任意 PR | 失败 | 任意 | request_changes |
| 人工 PR | 未知 | 任意 | 派发 `test-qa-runner` |

## 日常巡检

```bash
gh pr list --state open --json number,title,author,headRefName,baseRefName
gh run list --limit 20
```

没有 `gh` 或登录状态不足时，返回待人工确认，不要编造 PR 状态。
