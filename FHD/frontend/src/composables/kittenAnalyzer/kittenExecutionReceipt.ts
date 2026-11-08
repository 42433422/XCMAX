import { KITTEN_PHASE, type KittenPhase } from '@/composables/useKittenWorkflowState'
import { asRecord, asString } from '@/utils/typeGuards'
import { requiresTurnReconciliation } from '../chat-orchestration/chatOrchestrationShared'
import type { KittenAnalysisResult } from './kittenAnalyzerShared'

export type KittenExecutionReceipt = NonNullable<KittenAnalysisResult['execution']>

const COMPLETED = ['completed', 'success', 'succeeded', 'done', 'ok']
const AUTHORIZATION = ['waiting_authorization', 'authorization_required', 'waiting_auth', 'awaiting_auth', 'requires_token']
const APPROVAL = ['waiting_approval', 'awaiting_approval', 'pending_approval', 'approval_required']
const WAITING = ['waiting_user', 'waiting_input', 'awaiting_input', 'waiting', 'blocked', 'paused']
const RUNNING = ['accepted', 'queued', 'running', 'pending', 'in_progress', 'inflight', 'retrying', 'planning', 'processing']
const UNCONFIRMED = ['interrupted', 'partial', 'partial_failure', 'partial_success']
const FAILED = [
  'failed',
  'failure',
  'fail',
  'error',
  'cancelled',
  'canceled',
  'rejected',
  'denied',
  'expired',
  'timed_out',
  'timeout',
  'aborted',
]
const KNOWN = new Set([...COMPLETED, ...AUTHORIZATION, ...APPROVAL, ...WAITING, ...RUNNING, ...UNCONFIRMED, ...FAILED])
export const KITTEN_UNCONFIRMED_REASON = '原任务结果尚未确认，请核对原任务，勿重复提交。'

/** Inspect only execution envelopes, with bounds that fail closed for oversized/deep receipts. */
function executionRows(value: unknown) {
  const queue = [{ value, depth: 0 }]
  const rows: Record<string, unknown>[] = []
  const seen = new Set<object>()
  let incomplete = false
  while (queue.length) {
    const next = queue.shift()!
    if (!next.value || typeof next.value !== 'object' || seen.has(next.value)) continue
    seen.add(next.value)
    if (next.depth > 6 || rows.length >= 100) {
      incomplete = true
      continue
    }
    const row = asRecord(next.value)
    rows.push(row)
    for (const key of ['data', 'payload', 'result', 'output', 'final_output', 'chat_payload', 'agent_run']) {
      queue.push({ value: row[key], depth: next.depth + 1 })
    }
    for (const key of ['outputs', 'node_outputs', 'legacy_tool_records', '_tool_records', 'tool_records', 'steps']) {
      const children = Array.isArray(row[key]) ? row[key] : Object.values(asRecord(row[key]))
      if (children.length > 100) incomplete = true
      for (const child of children.slice(0, 100)) queue.push({ value: child, depth: next.depth + 1 })
    }
  }
  return { rows, incomplete }
}

export function inspectKittenExecution(value: unknown) {
  const { rows, incomplete } = executionRows(value)
  const firstText = (read: (row: Record<string, unknown>) => unknown) =>
    rows.map(read).find((item) => typeof item === 'string' && item.trim()) as string | undefined
  const states = rows.flatMap((row) =>
    ['execution_outcome', 'execution_state', 'execution_status', 'outcome', 'status', 'state', 'exit_status']
      .map((key) => (typeof row[key] === 'string' ? row[key].trim().toLowerCase() : ''))
      .filter(Boolean),
  )
  const matched = (choices: string[]) => states.find((state) => choices.includes(state))
  let phase: KittenPhase = KITTEN_PHASE.unknown
  let title = '结果待核对'
  let status = 'unknown'
  let reason = KITTEN_UNCONFIRMED_REASON
  if (incomplete || matched(UNCONFIRMED) || rows.some(requiresTurnReconciliation) || states.some((state) => !KNOWN.has(state))) {
    // Neither an outer transport success nor a recognized sibling state can erase uncertainty.
  } else if (rows.some((row) => row.requires_token) || matched(AUTHORIZATION)) {
    phase = KITTEN_PHASE.waitingAuthorization
    title = '等待授权'
    status = matched(AUTHORIZATION) || 'waiting_authorization'
    reason = `需要授权：${firstText((row) => row.token_description || row.token_name) || '授权信息'}。原任务尚未完成，等待授权处理。`
  } else if (rows.some((row) => row.pending_approval) || matched(APPROVAL)) {
    phase = KITTEN_PHASE.waitingApproval
    title = '等待审批'
    status = matched(APPROVAL) || 'waiting_approval'
    reason = '原任务正在等待审批，审批完成前尚未执行完成。'
  } else if (rows.some((row) => row.needs_user_input) || matched(WAITING)) {
    phase = KITTEN_PHASE.waitingUser
    title = '等待处理'
    status = matched(WAITING) || 'waiting_user'
    reason = firstText((row) => row.waiting_reason || row.message) || '原任务需要补充信息或人工处理。'
  } else if (matched(FAILED) || rows.some((row) => row.error)) {
    phase = KITTEN_PHASE.error
    title = '请求未完成'
    status = matched(FAILED) || 'failed'
    reason = firstText((row) => row.message || row.error) || '原任务未完成。'
  } else if (matched(RUNNING)) {
    phase = KITTEN_PHASE.analyzing
    title = '任务处理中'
    status = matched(RUNNING)!
    reason = '原任务仍在处理，请勿重复提交。'
  } else if (rows.some((row) => row.success === false || row.ok === false)) {
    phase = KITTEN_PHASE.error
    title = '请求未完成'
    status = 'failed'
    reason = firstText((row) => row.message) || '原任务未完成。'
  } else if (matched(COMPLETED) || rows.some((row) => row.success === true || row.ok === true)) {
    phase = KITTEN_PHASE.delivered
    title = 'AI 分析'
    status = 'completed'
    reason = ''
  }
  return {
    phase,
    title,
    status,
    reason,
    run_id: firstText((row) => row.run_id || row.agent_run_id) || '',
    approval_id:
      firstText(
        (row) =>
          row.approval_id || asRecord(row.approval).approval_id || asRecord(row.approval).id || asRecord(row.pending_approval).approval_id,
      ) || '',
    token_name: firstText((row) => row.token_name) || '',
    text: firstText((row) => row.response || row.text) || '',
  }
}

export function rememberKittenExecution(receipt: KittenExecutionReceipt, value: unknown) {
  const result = inspectKittenExecution(value)
  // Once received, the original run remains the only candidate for recovery.
  receipt.run_id ||= asString(result.run_id).trim()
  receipt.approval_id = asString(result.approval_id).trim() || receipt.approval_id
  receipt.token_name = asString(result.token_name).trim() || receipt.token_name
}
