import type { ChatApprovalCard } from '@/types/chat-ui'
import type { ChatPlannerPayload } from '@/types/chat'
import { asArray, asBoolean, asRecord, asString } from '@/utils/typeGuards'
import { createBusinessHarnessId } from '@/utils/businessHarnessIds'

function nestedData(data: ChatPlannerPayload): Record<string, unknown> {
  return asRecord(asRecord(data.data).data)
}

/** Persisted card IDs keep clicks attached to the same message across updates. */
export function approvalCardId(card: ChatApprovalCard): string {
  return card.id || (card.run_id || card.agent_run_id ? `run:${card.run_id || card.agent_run_id}` : card.plan_id ? `plan:${card.plan_id}` : '')
}

export function restoreApprovalCard(card: ChatApprovalCard): ChatApprovalCard {
  const { submitting: _submitting, ...saved } = card
  return { ...saved, id: card.id || `approval:${createBusinessHarnessId('turn')}` }
}

export function parseApprovalCardFromPayload(data: ChatPlannerPayload): ChatApprovalCard | null {
  const envelope = asRecord(data.data)
  const inner = nestedData(data)
  const explicit = asRecord(inner.approval_card)
  const action = asString(envelope.action).trim()
  if (!Object.keys(explicit).length && action !== 'workflow_confirmation_required' && action !== 'approval_pending') return null
  const raw = { ...inner, ...explicit }
  const runId = asString(raw.run_id || raw.agent_run_id || envelope.run_id || envelope.agent_run_id || data.run_id || data.agent_run_id)
  return restoreApprovalCard({
    version: Number(raw.version) || 1,
    kind: asString(raw.kind || envelope.action),
    plan_id: asString(raw.plan_id),
    run_id: runId,
    agent_run_id: runId,
    intent: asString(raw.intent),
    blocking_nodes: asArray(raw.blocking_nodes)
      .map((x) => asString(x))
      .filter(Boolean),
    approval_required: asBoolean(raw.approval_required, false),
    approval_nodes: asArray<Record<string, unknown>>(raw.approval_nodes).map((n) => ({
      node_id: asString(n.node_id),
      tool_id: asString(n.tool_id),
      action: asString(n.action),
    })),
    approval_request_ids: asArray(raw.approval_request_ids)
      .map((x) => asString(x))
      .filter(Boolean),
    approval_path: asString(raw.approval_path),
    todo: asArray(raw.todo)
      .map((x) => asString(x))
      .filter(Boolean),
    reason: asString(raw.reason),
    confirm_mode: asString(raw.confirm_mode) || (asBoolean(raw.approval_required, false) ? 'approval' : 'interactive'),
    status: 'pending',
  })
}
