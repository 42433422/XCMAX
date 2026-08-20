# 档案清理（File Retention）Runbook

档案清理员 `retention-officer`（在岗员工节点图 → `server-and-ops` 区）负责
按 TTL 清理 MODstore 服务器上的过期临时文件，并把每次清理写入员工执行流水，
让员工大会上能直接答出「过期文件谁在管、上次释放多少」。

同一个任务也约束高频派生通知，避免健康巡检把 SQLite/PostgreSQL 写满。支付结果、
人工问题等业务通知不属于此清理范围。

## 1. 触发方式

| 方式     | 触发器                                                     | 入口                                                    |
| -------- | ---------------------------------------------------------- | ------------------------------------------------------- |
| 周期     | APScheduler `retention_janitor_daily`（每天 03:15）        | `MODstore_deploy/modstore_server/workflow_scheduler.py` |
| 存储压力 | APScheduler `storage_pressure_self_heal`（默认每 15 分钟） | 达阈值后自动执行受控真清理                              |
| 手动     | CLI                                                        | `python -m modstore_server.file_retention_janitor`      |
| 员工     | 员工大会 / 浮动管家发问「过期文件谁清理」                  | 由 `retention-officer` 直接回答                         |

## 2. RETENTION_TARGETS（与代码 `MODstore_deploy/modstore_server/file_retention_janitor.py` 同步）

| 路径 / 模式                                                  | 默认 TTL | 备注                             |
| ------------------------------------------------------------ | -------- | -------------------------------- |
| `MODstore_deploy/modstore_server/workbench_script_runs/*`    | 7 天     | sandbox 单次 run 工作目录。      |
| `MODstore_deploy/modstore_server/market_files/.tmp_chunks/*` | 1 天     | catalog 上传分片合并失败的残留。 |
| `MODstore_deploy/modstore_server/webhook_events/*.json`      | 30 天    | webhook 投递事件存档。           |
| `.cursor_*_log.txt`（仓库根）                                | 14 天    | Cursor agent / smoke 日志。      |
| `coverage/`、`playwright-report/`、`test-results/` 旧批次    | 30 天    | 历史测试产物。                   |

### 数据库通知保留

| 通知类型                                                      | 默认规则                            | 备注                           |
| ------------------------------------------------------------- | ----------------------------------- | ------------------------------ |
| `system`                                                      | 每用户保留最新 200 条，且最长 30 天 | 健康巡检、系统状态等派生告警。 |
| `employee_execution_done`                                     | 每用户保留最新 200 条，且最长 30 天 | 员工执行完成的派生提醒。       |
| `payment_success` / `payment_failed` / `human_question_asked` | 不清理                              | 业务与人工协同证据。           |

可用 `MODSTORE_NOTIFICATION_SYSTEM_KEEP_PER_USER`、
`MODSTORE_NOTIFICATION_EXECUTION_KEEP_PER_USER`、
`MODSTORE_NOTIFICATION_RETENTION_DAYS` 调整保留量；
`MODSTORE_NOTIFICATION_RETENTION_MAX_DELETE` 限制单次最多删除的行数（默认 100 万）。
调度器默认会真实清理这两类派生通知；设置
`MODSTORE_NOTIFICATION_RETENTION_DRY_RUN=1` 可单独切换为预演，不影响文件目标的
`MODSTORE_RETENTION_DRY_RUN`。

## 3. dry-run / 真删开关

环境变量 `MODSTORE_RETENTION_DRY_RUN`：

- `1` / 未设置：**dry-run**（默认）。只打印将要删除的文件并写一条
  `EmployeeExecutionMetric(status="success", task="janitor.scheduled.dry_run")`。
- `0`：真正执行删除。

首次发布建议保留 dry-run **至少 7 天**，观察 `released_bytes` / `removed_count` 是否合理后再切换。

## 4. 安全护栏

- 任何 `_local_secrets/**`、`.env*`、`**/secrets/**` 路径**禁止删除**；命中时写一条 warning。
- 单次清理上限 5 GB，超过则停止并向 admin 升级（在执行流水中以 `status="warning"` 落库）。
- 删除前先做 `Path.resolve()` 防止符号链接逃逸，确保最终路径仍在仓库目录内。
- 通知删除只允许 `system` 与 `employee_execution_done` 两类，并按用户分别排序保留。
- SQLite 删除行后不会自动缩小文件；需要释放磁盘时，先停写入服务并完成备份，再执行
  `PRAGMA integrity_check`、`VACUUM`，随后复查行数与服务健康。

### 存储压力自愈护栏

- 默认在数据库所在盘可用空间低于 10 GiB，或已用率达到 90% 时触发。
- 自动动作只能调用本文档已声明的文件与派生通知白名单；不执行通用 shell 删除。
- 跨进程锁防止多实例重复清理，默认 60 分钟动作冷却防止失败循环。
- 恢复阈值高于触发阈值（12 GiB / 低于等于 88%），避免在边界上反复报修复。
- 每次观测、策略决定、动作回执和前后磁盘数据都追加到
  `$MODSTORE_RUNTIME_DIR/storage_pressure_self_heal_runs.jsonl`；对外可从
  `/api/scheduler/runtime` 的 `storage_pressure` 字段查询。
- 该 JSONL 是两段滚动账本：单段默认上限 16 MiB，最多保留当前段和 `.1`
  上一段，避免「监测磁盘的日志反而写满磁盘」。
- 只有达到恢复阈值才标记 `recovered`。若仅删除 SQLite 行而磁盘空间未回收，
  状态仍为 `pressure_persists`，同时写入调度失败和 `log.anomaly` incident。
- `MODSTORE_STORAGE_SELF_HEAL_ENABLED=0` 是立即生效的人工 veto 通道。

## 5. 验收

- 连续 7 个工作日 dry-run，没有**可操作** warning（目录不存在、无可删过期文件 → `success`）。
- 切到非 dry-run 后，每次 `EmployeeExecutionMetric.error == ""` 且 `released_bytes >= 0`。
- `database_retention.candidate_count` 与预演一致，`removed_count` 不超过硬上限，
  且支付/人工问题通知行数不变。
- 员工大会回答「过期文件由谁清理」时，能直接引用最近一次执行流水。
- 健康盘上定时任务只写 `healthy_no_action`，不删任何数据。
- 故障注入必须同时覆盖：达阈值动作、冷却幂等、人工 veto、业务通知保护，
  以及「已执行但压力未解除」不得标记成功。
