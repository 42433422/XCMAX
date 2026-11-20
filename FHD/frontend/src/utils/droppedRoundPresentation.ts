import { asArray, asRecord, asString } from './typeGuards'

export type DroppedRoundStatus =
  | 'completed'
  | 'failed'
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
}

export function activeChatTurnStatus(raw: string): ActiveChatTurn['status'] | undefined {
  if (raw === 'waiting_user' || raw === 'waiting_approval') return 'waiting_approval'
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
  if (activeTurn?.turnId === turnId) {
    const status = activeTurn.status === 'blocked' ? 'unknown' : activeTurn.status === 'paused' ? 'waiting_approval' : activeTurn.status
    return { status, workflowAction: activeTurn.status, text: activeChatTurnMessage(activeTurn), activeTurn }
  }
  const receipt = asRecord(body.turn_receipt)
  if (turnId && asString(receipt.turn_id) === turnId && asString(receipt.run_id)) {
    return droppedRoundPresentation({
      reachable: true, serverStatus: asString(receipt.status), serverText: asString(receipt.message),
    })
  }
  const rows = asArray(body.messages ?? asRecord(body.data).messages)
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
      return droppedRoundPresentation({ reachable: true, serverStatus, serverText: asString(row.content) })
    }
  }
  return droppedRoundPresentation({ reachable: true })
}
