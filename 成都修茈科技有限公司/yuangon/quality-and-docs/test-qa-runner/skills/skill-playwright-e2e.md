# ESkill：Playwright E2E 测试（skill-playwright-e2e）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-playwright-e2e` |
| 所属员工 | `test-qa-runner` |
| 业务域 | 前端 E2E 端到端测试执行 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
npx playwright test --reporter=html
→ 解析结果（passed/failed/flaky）
→ 提取失败截图路径和错误信息
→ 输出报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "tests_passed": 0,
  "tests_failed": 0,
  "tests_flaky": 0,
  "failed_cases": [{ "name": "", "error": "", "screenshot": "" }]
}
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 结果不达标 | `tests_failed > 0`（排除 flaky 后）|

## 3. 动态阶段

**预算**：4000 tokens，5 步。  
**LLM 任务**：分析截图和错误信息 → 判断前端 bug / 环境问题 → 生成定位报告推送给对应员工。  
**约束**：不修改 `market/src/**`；只生成报告。

## 4. 固化

**验收标准**：`tests_failed == 0`，报告已推送给相关员工。
