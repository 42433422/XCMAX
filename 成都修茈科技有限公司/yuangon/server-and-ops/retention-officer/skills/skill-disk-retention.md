# ESkill：磁盘档案保留与清理（skill-disk-retention）

## 元信息

| 字段 | 值 |
|------|----|
| skill_id | `skill-disk-retention` |
| 所属员工 | `retention-officer` |
| 业务域 | 磁盘档案保留与定时清理 |
| 版本 | 1.0.0 |

## 1. 静态阶段

**执行逻辑**：
```
按 RETENTION_TARGETS 列表 → 计算每个目录的 TTL
→ 列出 mtime 早于 cutoff 的文件 / 子目录
→ dry-run（默认）只预览；非 dry-run 时执行 rm -rf
→ 写一行 EmployeeExecutionMetric (employee_id="retention-officer", task="janitor.scheduled")
```

**输出 schema**：
```json
{
  "status": "ok | warning | error",
  "dry_run": true,
  "removed_count": 0,
  "released_bytes": 0,
  "scanned_targets": [
    {"path": "...", "ttl_days": 7, "kept": 0, "removed": 0, "skipped": 0}
  ],
  "warnings": [],
  "report_md": "..."
}
```

## 2. RETENTION_TARGETS（默认 TTL 表）

| 目录 / 模式 | TTL（天） | 说明 |
|-------------|-----------|------|
| `MODstore_deploy/modstore_server/workbench_script_runs/*` | 7 | sandbox 单次 run 临时目录，保留近 7 日便于排错。 |
| `MODstore_deploy/modstore_server/market_files/.tmp_chunks/*` | 1 | catalog 上传分片合并失败的残留。 |
| `MODstore_deploy/modstore_server/webhook_events/*.json` | 30 | webhook 投递事件存档。 |
| `.cursor_*_log.txt` | 14 | Cursor agent / smoke 日志。 |
| `coverage/`, `playwright-report/`, `test-results/` | 30 | 历史测试产物（保留最近 1 个月对账）。 |

## 3. 动态触发条件

| 触发类型 | 规则 |
|----------|------|
| 执行报错 | 目录无权限 / 设备空间不足 |
| 结果不达标 | 单次释放 0 字节但目标目录中存在过期文件 |

## 4. 动态阶段

**预算**：1500 tokens，3 步。  
**约束**：
- 任何 `.env`、`_local_secrets/**`、`**/secrets/**` 路径**禁止删除**；命中时写 warning。
- 默认 `MODSTORE_RETENTION_DRY_RUN=1`；首发 7 天观察期内只输出报告。
- 单次清理上限 5GB，超过则停止并向 admin 升级。

**LLM 任务**：
- 把 `scanned_targets` 与 warnings 翻译成「老板看得懂」的中文 Markdown 概述（释放空间、删了多少文件、有无异常）。

## 5. 固化

**验收标准**：
- 连续 7 个工作日 dry-run 没有 warning。
- 切到非 dry-run 后，每次执行流水中 `released_bytes >= 0` 且 `error=""`。
- `EmployeeExecutionMetric` 中 `task="janitor.scheduled"` 的最近一条 `status="success"`。
