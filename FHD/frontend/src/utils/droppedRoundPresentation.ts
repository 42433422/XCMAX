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
