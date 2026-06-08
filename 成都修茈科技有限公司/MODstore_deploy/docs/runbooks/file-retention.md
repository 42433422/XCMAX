# 档案清理（File Retention）Runbook

档案清理员 `retention-officer`（在岗员工节点图 → `server-and-ops` 区）负责
按 TTL 清理 MODstore 服务器上的过期临时文件，并把每次清理写入员工执行流水，
让员工大会上能直接答出「过期文件谁在管、上次释放多少」。

## 1. 触发方式

| 方式 | 触发器 | 入口 |
|------|--------|------|
| 周期 | APScheduler `retention_janitor_daily`（每天 03:15） | `MODstore_deploy/modstore_server/workflow_scheduler.py` |
| 手动 | CLI | `python -m modstore_server.file_retention_janitor` |
| 员工 | 员工大会 / 浮动管家发问「过期文件谁清理」 | 由 `retention-officer` 直接回答 |

## 2. RETENTION_TARGETS（与代码 `MODstore_deploy/modstore_server/file_retention_janitor.py` 同步）

| 路径 / 模式 | 默认 TTL | 备注 |
|-------------|----------|------|
| `MODstore_deploy/modstore_server/workbench_script_runs/*` | 7 天 | sandbox 单次 run 工作目录。 |
| `MODstore_deploy/modstore_server/market_files/.tmp_chunks/*` | 1 天 | catalog 上传分片合并失败的残留。 |
| `MODstore_deploy/modstore_server/webhook_events/*.json` | 30 天 | webhook 投递事件存档。 |
| `.cursor_*_log.txt`（仓库根） | 14 天 | Cursor agent / smoke 日志。 |
| `coverage/`、`playwright-report/`、`test-results/` 旧批次 | 30 天 | 历史测试产物。 |

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

## 5. 验收

- 连续 7 个工作日 dry-run，没有**可操作** warning（目录不存在、无可删过期文件 → `success`）。
- 切到非 dry-run 后，每次 `EmployeeExecutionMetric.error == ""` 且 `released_bytes >= 0`。
- 员工大会回答「过期文件由谁清理」时，能直接引用最近一次执行流水。
