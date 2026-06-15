# ESkill：流程自动化（skill-workflow-automation）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-workflow-automation` |
| 所属员工 | `workflow-automator` |
| 业务域 | 为员工包创建自动化工作流 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
接收员工包 → 解析能力与需求
→ 调用 attach_nl_workflow_to_employee_pack_dir
→ 生成画布节点与连线 → 附加到员工包目录
→ 输出工作流 ID 与 Skill 数量
```

**输出 schema**：
```json
{ "status": "ok | error", "workflow_id": "", "skill_count": 0, "employee_pack_id": "" }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 工作流创建失败；节点生成失败 |
| 结果不达标 | `skill_count == 0`；工作流 ID 缺失 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：修复节点生成逻辑；补全缺失的连线关系。

## 4. 固化

**验收标准**：工作流 ID 有效，画布节点与连线完整，Skill 数量与员工包声明一致。
