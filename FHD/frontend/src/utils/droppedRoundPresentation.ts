import agentRunsApi from '@/api/agentRuns'
import chatApi from '@/api/chat'
import { asArray, asRecord, asString } from './typeGuards'

export type DroppedRoundStatus =
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'interrupted'
  | 'unknown'
  | 'running'
  | 'queued'
  | 'waiting_approval'

export interface ActiveChatTurn {
  turnId: string
  runId: string
  taskId?: string
  status: 'running' | 'queued' | 'waiting_approval' | 'paused' | 'blocked'
  message: string
}

interface DroppedRoundPresentation {
  status: DroppedRoundStatus
  text: string
  workflowAction: string
  activeTurn?: ActiveChatTurn
  savedMessage?: Record<string, unknown>
}

export function activeChatTurnStatus(raw: string): ActiveChatTurn['status'] | undefined {
  if (raw === 'waiting_user' || raw === 'waiting_approval') return 'waiting_approval'
  if (raw === 'waiting_input' || raw === 'waiting_auth') return 'blocked'
  if (raw === 'queued' || raw === 'pending') return 'queued'
  if (raw === 'paused' || raw === 'blocked') return raw
  if (['running', 'planning', 'retrying'].includes(raw)) return 'running'
}

export function readActiveChatTurn(value: unknown): ActiveChatTurn | undefined {
  const body = asRecord(value)
  const row = asRecord(body.active_turn || asRecord(body.data).active_turn)
  const turnId = asString(row.turn_id).trim()
  const runId = asString(row.run_id).trim()
  const status = activeChatTurnStatus(asString(row.status).trim().toLowerCase())
  const taskId = asString(row.task_id).trim()
  return turnId && runId && status ? { turnId, runId, status, ...(taskId ? { taskId } : {}), message: asString(row.message).trim() } : undefined
}

export function activeChatTurnMessage(turn: ActiveChatTurn): string {
  if (turn.message) return turn.message
  if (turn.status === 'blocked') return '请先核对原任务的回执，再决定如何继续。'
  if (turn.status === 'waiting_approval') return '原任务正在等待确认。'
  if (turn.status === 'paused') return '原任务已暂停。'
  return turn.status === 'queued' ? '原任务仍在排队。' : '原任务仍在执行，正在读取进度。'
}

