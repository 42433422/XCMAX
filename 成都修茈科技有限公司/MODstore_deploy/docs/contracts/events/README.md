# MODstore Event Contracts — JSON Schema 索引

事件统一使用 NeuroBus / Webhook envelope（见仓库根 `docs/service-boundaries-and-events.md`）。本目录为 **payload** 的 JSON Schema（`data` / `payload` 对象），与 Python [`modstore_server/eventing/contracts.py`](../../../modstore_server/eventing/contracts.py) 中的 `EventContract.required_payload` 一一对应。

CI：`tests/test_event_schemas.py` 校验每个契约的 `required_payload` 与对应 `.schema.json` 的 `required` 集合一致。

## Schema 文件

| 事件 `type` | Schema 文件 | 聚合 |
| --- | --- | --- |
| `payment.paid` | [payment.paid.schema.json](./payment.paid.schema.json) | payment_order |
| `wallet.balance_changed` | [wallet.balance_changed.schema.json](./wallet.balance_changed.schema.json) | wallet |
| `refund.approved` | [refund.approved.schema.json](./refund.approved.schema.json) | refund |
| `refund.rejected` | [refund.rejected.schema.json](./refund.rejected.schema.json) | refund |
| `refund.failed` | [refund.failed.schema.json](./refund.failed.schema.json) | refund |
| `employee.execution_completed` | [employee.execution_completed.schema.json](./employee.execution_completed.schema.json) | employee_execution |
| `employee.pack_registered` | [employee.pack_registered.schema.json](./employee.pack_registered.schema.json) | employee_pack |
| `workflow.execution_completed` | [workflow.execution_completed.schema.json](./workflow.execution_completed.schema.json) | workflow_execution |
| `workflow.execution_failed` | [workflow.execution_failed.schema.json](./workflow.execution_failed.schema.json) | workflow_execution |
| `workflow.sandbox_completed` | [workflow.sandbox_completed.schema.json](./workflow.sandbox_completed.schema.json) | workflow_execution |
| `catalog.package_published` | [catalog.package_published.schema.json](./catalog.package_published.schema.json) | catalog_item |
| `llm.quota_consumed` | [llm.quota_consumed.schema.json](./llm.quota_consumed.schema.json) | user_llm_credential |

`payment.order_paid` 为 `payment.paid` 的 legacy alias，不单独建 schema。

## Envelope（参考）

```json
{
  "event_id": "uuid",
  "event_name": "payment.paid",
  "event_version": 1,
  "occurred_at": "2026-04-26T00:00:00Z",
  "producer": "modstore-python",
  "idempotency_key": "payment.paid:MOD123",
  "subject_id": "MOD123",
  "payload": {}
}
```
