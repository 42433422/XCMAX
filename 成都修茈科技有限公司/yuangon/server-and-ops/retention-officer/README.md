# 档案清理员（retention-officer）

## 一句话职责

按 TTL 清理 MODstore 服务器上的过期临时文件（workbench 沙箱、上传分片、日志、覆盖率产物等），并把每次清理结果写回员工执行流水，让员工大会能直接答出「过期文件谁在管」。

## 负责文件

| 类型 | 路径 | 默认 TTL |
|------|------|----------|
| 沙箱 run 工作目录 | `MODstore_deploy/modstore_server/workbench_script_runs/*` | 7 天 |
| catalog 上传分片残留 | `MODstore_deploy/modstore_server/market_files/.tmp_chunks/*` | 1 天 |
| webhook 投递事件存档 | `MODstore_deploy/modstore_server/webhook_events/*.json` | 30 天 |
| Cursor / smoke 日志 | `.cursor_*_log.txt` | 14 天 |
| 历史测试产物 | `coverage/`、`playwright-report/`、`test-results/` | 30 天 |
| Cursor 临时 xcemp 缓存 | `__tmp_xcemp/`、`__tmp_emp_*.json` | 7 天 |
| Nginx 解压副本 | `_nginx_extract/` | 90 天（仅作归档参考） |
| 历史落地稿 | `new/`、`site/`、`dist/` | 90 天（提交前先归档到 `legacy-archive.md`） |
| 支付 SDK 解压副本 | `alipay_package/` | 90 天 |
| 冻结子项目 | `taiyangniao-pro/` | 不清理，仅生成归档说明（如需复活由 admin 指派维护员） |
| 自身 runbook | `MODstore_deploy/docs/runbooks/file-retention.md` | — |
| 历史归档说明 | `MODstore_deploy/docs/runbooks/legacy-archive.md` | — |

## 典型任务

1. 周期触发（每日 03:15）扫描 RETENTION_TARGETS，列出过期文件并按 TTL 删除。
2. 每次清理后写一行 `EmployeeExecutionMetric(employee_id="retention-officer", task="janitor.scheduled")`，附 `released_bytes / removed_count / scanned_targets`。
3. 在员工大会上回答「过期文件由谁清理 / 多久清一次 / 上次释放多少 GB」。
4. 维护 `docs/runbooks/file-retention.md` 与代码 `RETENTION_TARGETS` 的一致性。

## KPI

| 指标 | 目标 |
|------|------|
| 周累计释放空间 | ≥ 1 GB（基线，看仓库实际增长率） |
| 误删（命中禁区或活跃文件） | 0 |
| 每日 cron 按时执行率 | ≥ 95% |

## 禁区

- `_local_secrets/**`、`.env*`、`**/secrets/**` 一律不动。
- 任何 `.py` / `.vue` / `.ts` 源码：只读不删。
- 数据库文件、`packages.json`、`REGISTRY.json` 等持久化数据：不在清理范围内。

## 协作关系

- 接收 `log-monitor-incident` 提供的磁盘告警作为额外触发。
- 文档 `docs/runbooks/file-retention.md` 由本员工与 `doc-knowledge-curator` 共同维护，正文以本员工为准。
- 任何新目录加入清理范围前，需在员工大会上 propose 并获得 admin 确认。
