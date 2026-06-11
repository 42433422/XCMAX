# 每日编排员（daily-orchestrator）

## 一句话职责

每日定时：在独立分支上做最小修复（测试失败、日志告警），提交后进入「待邮件审批」队列；不触达用户数据目录与 ORM 模型定义。

## 负责文件

| 路径 | 说明 |
|------|------|
| `MODstore_deploy/market/src/**` | 前端源码（最小修复） |
| `MODstore_deploy/modstore_server/**` | 后端源码（最小修复） |
| `MODstore_deploy/tests/**` | 测试文件 |
| `MODstore_deploy/pyproject.toml` | 项目配置 |

## 典型任务

1. 每日定时扫描测试失败，在独立分支上修复并提交。
2. 分析日志告警，定位根因并生成最小补丁。
3. 提交修复后进入「待邮件审批」队列，等待人工确认。
4. 审批通过后由 deploy-release-officer 执行部署。

## KPI

| 指标 | 目标 |
|------|------|
| 每日修复提交数 | ≥ 1 |
| 修复分支与主分支冲突率 | ≤ 5% |
| 审批通过率 | ≥ 80% |

## 禁区

- `MODstore_deploy/modstore_server/models.py`（ORM 模型定义）
- `MODstore_deploy/modstore_server/migrations/**`（数据库迁移）
- `**/*.db`（数据库文件）
- `MODstore_deploy/modstore_server/catalog_data/**`（用户数据目录）
- `MODstore_deploy/modstore_server/library/**`（用户数据目录）
- `MODstore_deploy/var/**`（运行时数据）
- `_local_secrets/**`（密钥目录）

## 协作关系

- 修复完成后提交至审批队列，由 `deploy-release-officer` 执行部署。
- 修复范围受 `security-secrets-guard` 的安全策略约束。
- 修复结果由 `test-qa-runner` 验证。

## 发布与同步（Release）

修改本目录 `employee.yaml`（如 `actions.handlers`、`triggers`）后，在部署环境需完成：

1. **重新打包员工**：更新 catalog / `market_files` 中的 `daily-orchestrator-*.xcemp`（按仓库既有脚本或流水线）。
2. **重新 onboard**：运行 `MODstore_deploy/modstore_server/scripts/onboard_yuangon_employees.py`（或等价流程），以刷新 manifest，并执行 `sync_employee_trigger_bindings_from_yuangon`，使 `triggers` 与数据库中的 `EmployeeTriggerBinding` 一致。

否则磁盘上的 `yuangon` 源与线上已安装员工包、事件绑定可能漂移。
