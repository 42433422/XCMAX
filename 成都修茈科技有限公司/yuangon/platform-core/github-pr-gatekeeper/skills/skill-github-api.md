# skill-github-api — GitHub API 调用

## 一句话

GitHub API 调用：review/approve/merge/comment，统一封装鉴权、限流、重试。

## 触发场景

- `skill-pr-review` 与 `skill-dependabot-merge` 内部调用
- 任何需要直接调 GitHub REST/GraphQL 的场景

## 输入

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `method` | string | 是 | HTTP method: `GET/POST/PUT/PATCH/DELETE` |
| `path` | string | 是 | API path（如 `/repos/{owner}/{repo}/pulls/{n}`），不含 base URL |
| `body` | object | 否 | JSON body |
| `graphql_query` | string | 否 | GraphQL query（与 `method/path` 互斥） |
| `graphql_variables` | object | 否 | GraphQL variables |
| `dry_run` | bool | 否 | true 时只返回"会调用什么"，不发请求 |

## 鉴权

- Token 来源：`security-secrets-guard` 持有，本岗只读引用，不写 `.env`。
- Token 必备 scope：`repo`（私有库）/ `public_repo`（公开库）/ `workflow`（改 GitHub Actions）/ `pull-requests:write`（fine-grained token）。
- Header：`Authorization: Bearer {token}`、`Accept: application/vnd.github+json`、`X-GitHub-Api-Version: 2022-11-28`。

## 限流策略

- 标准 token：5000 req/h + 30 req/min（GraphQL）
- 检查 `X-RateLimit-Remaining` 与 `X-RateLimit-Reset`：
  - `Remaining < 100` → 暂停 60s
  - `Remaining = 0` → 等 `Reset` 时间戳
- 429 / 5xx 重试 1 次（指数退避 1s → 2s）
- 4xx（除 429）→ 不重试

## 主要端点

| 操作 | Method | Path |
|------|--------|------|
| 拉 PR 详情 | GET | `/repos/{owner}/{repo}/pulls/{pull_number}` |
| 拉变更文件 | GET | `/repos/{owner}/{repo}/pulls/{pull_number}/files` |
| 拉 CI 状态 | GET | `/repos/{owner}/{repo}/commits/{sha}/check-runs` |
| 提交 review | POST | `/repos/{owner}/{repo}/pulls/{pull_number}/reviews` |
| Approve PR | POST | `/repos/{owner}/{repo}/pulls/{pull_number}/reviews` (event=APPROVE) |
| Request changes | POST | `/repos/{owner}/{repo}/pulls/{pull_number}/reviews` (event=REQUEST_CHANGES) |
| 评论 | POST | `/repos/{owner}/{repo}/issues/{pull_number}/comments` |
| Merge | PUT | `/repos/{owner}/{repo}/pulls/{pull_number}/merge` |
| 删分支 | DELETE | `/repos/{owner}/{repo}/git/refs/heads/{branch}` |

## 输出

```json
{
  "ok": true,
  "status_code": 200,
  "action": "github_api_called",
  "method": "POST",
  "path": "/repos/owner/repo/pulls/123/reviews",
  "response_summary": "approved PR #123",
  "rate_limit_remaining": 4998,
  "rate_limit_reset": 1730000000
}
```

## 失败处置

| HTTP | 含义 | 处置 |
|------|------|------|
| 401 | Token 失效 | 上报 `security-secrets-guard` 旋转，不重试 |
| 403 | 权限不足 | 检查 token scope；上报 admin |
| 404 | 资源不存在 | 不重试，返回 `ok=false` |
| 409 | 冲突 | 等 5s 重试 1 次 |
| 422 | 校验失败 | 检查 body，不重试 |
| 429 | 限流 | 指数退避重试 1 次 |
| 5xx | 服务端 | 指数退避重试 1 次 |

## 安全

- **不**在日志、回显、输出中明文打印 token：一律脱敏为 `ghp_***xxxx`
- **不**把 token 写到磁盘 / `.env` / 配置文件
- **不**跨员工传递 token，调用方自己从 `security-secrets-guard` 取
- 调用响应若包含 token-like 字符串（误回显），先脱敏再返回
