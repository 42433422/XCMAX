import type { ChatApprovalCard } from '@/types/chat-ui'
import type { ChatMessage } from '@/composables/useChatMessages'
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

/**
 * 服务端历史快照不带前端 status。只有会话里最新一条带待确认卡片的 AI 消息
 * 才可能是仍在 waiting_user 的任务；更早的消息已有后续回执，不能再次提交。
 * 返回是否发生了状态调整。
 */
export function reconcileApprovalCards(messages: ChatMessage[]): boolean {
  // 本地未保存消息与服务端历史合并后顺序可能错位（时间只有时分，跨天也不能比较），
  // 因此取「最近一条用户消息之后的第一张卡片」作为仍然在等待确认的卡片。
  let lastUserIndex = -1
  messages.forEach((msg, index) => {
    if (msg?.role === 'user') lastUserIndex = index
  })
  let lastIndex = -1
  messages.forEach((msg, index) => {
    if (msg?.role !== 'ai' || !msg.approvalCard) return
    if (lastIndex < 0 && index > lastUserIndex) lastIndex = index
  })
  let changed = false
  messages.forEach((msg, index) => {
    const card = msg?.approvalCard
    if (!card) return
    if (card.status === 'confirmed' || card.status === 'cancelled') return
    const submitted = Boolean(card.approval_path || card.approval_request_ids?.length)
    if (submitted) {
      if (!card.status) {
        card.status = 'confirmed'
        changed = true
      }
      return
    }
    const next = index === lastIndex ? 'pending' : 'confirmed'
    if (card.status !== next) {
      card.status = next
      changed = true
    }
  })
  return changed
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
