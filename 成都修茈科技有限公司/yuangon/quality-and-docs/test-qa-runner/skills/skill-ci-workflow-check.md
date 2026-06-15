# ESkill：CI 工作流测试步骤检查（skill-ci-workflow-check）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-ci-workflow-check` |
| 所属员工 | `test-qa-runner` |
| 业务域 | CI 工作流中测试步骤的完整性与正确性检查 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
1. 读取 .github/workflows/ci-*.yml 中的测试步骤
2. 检查是否覆盖以下测试框架：
   - pytest（MODstore 后端 + vibe-coding）
   - vitest（Market 前端单测）
   - playwright（E2E 测试）
   - vue-tsc（TypeScript 类型检查）
3. 检查覆盖率门禁是否在 CI 中启用
4. 检查 CI 中的 Python/Node 版本与项目要求是否一致
5. 生成 CI 测试覆盖报告
→ 输出摘要
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "workflows_checked": [],
  "frameworks_covered": [],
  "frameworks_missing": [],
  "coverage_gate_enabled": true,
  "issues": []
}
```

**约束**：只读取和审查 CI 配置；如需修改，生成 diff 建议并通知 `deploy-release-officer` 执行。

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 框架缺失 | `frameworks_missing.length > 0` |
| 门禁未启用 | `coverage_gate_enabled == false` |
| CI 变更 | `.github/workflows/ci-*.yml` 文件发生变更 |

## 3. 动态阶段

**预算**：4000 tokens，5 步。
**LLM 任务**：生成 CI 配置更新建议 diff → 通知 `deploy-release-officer` 审批并执行更新。

## 4. 固化

**验收标准**：`frameworks_missing.length == 0` 且 `coverage_gate_enabled == true`，CI 测试步骤覆盖全站所有测试框架。