export function droppedRoundPresentation(input: {
  reachable: boolean
  serverStatus?: string | null
  serverText?: string | null
}): DroppedRoundPresentation {
  if (!input.reachable) {
    return {
      status: 'unknown',
      workflowAction: 'unknown',
      text: '连接中断，结果未知。请核对原任务后再决定是否重试，未标记为成功。',
    }
  }
  const status = String(input.serverStatus || '').trim().toLowerCase()
  const text = String(input.serverText || '').trim()
  if ((status === 'completed' || status === 'succeeded') && text) {
    return { status: 'completed', workflowAction: 'completed', text }
  }
  if (status === 'running' || status === 'queued' || status === 'waiting_approval') {
    return {
      status,
      workflowAction: status,
      text: '原任务仍在服务端处理，未标记为成功。请稍后核对，勿重复提交。',
    }
  }
  if (status === 'interrupted') {
    return {
      status: 'interrupted',
      workflowAction: 'interrupted',
      text: '本轮已中断，未标记为成功。请核对原任务后再决定是否重试。',
    }
  }
  if (status === 'failed') {
    return { status: 'failed', workflowAction: 'failed', text: text || '服务端确认本轮失败。' }
  }
  if (status === 'blocked') {
    return { status: 'blocked', workflowAction: 'blocked', text: text || '原任务已阻断，请核对回执。' }
  }
  return {
    status: 'unknown',
    workflowAction: 'unknown',
    text: '连接中断，服务端状态未确认。未标记为成功，请核对原任务，勿重复提交。',
  }
}
/** History stores turn identity and the outcome in metadata, sometimes as JSON. */
export function droppedRoundFromHistory(conversation: unknown, turnId: string): DroppedRoundPresentation {
  const body = asRecord(conversation)
  const activeTurn = readActiveChatTurn(body)
  const receipt = asRecord(body.turn_receipt)
  const rows = asArray(body.messages ?? asRecord(body.data).messages)
  const savedBlockedReceipt = activeTurn?.status === 'blocked' && receipt.turn_id === turnId
    && typeof receipt.message_id === 'number' && body.durable === true
    && rows.some(row => asRecord(row).id === receipt.message_id && asString(asRecord(row).content).trim())
  if (activeTurn?.turnId === turnId && !savedBlockedReceipt) {
    const status = activeTurn.status === 'blocked' ? 'unknown' : activeTurn.status === 'paused' ? 'waiting_approval' : activeTurn.status
    return { status, workflowAction: activeTurn.status, text: activeChatTurnMessage(activeTurn), activeTurn }
  }
  if (turnId && asString(receipt.turn_id) === turnId && (asString(receipt.run_id)
    || (receipt.receipt_kind === 'turn' && receipt.durable === true))) {
    const uncertain = receipt.requires_reconciliation === true || receipt.reconciliation_required === true || receipt.outcome_unknown === true
    const presentation = droppedRoundPresentation({
      reachable: true, serverStatus: uncertain ? 'unknown' : asString(receipt.execution_state || receipt.status), serverText: asString(receipt.message),
    })
    const savedMessage = typeof receipt.message_id === 'number' && body.durable === true
      ? rows.map(asRecord).find(row => row.id === receipt.message_id && ['assistant', 'ai'].includes(asString(row.role))) : undefined
    return { ...presentation, ...(savedMessage && !uncertain ? { savedMessage: { ...savedMessage, durable: true } } : {}) }
  }
  if (turnId && body.success !== false) {
    for (const raw of [...rows].reverse()) {
      const row = asRecord(raw)
      if (row.role !== 'assistant' && row.role !== 'ai') continue
      let metadata = asRecord(row.metadata)
      if (typeof row.metadata === 'string') {
        try { metadata = asRecord(JSON.parse(row.metadata)) } catch { continue }
      }
      const summary = asRecord(metadata.summary)
      const ui = asRecord(row.ui_payload || metadata.ui)
      const savedTurn = asString(ui.turnId || asRecord(metadata.business_harness).turn_id || summary.turn_id).trim()
      if (savedTurn !== turnId) continue
      const state = asString(summary.status || row.status).trim().toLowerCase()
      const serverStatus = state === 'outcome_unknown' ? 'unknown'
        : summary.success === false && ['completed', 'succeeded'].includes(state) ? 'failed'
        : ['completed', 'succeeded', 'failed', 'interrupted', 'running', 'queued', 'waiting_approval', 'unknown'].includes(state) ? state
        : summary.success === false ? 'failed'
          : summary.success === true && !summary.status && !row.status ? 'completed' : 'unknown'
      return { ...droppedRoundPresentation({ reachable: true, serverStatus, serverText: asString(row.content) }),
        ...(body.durable === true ? { savedMessage: { ...row, durable: true } } : {}) }
    }
  }
  return droppedRoundPresentation({ reachable: true })
}

/** Read the persisted turn first; only an exact failed run may fill a missing receipt. */
export async function readDroppedRoundOutcome(
  sessionId: string,
  turnId: string | undefined,
  runId: string,
  isActive: () => boolean,
): Promise<ReturnType<typeof droppedRoundPresentation>> {
  let presentation = droppedRoundPresentation({ reachable: false })
  try {
    const convo = await chatApi.getConversation(sessionId, { turn_id: turnId })
    presentation = droppedRoundFromHistory(convo, turnId || '')
  } catch {
    // The original conversation may not be available after disconnecting.
  }
  if (presentation.activeTurn || presentation.status !== 'unknown' || !runId || !isActive()) return presentation
  try {
    const receipt = await agentRunsApi.getRun(runId)
    const run = receipt.data
    if (receipt.success && run?.run_id === runId && run.status === 'failed') {
      return droppedRoundPresentation({ reachable: true, serverStatus: run.status, serverText: run.error })
    }
  } catch {
    // Keep the unknown state if the authoritative run cannot be read.
  }
  return presentation
}
