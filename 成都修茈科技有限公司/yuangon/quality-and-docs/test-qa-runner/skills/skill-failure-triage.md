# ESkill：测试失败归因 / 范围门禁（skill-failure-triage）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-failure-triage` |
| 所属员工 | `test-qa-runner` |
| 业务域 | 失败责任划分、避免误改被测源码 |
| 版本 | 1.0.0 |

## 1. 静态阶段 — 决策树

**输入**：`failed_cases`（pytest / vitest / playwright JSON）、traceback、可选 `[pytest-env]` / `[playwright-env]` 日志块。

**步骤**：

1. **复现归类**：flake、超时、断言失败、依赖/导入错误、环境配置错误。
2. **责任判定**：
   - 断言与**新接口/新路由/新字段**不一致，且被测代码近期有变更 → 优先怀疑**测试未同步**；仅在 `scope_globs` 内（`tests/**`、`**/*.test.ts`、`**/*.spec.ts`、`market/src/test/**`）修正测试或 mock。
   - 同样情况但契约明确、测试无误 → 生成**源码缺陷/回归**简报，指派 [`MODstore_deploy/docs/routing-table.md`](../../../../MODstore_deploy/docs/routing-table.md) 中的 owner（如 `modstore-backend-api`、`market-frontend-dev`）；**不**修改 `modstore_server/**`、`market/src/**` 非测试文件、`vibe-coding/src/**`。
3. **禁止行为**：为凑绿修改被测源码、静默吞断言、无依据放宽门禁。

**输出 schema**：

```json
{
  "triage_status": "test_fix | app_bug_report | environment | unknown",
  "recommended_scope": "tests_only | escalate_to_owner",
  "owner_employee_suggestion": "modstore-backend-api",
  "evidence": ["≤400 chars snippet or failed_cases id"],
  "notes": ""
}
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 任意框架 `status=fail` | 必须先经过本 skill 决策树再动手改文件 |
| PR 中同时出现 `tests/**` 与 `modstore_server/**` 修改 | 复核是否越权（除非 PR 作者为主 owner） |

## 3. 依赖

- `.cursor/contracts/error-code-map.yaml`（错误码与推荐 owner）
- 本员工 `employee.yaml` 中 `scope_globs` / `forbidden_globs`（运行时校验）
