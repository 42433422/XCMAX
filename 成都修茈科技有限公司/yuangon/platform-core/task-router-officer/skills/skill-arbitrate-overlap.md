# skill-arbitrate-overlap

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-arbitrate-overlap` |
| 所属员工 | `task-router-officer` |
| 业务域 | scope 重叠时的仲裁 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：候选员工列表 + task。  
**执行图**：
```
按 README §仲裁规则 1→5 顺序判断
每条规则命中即返回，否则继续下一条
返回 (chosen, reason)
```

**输出**：`{chosen: "<id>", reason: "rule-N: ..."}`。

## 2. 动态触发

- 5 条规则全不命中。
- 命中规则 5 出现 admin 否决（admin 选了不同的人）。

## 3. 动态阶段

预算 1500 token，3 步。LLM 任务：基于 task.summary 与候选员工的 README.domain，给出选择理由。

## 4. 固化

把 admin 在动态阶段的选择沉淀为新增规则（追加到 README §仲裁规则）。
