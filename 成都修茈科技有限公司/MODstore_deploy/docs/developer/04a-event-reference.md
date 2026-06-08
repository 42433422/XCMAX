# 事件参考

> 本页由 `scripts/generate_event_reference.py` 从 `modstore_server/eventing/contracts.py` 自动生成。在 `contracts.py` 增/改事件后，请重新运行脚本而不是手工编辑此文件。

MODstore 的所有出站事件（业务 webhook、订阅）共用同一份 envelope 与同一份名称表：

```json
{
  "id": "<事件唯一 id>",
  "type": "<事件名，见下表>",
  "version": <事件版本，整数>,
  "source": "modstore-python | modstore-java | modstore-employee-api | ...",
  "aggregate_id": "<聚合 id，例如订单号 / 工作流 id>",
  "created_at": <unix 秒>,
  "data": { ... }
}
```

HTTP 头同时包含 `X-Modstore-Webhook-Signature: sha256=<hex>`，签名规则：

```
HMAC-SHA256(secret, timestamp + '.' + event_id + '.' + body)
```

## 事件清单

| Event | Version | Aggregate | 必填字段 | 说明 |
| --- | --- | --- | --- | --- |
| `catalog.item_published` | 1 | catalog_item | `item_id`, `author_id`, `name`, `artifact` | A catalog item was published or made publicly available in the store. |
| `catalog.package_published` | 1 | catalog_item | `pkg_id`, `author_id`, `version`, `artifact`, `name` | A catalog package (e.g. employee_pack) was published to the store. |
| `employee.execution_completed` | 1 | employee_execution | `employee_id`, `user_id`, `task`, `status` | An AI employee task finished (status=success/failure). |
| `employee.pack_registered` | 1 | employee_pack | `pack_id`, `author_id`, `mod_id`, `version` | An employee pack was registered from a workflow manifest. |
| `invoice.created` | 1 | invoice | `invoice_id`, `user_id`, `order_no`, `amount` | An invoice was created for a completed payment order. |
| `llm.quota_consumed` | 1 | user_llm_credential | `user_id`, `provider`, `model`, `tokens`, `cost` | LLM quota was consumed for a user request. |
| `payment.paid` | 1 | payment_order | `out_trade_no`, `user_id`, `subject`, `total_amount`, `order_kind` | A payment order has been successfully paid and fulfilled. |
| `refund.approved` | 1 | refund | `refund_id`, `order_no`, `user_id`, `amount`, `status` | A refund request was approved and successfully refunded. |
| `refund.failed` | 1 | refund | `refund_id`, `order_no`, `user_id`, `amount`, `status` | A refund request was approved but downstream refund execution failed. |
| `refund.rejected` | 1 | refund | `refund_id`, `order_no`, `user_id`, `amount`, `status` | A refund request was rejected by an administrator. |
| `subscription.renewal_failed` | 1 | user_plan | `user_id`, `plan_id`, `reason` | A subscription auto-renewal failed (e.g. insufficient wallet balance). |
| `subscription.renewed` | 1 | user_plan | `user_id`, `plan_id`, `out_trade_no`, `amount`, `expires_at` | A subscription plan was automatically renewed and payment deducted from wallet. |
| `wallet.balance_changed` | 1 | wallet | `user_id`, `amount`, `source_order_id`, `transaction_type` | A user's wallet balance changed because of recharge, payment, or refund. |
| `workflow.event_trigger` | 1 | workflow | `workflow_id`, `user_id` | Request asynchronous workflow execution driven by a domain event. |
| `workflow.execution_completed` | 1 | workflow_execution | `workflow_id`, `execution_id`, `user_id`, `status` | A workflow execution finished successfully. |
| `workflow.execution_failed` | 1 | workflow_execution | `workflow_id`, `execution_id`, `user_id`, `status` | A workflow execution ran but failed at runtime. |
| `workflow.sandbox_completed` | 1 | workflow_execution | `workflow_id`, `user_id`, `status`, `duration_ms` | A workflow sandbox run finished (success or failure). |

## 详细说明

### `catalog.item_published` (v1)

