# Runbook — 需求接入员

| 字段 | 值 |
|------|----|
| 员工 ID | `intake-dispatcher` |
| 负责区域 | `platform-core` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

## 日常巡检

### 巡检 1：待派发队列长度

```bash
# 期望：< 50；持续 > 100 说明 task-router-officer 消费跟不上
sqlite3 MODstore_deploy/var/modstore.db "SELECT COUNT(*) FROM intake_tasks WHERE status='pending';"
```

### 巡检 2：intent=unknown 比例

```bash
sqlite3 MODstore_deploy/var/modstore.db "SELECT intent, COUNT(*) FROM intake_tasks WHERE created_at > datetime('now','-1 day') GROUP BY intent;"
```

### 巡检 3：mianshi/ 候补包是否被监听

```bash
ls -la mianshi/*.xcemp
# 对照 intake_tasks 中 source='candidate_pack' 的最新一条时间戳，差异 > 10 分钟报警
```

## 异常处置

### 异常 1：归一化失败率高（unknown > 30%）
- 升级到动态阶段，让 LLM 给出 `intent` 推断。
- 同步把"无法识别"的样本推给 `doc-knowledge-curator` 完善知识库。

### 异常 2：高风险任务被误判为 low
- 立即升级给 admin。
- 在 `skill-intake-normalize.md` 的"风险词典"追加触发词。

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |
