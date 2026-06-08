# yuangon 自动化总开关 Runbook

> 版本：1.0.0 · 更新：2026-05-08  
> 目标：把"全覆盖、全流程、全自动"从设计稿变成跑起来的状态。本 runbook 列出**全部需要打开的开关**与一个一次性 bootstrap 命令清单。

## 一、自动化清单（务必按顺序跑一次）

```bash
# 0. 进入仓库根
cd /path/to/成都修茈科技有限公司

# 1. 安装 git hooks（pre-push 校验 + post-commit 触发回流）
bash scripts/install_git_hooks.sh
# Windows: powershell -File scripts/install_git_hooks.ps1

# 2. 首次构建路由表（之后由 task-router-officer 接管自动重建）
MODstore_deploy/.venv/Scripts/python.exe MODstore_deploy/scripts/build_routing_table.py

# 3. 首次扫一遍 mianshi/ 候补包（之后 cron 每 5 分钟自动跑）
MODstore_deploy/.venv/Scripts/python.exe MODstore_deploy/scripts/intake_watcher.py

# 4. 重新 onboard 全量员工（让数据库与 yuangon 完全一致）
cd MODstore_deploy
.venv/Scripts/python.exe -m modstore_server.scripts.onboard_yuangon_employees --force
cd ..
```

## 二、APScheduler / Cron 计划表

由 `triggers.schedule.cron` 在每个 employee.yaml 中声明，由 MODstore 内置的 APScheduler 在启动时自动注册：

| 时间 | 员工 | 动作 |
|------|------|------|
| 02:00 / 5min | `intake-dispatcher` | 扫 `mianshi/` 候补包 + 检查队列 |
| 02:30 | `push-update-context-officer` | yuangon → onboard 兜底回流 |
| 03:00 | `task-router-officer` | 重建路由表 |
| 03:15 | `retention-officer` | 清扫过期临时文件 |
| 03:30 | `daily-orchestrator` | 跑测试 + 自动修复 + 提交评审 |

启动方式：MODstore 主进程启动时由 `modstore_server/scheduling/aps.py` 读取所有 manifest 的 `triggers.schedule` 字段并注册。

## 三、事件总线打开校验

```bash
tail -n 5 MODstore_deploy/modstore_server/data/event_outbox.jsonl
```
正常应该看到形如 `{"event_name":"yuangon.def.changed",...}`、`{"event_name":"ops.intake.candidate_pack",...}` 的记录。  
对应的订阅由 `triggers.subscribes` 在 onboard 时写入 `employee_trigger_bindings` 表（见已知未决项 DB-001）。

## 四、健康检查（每周）

```bash
# 1. 全量 yaml 仍可校验
MODstore_deploy/.venv/Scripts/python.exe -m modstore_server.scripts.onboard_yuangon_employees --dry-run

# 2. 路由表新鲜度
MODstore_deploy/.venv/Scripts/python.exe MODstore_deploy/scripts/build_routing_table.py --check

# 3. 资产覆盖度（任何未覆盖路径会列出来）
MODstore_deploy/.venv/Scripts/python.exe MODstore_deploy/scripts/coverage_audit.py
```

`coverage_audit.py` 见 §五。

## 五、coverage_audit.py（覆盖度审计）

详见 [`MODstore_deploy/scripts/coverage_audit.py`](../../scripts/coverage_audit.py)；它读取 `yuangon/_shared/OWNERSHIP.md` 中的显式忽略表 + 各员工 `scope_globs`，扫描仓库，输出**仍未覆盖**的文件清单（应为空或全部命中显式忽略规则）。

## 六、回滚与停机

- **暂时停掉自动化**：删除 `.git/hooks/pre-push` 与 `.git/hooks/post-commit`；并在 admin 控制台暂停 APScheduler。
- **回滚某次 yuangon 改动**：`git revert <sha>` 后 `yuangon_resync.py --apply` 会自动把数据库改回旧版本。
- **路由表错误派发**：人工把 `MODstore_deploy/modstore_server/data/routing_table.json` 改回上一个版本（git 里有快照），然后 `task-router-officer` 重启后会自动重建。

## 七、变更记录

| 日期 | 变更 | 操作人 |
|------|------|--------|
| 2026-05-08 | 初版：上线 5 个 cron + git hook + 3 个脚手架 | admin |
