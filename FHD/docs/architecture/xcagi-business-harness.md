# XCAGI Business Harness v1

XCAGI Business Harness borrows the durable orchestration shape of Codex—thread, turn, run,
event stream, approval, terminal result—but makes the contract business-native, tenant-aware,
and suitable for ERP side effects. It is a protocol over the existing AgentRun/AgentTask,
workflow, approval, conversation, and artifact services; it is not a second workflow engine.

The conceptual blueprint is OpenAI Codex's public app-server protocol: a durable thread owns
turns, each turn streams typed item lifecycle notifications, approvals are correlated to the
thread and turn, and the terminal completion event is authoritative. XCAGI extends that shape
with an explicit business task identity, ERP approval records, retry attempts, tenant context,
business facts, and persisted-effect evidence. No Codex source code is copied into this layer.

## Runtime model

| Object | Identity | Lifetime | Meaning |
| --- | --- | --- | --- |
| Conversation | `conversation_id` | user thread | Business context and readable history |
| Turn | `turn_id` | one submitted user round or batch | Input boundary and message idempotency scope |
| Task | `task_id` | one business objective | Durable control-plane object shown in the task center |
| Run | `run_id` | one execution attempt | Plan, steps, tool calls, observations, cost, and evidence |
| Event | `event_id` | immutable occurrence | Ordered runtime change carrying a harness identity envelope |
| Approval | `request_no` | one risk gate | Human authorization; approval is never treated as execution |
| Result | `projection_key` | one terminal run state | User-readable outcome plus bounded facts and evidence links |

The key rule is `conversation_id != task_id`. A conversation may contain many independent
tasks. A retry keeps the same `task_id` and increments `attempt`; a new user objective gets a
new `task_id`. Approval resume keeps the original task and run identity.

## State and event contract

Runs use the canonical states `queued`, `planning`, `running`, `retrying`, `waiting_user`,
`paused`, `blocked`, `completed`, `failed`, and `cancelled`. Every event contains:

```json
{
  "event_type": "tool.completed",
  "data": {
    "harness": {
      "protocol": "xcagi.business-harness.v1",
      "conversation_id": "...",
      "turn_id": "turn_...",
      "task_id": "task_...",
      "run_id": "run_...",
      "attempt": 1
    }
  }
}
```

The event stream is the live synchronization path. Snapshot polling remains a 15-second
recovery path for upgrades, disconnects, and older backends; it is not the primary UI clock.

## Approval and terminal projection

Medium/high-risk writes stop at `waiting_user`. Creating an approval request proves only that
authorization is pending. On approval, the original run continues. On rejection, the waiting
run is cancelled. Only after the run reaches a terminal state does the harness create a
`business_result` containing:

- `success`, `status`, and a readable `summary`;
- bounded business facts such as customer/order/record IDs and counts;
- evidence counts and artifact IDs;
- the full conversation/turn/task/run identity chain;
- an idempotent `projection_key`.

For approval-backed chat work, that result is written once into the originating conversation.
Raw node outputs remain available only in the advanced evidence panel.

## Persistence ownership

The backend is the source of truth for remote chat turns. The renderer writes only local-only
actions and fast paths that do not pass through the chat application service. Conversation
metadata stores a whitelisted UI payload so approval cards, plans, traces, attachments, and
terminal results survive reloads without persisting arbitrary component state.

## Safety invariants

1. Tenant and authenticated actor boundaries are resolved server-side.
2. Business writes remain behind the existing risk gate and approval service.
3. Tool idempotency and approval replay guards remain authoritative.
4. Terminal result projection is idempotent and cannot execute a tool.
5. User-facing plans use business descriptions; tool IDs, dependency IDs, and raw JSON stay in
   the advanced evidence view.

## Reference blueprint

- [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Codex Python SDK thread and turn API](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md)
