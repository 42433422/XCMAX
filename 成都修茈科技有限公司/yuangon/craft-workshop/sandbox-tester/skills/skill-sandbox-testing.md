# ESkill：沙箱测试（skill-sandbox-testing）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-sandbox-testing` |
| 所属员工 | `sandbox-tester` |
| 业务域 | 员工工作流沙箱测试 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
run_workflow_sandbox(workflow_id, mode="validate_only")
→ 结构校验结果
→ run_workflow_sandbox(workflow_id, mode="mock")
→ Mock 执行结果
→ 真实员工调用验证
→ 输出测试报告
```

**输出 schema**：
```json
{
  "status": "ok | fail",
  "workflow_id": "",
  "structure_validation": { "status": "", "errors": [] },
  "mock_execution": { "status": "", "phases_run": 0, "errors": [] },
  "employee_reachability": { "status": "", "unreachable": [] },
  "summary": ""
}
```

**工具绑定**：
- run_workflow_sandbox

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | run_workflow_sandbox 抛出异常 |
| 结果不达标 | structure_validation.status == "fail" 或 mock_execution.status == "fail" |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析校验/执行失败原因 → 判断是 manifest 缺陷还是环境问题 → 生成修复建议或重新构造 Mock 参数。

**允许改动的模块白名单**：
- workbench/sandbox/* 配置文件

## 4. 固化

**验收标准**：
- [ ] structure_validation.status == "ok"
- [ ] mock_execution.status == "ok"
- [ ] employee_reachability.status == "ok"
