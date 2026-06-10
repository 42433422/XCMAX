# ESkill：覆盖率门禁维护（skill-coverage-gate）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-coverage-gate` |
| 所属员工 | `test-qa-runner` |
| 业务域 | 全站覆盖率门禁阈值维护与退化检测 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
1. 读取 MODstore_deploy/tests/test_coverage_gates.py 中的阈值配置
2. 运行各模块覆盖率检查：
   - MODstore 后端：python -m pytest tests/ --cov=modstore_server --cov-report=json -q
   - vibe-coding：python -m pytest tests/ --cov=src/vibe_coding --cov-report=json -q
   - Market 前端：cd market && npx vitest run --coverage
3. 对比当前覆盖率与门禁阈值
4. 生成覆盖率趋势报告
→ 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "modules_checked": 0,
  "modules_passing": 0,
  "modules_failing": 0,
  "details": [
    {
      "module": "modstore_server",
      "current_pct": 0.0,
      "gate_pct": 0.0,
      "pass": true,
      "delta_pct": 0.0
    }
  ]
}
```

**约束**：不修改源码；只能修改 `test_coverage_gates.py` 中的阈值配置（上调需经审批，下调禁止）。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 门禁未通过 | `modules_failing > 0` |
| 覆盖率下降 | 任意模块 `delta_pct < -5` |

## 3. 动态阶段

**预算**：4000 tokens，5 步。
**LLM 任务**：分析覆盖率缺口 → 识别未覆盖的关键模块/函数 → 生成补充测试建议 → 通知对应员工（`modstore-backend-api`、`vibe-coding-maintainer`、`market-frontend-dev`）补充测试。

## 4. 固化

**验收标准**：`modules_failing == 0`，所有模块覆盖率达标且无退化。
