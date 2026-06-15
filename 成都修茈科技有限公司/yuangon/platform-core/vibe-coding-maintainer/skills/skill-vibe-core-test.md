# ESkill：核心库测试与修复（skill-vibe-core-test）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-vibe-core-test` |
| 所属员工 | `vibe-coding-maintainer` |
| 业务域 | vibe-coding 核心库质量维护 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
py_compile 全部核心模块 → python -m pytest tests/ -q
→ --cov 覆盖率检查 → 输出报告
```

**输出 schema**：
```json
{ "status": "ok | error", "tests_passed": 0, "tests_failed": 0, "coverage_pct": 0.0, "syntax_errors": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | SyntaxError；ImportError |
| 结果不达标 | `tests_failed > 0` 或 `coverage_pct < 85` |

## 3. 动态阶段

**预算**：5000 tokens，6 步。  
**LLM 任务**：分析失败 test traceback → 生成最小修复 diff → 补充缺失测试 case。

## 4. 固化

**验收标准**：`tests_failed == 0` 且 `coverage_pct ≥ 85`，且接口签名无 break。
