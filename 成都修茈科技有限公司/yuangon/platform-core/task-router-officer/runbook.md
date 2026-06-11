# Runbook — 任务派发员

| 字段 | 值 |
|------|----|
| 员工 ID | `task-router-officer` |
| 负责区域 | `platform-core` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

### 巡检 1：路由表新鲜度
```bash
ls -l MODstore_deploy/docs/routing-table.md
# mtime 在 24h 内为新鲜
```

### 巡检 2：未命中堆积
```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT COUNT(*) FROM dispatch_log WHERE chosen IS NULL AND created_at > datetime('now','-1 day');"
```

### 巡检 3：误派发回收
```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT chosen, COUNT(*) FROM dispatch_log WHERE outcome='rejected' AND created_at > datetime('now','-1 day') GROUP BY chosen;"
```

## 异常处置

### 异常 1：路由表过期
- 立即 `python -m modstore_server.scripts.build_routing_table` 重建。
- 通知 `push-update-context-officer` 检查 yuangon-resync 流水线。

### 异常 2：派发后被员工拒收
- 读取 `dispatch_log.reason` 与员工反馈，更新 `skill-arbitrate-overlap.md` 的仲裁规则。

### 异常 3：高风险任务被派给低权限员工
- 立即 escalate admin。
- 在 `skill-route-task.md` 的"风险通道"加规则。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
