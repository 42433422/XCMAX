# 任务派发员（`task-router-officer`）

## 一句话职责

读取 `intake_tasks(status='pending')`，按 `files_hint` 命中 `scope_globs` 选定执行员工；命中多人时按仲裁规则裁决；无人匹配则升级到 admin。

## 路由表来源

- 全量 `yuangon/**/employee.yaml` 中的 `scope_globs` 与 `forbidden_globs`。
- 每日 03:00 由 `MODstore_deploy/modstore_server/scripts/build_routing_table.py` 生成 `MODstore_deploy/docs/routing-table.md`（人可读 + 机器可解析）。

## 仲裁规则（命中 ≥ 2 人时）

按优先级降序，命中即停止：

1. **专属优先**：路径同时被一人 `scope_globs` 命中、被另一人 `forbidden_globs` 命中 → 选第一人。
2. **更具体的 glob 优先**：`workbench/**` vs `**/*.vue`，前者更长更具体。
3. **意图匹配优先**：task.intent 与员工 area 的偏好表（dba→server-and-ops/dbops-engineer，doc→quality-and-docs/doc-knowledge-curator 等）。
4. **风险等级 vs handlers**：high 风险只派给 `handlers` 含 `agent` 且 `escalate_to_human=true` 的员工。
5. **以上全部并列** → 选 `version` 最新的；仍并列 → 升级 admin 二选一。

## 输出

- 写一行 `dispatch_log(task_id, candidate_employees=[...], chosen=..., reason=...)`。
- emit `employee.task.assigned:<chosen>`，被派员工通过 `triggers.subscribes` 接住。

## 典型任务

1. task `{intent:dba, files_hint:[migrations/...]}` → 命中 `dbops-engineer.scope_globs` → 派发。
2. task `{intent:bugfix, files_hint:[market/src/views/AdminDutyEmployeesView.vue]}` → 命中 `workbench-ux-stylist`（已扩展覆盖 Admin*View.vue） → 派发。
3. task `{intent:onboarding, files_hint:[mianshi/foo.xcemp]}` → 命中 `employee-pack-quality-interviewer` + `employee-interview-assistant` → 仲裁规则 1+3 选 `employee-interview-assistant` 先做信息访谈。

## KPI

| 指标 | 目标 |
|------|------|
| 命中率（非 unknown 任务有员工承接） | ≥ 95% |
| 多命中仲裁正确率（admin 抽查） | ≥ 90% |
| 派发延迟 | < 10s |
| 误派发率（接收员工拒收 / 命中 forbidden） | 0 |

## 禁区

- 不直接改员工包代码（这是 `employee-pack-curator` 的职责）。
- 不直接改业务源码（前后端、payment 等）。
- 不动 schema（dbops-engineer 的事）。

## 协作关系

- 上游：`intake-dispatcher`。
- 下游：所有业务员工（通过 `employee.task.assigned:*` 事件）。
- 路由表更新依赖：`employee-pack-curator`（员工 scope 改动）+ `push-update-context-officer`（yuangon resync 后通知重建路由表）。
