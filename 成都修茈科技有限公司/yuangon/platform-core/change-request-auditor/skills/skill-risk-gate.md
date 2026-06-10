# skill-risk-gate

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-risk-gate` |
| 所属员工 | `change-request-auditor` |
| 业务域 | 风险打分 → 放行/升级 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：`audit_report.json` + `test_report.json`（来自 test-qa-runner）。  
**执行图**：
```
risk = 0
+ 行数 > 500 → +0.4； > 100 → +0.1
+ 文件数 > 15 → +0.3
+ violations.secret/sql_hazard 任一 → +1.0（强制 high）
+ 测试失败 → +1.0（强制 high）
+ 覆盖率下降 > 2% → +0.4； > 0.5% → +0.1
+ 触碰 forbidden_globs → +0.5
clamp 0..1.5

low: < 0.2  → auto-approve
medium: 0.2..0.5  → auto-approve + tag "needs_admin_review"
high: ≥ 0.5  → escalate
```

## 2. 动态触发

- 同一员工同周内 low 被回滚 ≥ 2 次 → 该员工本周内强制 medium 起步。

## 3. 动态阶段

预算 2000 token，3 步。LLM 任务：在 medium 边界（0.4..0.5）做一次"看起来像 high 吗？"复核，理由写入 review.md。

## 4. 固化

每月把 admin 否决最多的规则反向调阈值，更新 risk_gate_thresholds.json。
