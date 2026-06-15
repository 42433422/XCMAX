# skill-route-task

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-route-task` |
| 所属员工 | `task-router-officer` |
| 业务域 | task → employee 路由 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**输入**：`intake_tasks` 中一行 pending task。  
**执行图**：
```
1. 加载 routing-table.md（缓存 5 分钟）
2. 对每条 files_hint 路径：
   - 命中员工 A.scope_globs ∧ 不命中 A.forbidden_globs → 候选
3. 候选 ≤ 1 → 直接派发
   候选 ≥ 2 → 调 skill-arbitrate-overlap
   候选 = 0 → 按 task.intent 走 INTENT_TO_AREA 兜底；仍空 → 升级 admin
4. 写 dispatch_log + emit employee.task.assigned:<chosen>
```

## 2. INTENT_TO_AREA 兜底表

| intent | 兜底员工 |
|--------|----------|
| bugfix | daily-orchestrator |
| feature | modstore-backend-api（后端类）/ market-frontend-dev（前端类） |
| doc | doc-knowledge-curator |
| ops | deploy-release-officer |
| dba | dbops-engineer |
| onboarding | employee-interview-assistant |
| qa | test-qa-runner |
| unknown | admin（升级） |

## 3. 动态触发

- 路由表加载失败 / glob 解析异常。
- 同一 task 被同一员工拒收 ≥ 2 次。

## 4. 固化

把命中规则的 hit_count 写到 `routing-table.md` 注释里，让 admin 看到热点路径。

## 5. 评估指标

见 README KPI。
