# GitHub PR 守门员（`github-pr-gatekeeper`）

**area**：`platform-core` · **subzone**：`build-release`
**yuangon 路径**：`成都修茈科技有限公司/yuangon/platform-core/github-pr-gatekeeper/`

## 一句话职责

通用 GitHub PR 审查：Dependabot/Renovate PR 自动审查与合并、CI 状态聚合、低风险自动 approve、major 版本升级派发 `vibe-coding-maintainer` 验证。

## 与 `change-request-auditor` 分工

| 员工 | PR 来源 | 类型 |
|------|---------|------|
| **`github-pr-gatekeeper`（本岗）** | GitHub 原生 PR（Dependabot/Renovate/人工） | 外部 PR |
| `change-request-auditor` | 员工包补丁队列（内部 CR） | 内部 CR |

本岗只做 review/approve/merge/comment，不直接改业务源码；major 升级必须派发 `vibe-coding-maintainer` 做兼容性验证。

## 决策矩阵

| PR 类型 | CI 状态 | 变更范围 | 决策 |
|---------|---------|---------|------|
| Dependabot patch/minor | 通过 | 仅依赖文件 | 自动 approve + merge |
| Dependabot major | 通过 | 仅依赖文件 | 派发 `vibe-coding-maintainer` 验证 |
| Dependabot security | 通过 | 仅依赖文件 | 自动 approve + merge（跳过 major 限制） |
| Dependabot any | 失败 | - | request_changes + 通知 |
| 人工 PR | - | - | 跑 `test-qa-runner` 验证 |

## 上游依赖 (`depends_on`)

- `change-request-auditor`：内部 CR 静态审复用，复杂 PR 升级给本岗时反向协同。
- `test-qa-runner`：人工 PR 必须先跑测试再决定 approve。

## 下游派发

- `vibe-coding-maintainer`：major 升级兼容性验证（不直接合并，等验证结论）。

## Scope（核心文件范围）

- `.github/dependabot.yml`：Dependabot 配置
- `.github/workflows/gitleaks.yml`：密钥扫描 CI
- `.github/workflows/codeql.yml`：代码安全扫描 CI
- `.github/gitleaks-config.toml`：gitleaks 规则
- `MODstore_deploy/modstore_server/auto_fix_loop.py`：自动修复循环（调用本岗的入口之一）
- `MODstore_deploy/modstore_server/telemetry_backlog_loop.py`：telemetry backlog（与 `change-request-auditor` 一起被列入可调用员工）

## 禁区

- `FHD/app/**`、`FHD/frontend/src/**`：宿主业务源码不归本岗。
- `models.py`、`migrations/**`：DB schema 归 `dbops-engineer`。
- `_local_secrets/**`：密钥由 `security-secrets-guard` 管；GitHub Token 也走该岗轮换。

## 关键事实

- **GitHub Token 来源**：`security-secrets-guard` 持有，本岗只读引用，不直接写 `.env`。
- **review/approve/merge 走 GitHub API**（REST v3 或 GraphQL v4），不直接 clone 仓库改代码。
- **major 升级**：必须等 `vibe-coding-maintainer` 验证结论回来才决定是否 merge，不抢跑。
- **security PR**：跳过 major 限制，因为安全补丁必须尽快合入。
- **不直接合并到主干**：本岗只 approve/merge PR，主干合并的最终责任由 `deploy-release-officer` 承担。

## 相关链接

- manifest：`FHD/mods/_employees/github-pr-gatekeeper/manifest.json`
- runbook：[runbook.md](./runbook.md)
- 兄弟岗：`change-request-auditor`（内部 CR）、`vibe-coding-maintainer`（major 验证）

---
*本文件由 admin 在 2026-06-28 录入 yuangon 编制，与 change-request-auditor 分工（外部 PR vs 内部 CR）。*
