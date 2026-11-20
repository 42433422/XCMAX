import agentRunsApi from '@/api/agentRuns'
import chatApi from '@/api/chat'
import { asArray, asRecord, asString } from './typeGuards'

export type DroppedRoundStatus =
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'unknown'
  | 'running'
  | 'queued'
  | 'waiting_approval'

export function droppedRoundPresentation(input: {
  reachable: boolean
  serverStatus?: string | null
  serverText?: string | null
}): { status: DroppedRoundStatus; text: string; workflowAction: string } {
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
export function droppedRoundFromHistory(conversation: unknown, turnId: string) {
  const body = asRecord(conversation)
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
      const serverStatus = summary.success === false ? 'failed'
        : ['completed', 'succeeded', 'failed', 'interrupted', 'running', 'queued', 'waiting_approval'].includes(state) ? state
          : summary.success === true && !summary.status && !row.status ? 'completed' : 'unknown'
      return droppedRoundPresentation({ reachable: true, serverStatus, serverText: asString(row.content) })
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
  if (presentation.status !== 'unknown' || !runId || !isActive()) return presentation
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
