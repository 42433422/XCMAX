# ESkill：需求意图分析（skill-intent-analysis）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-intent-analysis` |
| 所属员工 | `intent-analyst` |
| 业务域 | 需求意图解析与结构化 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
读取用户输入 → 执行 _canonical_workbench_intent 规范化
→ 关键词匹配（领域/能力） → 可选 LLM 结构化提取
→ 校验用户权限 → 输出结构化需求
```

**输出 schema**：
```json
{ "status": "ok | error", "intent": "", "domain_keywords": [], "suggested_skills": [], "user_permissions": {}, "warnings": [] }
```

## 2. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | _canonical_workbench_intent 抛出异常 |
| 结果不达标 | 意图为空或关键词匹配数为 0 |

## 3. 动态阶段

**预算**：3000 tokens，4 步。
**LLM 任务**：对原始用户输入进行语义理解 → 补全意图与关键词 → 重新结构化输出。

## 4. 固化

**验收标准**：`status == ok` 且 `intent` 非空且 `domain_keywords` 长度 ≥ 1。
