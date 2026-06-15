# Runbook — 变更评审员

| 字段 | 值 |
|------|----|
| 员工 ID | `change-request-auditor` |
| 负责区域 | `platform-core` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

### 巡检 1：待审队列长度
```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT status, COUNT(*) FROM change_requests GROUP BY status;"
# 期望：pending < 20；escalated < 10
```

### 巡检 2：放行后回滚率
```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT COUNT(*) FROM change_requests WHERE auto_approved=1 AND rolled_back=1 AND created_at > datetime('now','-7 day');"
# 期望：0；> 0 表示 risk-gate 阈值过松
```

### 巡检 3：误升级率
```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT COUNT(*) FROM change_requests WHERE escalated=1 AND admin_decision='approve_low' AND created_at > datetime('now','-7 day');"
```

## 异常处置

### 异常 1：测试基础设施不可用
- pytest / playwright 启动失败 → 立即 escalate 当前 task → 通知 `test-qa-runner` 与 admin。
- 不能"跳过测试就放行"。

### 异常 2：连续 ≥ 3 个 low 被回滚
- 立即把 risk-gate 阈值收紧（行数 / 覆盖率下降）。
- 在 `skill-risk-gate.md` 追加规则。

### 异常 3：评审超时（> 30min）
- 检查 test-qa-runner 队列；若拥堵则升级。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
