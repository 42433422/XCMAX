# 客服工单总线 SSOT

> 更新日期：2026-07-24

## 定轨

客服工单闭环的执行总线是 **MODstore `incident_bus` + incident team**，不是 FHD NeuroBus。

| 环节 | 位置 |
|------|------|
| 发布 | `modstore_server/customer_service_api.py` → `ops.intake.customer_ticket`（publish 前 enrich） |
| 编排 | `incident_team_orchestrator`（scout/fix/verify）+ binding 派发 |
| 入口员工 | `intake-dispatcher` 产出 `routing_plan`；`incident_bus` 消费并派发 `proposed_owner` |
| 回写 | `apply_customer_ticket_incident_progress` → 用户可见 lifecycle |

## 非 SSOT

- FHD `duty_employee_work_contracts.json` 中的 `ops.intake.customer_ticket` 描述的是 **duty 用工合同**，由 `sync_employee_triggers` 落到 incident binding，**不**表示 NeuroBus `bus.subscribe`。
- 客来来 `xcmax_integration` 仅为本机 HTTP 配对只读网关，工单不进 NeuroBus。

## 验收

一张 `CS*` 工单：`dispatched_count > 0`，`_cs_progress.lifecycle_*` 非空，且非全员 `handler_failed`。
