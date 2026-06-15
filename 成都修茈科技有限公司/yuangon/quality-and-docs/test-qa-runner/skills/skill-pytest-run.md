# ESkill：pytest 测试执行（skill-pytest-run）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-pytest-run` |
| 所属员工 | `test-qa-runner` |
| 业务域 | 后端单元/集成测试执行 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
python -m pytest <target_dirs> -q --tb=short
→ 解析输出（passed/failed/error）
→ --cov 覆盖率报告
→ 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "tests_passed": 0,
  "tests_failed": 0,
  "tests_error": 0,
  "coverage_pct": 0.0,
  "failed_cases": []
}
```

**约束**：不修改 `src/**` 源码；只能修改 `tests/**`。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `tests_failed > 0`；`coverage_pct < 80` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。  
**LLM 任务**：分析 traceback → 判断是测试 bug 还是源码 bug → 若测试 bug 则生成修复 diff；若源码 bug 则生成告警并推送给对应员工。

## 4. 固化

**验收标准**：`tests_failed == 0` 且 `coverage_pct >= 80`。
