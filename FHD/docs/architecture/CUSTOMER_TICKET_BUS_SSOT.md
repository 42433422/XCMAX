# 客服工单总线 SSOT

> 更新日期：2026-10-09

## 定轨

客服工单闭环的执行总线是 **MODstore `incident_bus` + incident team**，不是 FHD NeuroBus。

| 环节 | 位置 |
|------|------|
| 发布 | `modstore_server/customer_service_api.py` → `ops.intake.customer_ticket`（publish 前 enrich） |
| 编排 | `incident_team_orchestrator`（scout/fix/verify）+ binding 派发 |
| 入口员工 | `intake-dispatcher` 产出 `routing_plan`；`incident_bus` 消费并派发 `proposed_owner` |
| 回写 | `apply_customer_ticket_incident_progress` → 用户可见 lifecycle |
| 客户决定 | 桌面 `POST /api/mod-store/issue-runtime/{id}/decision` → `POST /api/customer-service/issues/{id}/decision`：「已解决」才关单，「重新打开」回到处理中并重新投递 |

## 非 SSOT

- FHD `duty_employee_work_contracts.json` 中的 `ops.intake.customer_ticket` 描述的是 **duty 用工合同**，由 `sync_employee_triggers` 落到 incident binding，**不**表示 NeuroBus `bus.subscribe`。
- 客来来 `xcmax_integration` 仅为本机 HTTP 配对只读网关，工单不进 NeuroBus。

## 验收

一张 `CS*` 工单：`dispatched_count > 0`，`_cs_progress.lifecycle_*` 非空，且非全员 `handler_failed`。真实闭环按 [ticket-loop.run.json](../evidence/e2e/final-acceptance-1.0.0.5/ticket-loop.run.json) 53 项与 [gates.json](../evidence/e2e/final-acceptance-1.0.0.5/gates.json) 闸门 17–23 判定；目前只有本机集成证据 [ticket-loop-local-20261006](../evidence/e2e/ticket-loop-local-20261006/run.jsonl)，未闭环。

同账号、同 source_ref/WO、同需求正文的跨版本支持补报追加到 `support_reports`，保留原附件、上下文及历史 outbox；新增同单事件携带本次支持包。重复补报幂等，不同正文或账号不得覆盖原案；闭单新补报须先由客户正常重开。
