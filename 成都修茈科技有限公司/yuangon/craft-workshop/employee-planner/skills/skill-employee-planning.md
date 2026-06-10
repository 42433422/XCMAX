# ESkill：员工编排规划（skill-employee-planning）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-employee-planning` |
| 所属员工 | `employee-planner` |
| 业务域 | 员工包架构规划与编排 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取需求分析结果 → 执行 _build_employee_orchestration_plan
→ 拆分员工职责与 Skill 组 → 确定编排顺序与依赖
→ 输出员工蓝图
```

**输出 schema**：
```json
{ "status": "ok | error", "plan_id": "", "employees": [], "workflows": [], "skill_groups": [], "dependencies": [], "warnings": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | _build_employee_orchestration_plan 抛出异常 |
| 结果不达标 | 蓝图中员工列表为空或依赖关系存在环 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：分析需求与已有员工能力 → 补全缺失职责拆分 → 修复依赖环 → 重新生成蓝图。

## 4. 固化

**验收标准**：`status == ok` 且 `employees` 非空且依赖关系无环。