A catalog item was published or made publicly available in the store.

- Aggregate: `catalog_item`
- 必填 `data` 字段：
  - `item_id`
  - `author_id`
  - `name`
  - `artifact`

### `catalog.package_published` (v1)

A catalog package (e.g. employee_pack) was published to the store.

- Aggregate: `catalog_item`
- 必填 `data` 字段：
  - `pkg_id`
  - `author_id`
  - `version`
  - `artifact`
  - `name`

### `employee.execution_completed` (v1)

An AI employee task finished (status=success/failure).

- Aggregate: `employee_execution`
- 必填 `data` 字段：
  - `employee_id`
  - `user_id`
  - `task`
  - `status`

### `employee.pack_registered` (v1)

An employee pack was registered from a workflow manifest.

- Aggregate: `employee_pack`
- 必填 `data` 字段：
  - `pack_id`
  - `author_id`
  - `mod_id`
  - `version`

### `invoice.created` (v1)

An invoice was created for a completed payment order.

- Aggregate: `invoice`
- 必填 `data` 字段：
  - `invoice_id`
  - `user_id`
  - `order_no`
  - `amount`

### `llm.quota_consumed` (v1)

LLM quota was consumed for a user request.

- Aggregate: `user_llm_credential`
- 必填 `data` 字段：
  - `user_id`
  - `provider`
  - `model`
  - `tokens`
  - `cost`

### `payment.paid` (v1)

A payment order has been successfully paid and fulfilled.

- Aggregate: `payment_order`
- 必填 `data` 字段：
  - `out_trade_no`
  - `user_id`
  - `subject`
  - `total_amount`
  - `order_kind`

### `refund.approved` (v1)

A refund request was approved and successfully refunded.

- Aggregate: `refund`
- 必填 `data` 字段：
  - `refund_id`
  - `order_no`
  - `user_id`
  - `amount`
  - `status`

### `refund.failed` (v1)

A refund request was approved but downstream refund execution failed.

- Aggregate: `refund`
- 必填 `data` 字段：
  - `refund_id`
  - `order_no`
  - `user_id`
  - `amount`
  - `status`

### `refund.rejected` (v1)

A refund request was rejected by an administrator.

- Aggregate: `refund`
- 必填 `data` 字段：
  - `refund_id`
  - `order_no`
  - `user_id`
  - `amount`
  - `status`

### `subscription.renewal_failed` (v1)

A subscription auto-renewal failed (e.g. insufficient wallet balance).

- Aggregate: `user_plan`
- 必填 `data` 字段：
  - `user_id`
  - `plan_id`
  - `reason`

### `subscription.renewed` (v1)

A subscription plan was automatically renewed and payment deducted from wallet.

- Aggregate: `user_plan`
- 必填 `data` 字段：
  - `user_id`
  - `plan_id`
  - `out_trade_no`
  - `amount`
  - `expires_at`

### `wallet.balance_changed` (v1)

A user's wallet balance changed because of recharge, payment, or refund.

- Aggregate: `wallet`
- 必填 `data` 字段：
  - `user_id`
  - `amount`
  - `source_order_id`
  - `transaction_type`

### `workflow.event_trigger` (v1)

Request asynchronous workflow execution driven by a domain event.

- Aggregate: `workflow`
- 必填 `data` 字段：
  - `workflow_id`
  - `user_id`

### `workflow.execution_completed` (v1)

A workflow execution finished successfully.

- Aggregate: `workflow_execution`
- 必填 `data` 字段：
  - `workflow_id`
  - `execution_id`
  - `user_id`
  - `status`

### `workflow.execution_failed` (v1)

A workflow execution ran but failed at runtime.

- Aggregate: `workflow_execution`
- 必填 `data` 字段：
  - `workflow_id`
  - `execution_id`
  - `user_id`
  - `status`

### `workflow.sandbox_completed` (v1)

A workflow sandbox run finished (success or failure).

- Aggregate: `workflow_execution`
- 必填 `data` 字段：
  - `workflow_id`
  - `user_id`
  - `status`
  - `duration_ms`

