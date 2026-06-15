# ESkill：Market 前端 vitest 测试执行（skill-vitest-run）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-vitest-run` |
| 所属员工 | `test-qa-runner` |
| 业务域 | Market 前端单元测试执行与覆盖率检查 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
cd MODstore_deploy/market
npx vitest run --coverage
→ 解析输出（passed/failed/skipped）
→ 提取覆盖率数据（statements/branches/functions/lines）
→ 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "tests_passed": 0,
  "tests_failed": 0,
  "tests_skipped": 0,
  "coverage_pct": {
    "statements": 0.0,
    "branches": 0.0,
    "functions": 0.0,
    "lines": 0.0
  },
  "failed_cases": []
}
```

**约束**：不修改 `market/src/**` 源码（仅可修改 `*.test.ts`、`*.spec.ts`、`src/test/**`）。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 测试失败 | `tests_failed > 0` |
| 覆盖率不足 | `coverage_pct.statements < 80`（当前基线 8%，逐步提升） |

## 3. 动态阶段

**预算**：4000 tokens，5 步。
**LLM 任务**：分析失败 case 的错误信息 → 判断是测试 bug 还是前端源码 bug → 若测试 bug 则生成修复 diff（仅限 `*.test.ts`）；若前端 bug 则生成告警并推送给 `market-frontend-dev`。

## 4. 固化

**验收标准**：`tests_failed == 0` 且 `coverage_pct.statements >= 80`。
