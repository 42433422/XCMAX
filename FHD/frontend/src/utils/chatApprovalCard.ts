import type { ChatApprovalCard } from '@/types/chat-ui'
import type { ChatPlannerPayload } from '@/types/chat'
import { asArray, asBoolean, asRecord, asString } from '@/utils/typeGuards'

function nestedData(data: ChatPlannerPayload): Record<string, unknown> {
  return asRecord(asRecord(data.data).data)
}

export function parseApprovalCardFromPayload(data: ChatPlannerPayload): ChatApprovalCard | null {
  const envelope = asRecord(data.data)
  const inner = nestedData(data)
  const raw = asRecord(inner.approval_card)
  if (!Object.keys(raw).length) {
    const action = asString(envelope.action).trim()
    if (
      action !== 'workflow_confirmation_required' &&
      action !== 'approval_pending'
    ) {
      return null
    }
    return {
      kind: action,
      plan_id: asString(inner.plan_id),
      run_id: asString(inner.run_id || inner.agent_run_id),
      agent_run_id: asString(inner.agent_run_id || inner.run_id),
      intent: asString(inner.intent),
      blocking_nodes: asArray(inner.blocking_nodes).map((x) => asString(x)).filter(Boolean),
      approval_required: asBoolean(inner.approval_required, false),
      approval_nodes: asArray<Record<string, unknown>>(inner.approval_nodes).map((n) => ({
        node_id: asString(n.node_id),
        tool_id: asString(n.tool_id),
        action: asString(n.action),
      })),
      approval_request_ids: asArray(inner.approval_request_ids).map((x) => asString(x)).filter(Boolean),
      approval_path: asString(inner.approval_path),
      todo: asArray(inner.todo).map((x) => asString(x)).filter(Boolean),
      reason: asString(inner.reason),
      confirm_mode: asBoolean(inner.approval_required, false) ? 'approval' : 'interactive',
      status: 'pending',
    }
  }
  return {
    version: Number(raw.version) || 1,
    kind: asString(raw.kind || envelope.action),
    plan_id: asString(raw.plan_id),
    run_id: asString(raw.run_id || raw.agent_run_id),
    agent_run_id: asString(raw.agent_run_id || raw.run_id),
    intent: asString(raw.intent),
    blocking_nodes: asArray(raw.blocking_nodes).map((x) => asString(x)).filter(Boolean),
    approval_required: asBoolean(raw.approval_required, false),
    approval_nodes: asArray<Record<string, unknown>>(raw.approval_nodes).map((n) => ({
      node_id: asString(n.node_id),
      tool_id: asString(n.tool_id),
      action: asString(n.action),
    })),
    approval_request_ids: asArray(raw.approval_request_ids).map((x) => asString(x)).filter(Boolean),
    approval_path: asString(raw.approval_path),
    todo: asArray(raw.todo).map((x) => asString(x)).filter(Boolean),
    reason: asString(raw.reason),
    confirm_mode: asString(raw.confirm_mode) || 'interactive',
    status: 'pending',
  }
}
