# Runbook — 数据库运维工程师

| 字段 | 值 |
|------|----|
| 员工 ID | `dbops-engineer` |
| 负责区域 | `server-and-ops` |
| 最后更新 | 2026-05-08 |
| 应急联系 | admin |

---

## 日常巡检

### 巡检 1：迁移树健康

```bash
cd MODstore_deploy
python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; cfg=Config('alembic.ini'); s=ScriptDirectory.from_config(cfg); heads=s.get_heads(); print('HEADS:', heads); assert len(heads)==1, 'multi-head detected'"
```

**预期**：`HEADS:` 只有 1 个。多 head 说明出现并行迁移分叉，需要 `alembic merge`。

### 巡检 2：models.py 与最新迁移一致

```bash
cd MODstore_deploy
alembic check 2>&1 | tee /tmp/alembic_check.log
```

**预期**：无 "Target database is not up to date" 也无未生成的 diff。若有未生成 diff，需要补一条 revision。

### 巡检 3：慢查询 Top-N

```bash
# 参考；具体连接由 .env 决定
python MODstore_deploy/scripts/db_slow_top.py --since 24h --top 10
```

### 巡检 4：备份完整性

```bash
ls -la MODstore_deploy/var/backups/ | tail -n 14
# 期望：每天至少 1 个 *.sql.gz；每周 1 个 *.full.sql.gz
```

### 巡检 5：连接池水位

```bash
python -c "from modstore_server.db import engine; print(engine.pool.status())"
```

**预期**：checkedout < pool_size * 0.8。

---

## 异常处置

### 异常 1：alembic 多 head

**症状**：`alembic upgrade head` 报 `Multiple head revisions are present`。  
**修复**：
1. `alembic heads` 确认两个 head 编号。
2. `alembic merge -m "merge xx and yy" <head1> <head2>`。
3. 重新 `alembic upgrade head` 在 sandbox 验证。

### 异常 2：models.py 改了字段但未生成迁移

**排查**：巡检 2 报 diff。  
**修复**：
1. `alembic revision --autogenerate -m "add field X to Y"`
2. 手工核对生成的 `op.add_column` / `op.alter_column`，**严格检查 NULL 默认值**。
3. 提交到 change-request 队列，等待 `test-qa-runner` + `change-request-auditor` 通过。

### 异常 3：复制延迟告警

**修复**：
1. 在主从分别 `SHOW SLAVE STATUS\G` / `SELECT pg_last_wal_replay_lsn()`。
2. 若延迟大于 60s，检查最近大事务/批量写。
3. 给 `modstore-backend-api` 反馈："请把批量插入拆成 chunk_size=500"。

### 异常 4：DB 不可达

**升级**：立即 escalate 给 admin 与 `security-secrets-guard`，按 §应急升级路径。

---

## 已知未决工单

| # | 报告日 | 来源 | 现象 | 处置建议 |
|---|--------|------|------|----------|
| DB-001 | 2026-05-08 | onboard_yuangon_employees 输出 | `sync_employee_trigger_bindings` 抛 `no such column: employee_trigger_bindings.priority`，说明 SQLite 中 `employee_trigger_bindings` 表缺 `priority` 列（与 ORM `EmployeeTriggerBinding` 模型不一致）。 | 生成一条 alembic revision：`op.add_column('employee_trigger_bindings', sa.Column('priority', sa.Integer(), nullable=False, server_default='0'))`，sandbox 双向通过后由 deploy-release-officer 在维护窗口执行。 |

## ESkill 动态阶段触发记录

| 日期 | 触发原因 | patch_id | 结果 | 是否固化 |
|------|----------|----------|------|----------|
| — | — | — | — | — |

---

## 应急升级路径

1. 迁移失败 → 立即 `alembic downgrade -1` → 通知 `deploy-release-officer` 暂停发布。
2. 数据丢失风险 → 阻断写入 + 拉取最近备份 → 通知 admin。
3. 凭据/权限异常 → 立即联动 `security-secrets-guard`，旋转账号。
