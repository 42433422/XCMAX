# ESkill：用例质量评审清单（skill-test-case-review-checklist）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-test-case-review-checklist` |
| 所属员工 | `test-qa-runner` |
| 业务域 | 覆盖率达标之外的缺陷发现能力 |
| 版本 | 1.0.0 |

## 1. 使用时机

- 动态阶段（LLM 任务）或人工评审：在合并前审视**新增/变更用例**，不仅看 line coverage。
- 输入：diff、`failed_cases` 历史、`coverage` 报告中的未覆盖分支提示。

## 2. 检查清单（逐项打勾）

| # | 项 | 说明 |
|---|----|------|
| 1 | 边界值 | 空输入、极长字符串、0/负数、边界枚举 |
| 2 | 错误路径 | 401/403/404/422/5xx 或前端等价错误 UI；网络超时 mock |
| 3 | 状态迁移 | 多步流程中非 happy path（取消、重试、并发） |
| 4 | 断言含义 | 断言失败时能指向具体产品行为，而非实现细节琐事 |
| 5 | 与契约一致 | OpenAPI / 类型定义 / 事件 schema 是否在用例中有体现 |
| 6 | Flake 风险 | 固定时钟、随机种子、异步 `waitFor` 是否稳 |

## 3. 输出

- 在 PR 描述或 JSON 摘要中附 `review_gaps: string[]`（仍未覆盖的风险点）。
- 若需补用例：仅在 `scope_globs` 内新增，并引用本清单条目编号。
