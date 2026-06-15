# ESkill：脚本工作流生成（skill-miniapp-build）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-miniapp-build` |
| 所属员工 | `miniapp-builder` |
| 业务域 | 为员工包生成配套脚本工作流 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
接收校验通过的员工包 → 解析自然语言需求
→ 调用 run_script_agent_job → 生成脚本工作流
→ 调用 _commit_script_workflow_from_result → 提交脚本工作流
→ 输出脚本工作流 ID 与内容
```

**输出 schema**：
```json
{ "status": "ok | error", "workflow_id": "", "script_content": "", "employee_pack_id": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 脚本生成失败；提交工作流失败 |
| 结果不达标 | 脚本内容为空；工作流 ID 缺失 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：修复脚本生成逻辑；补全缺失的脚本内容。

## 4. 固化

**验收标准**：脚本工作流 ID 有效，脚本内容完整且可执行，与员工包能力声明一致。
