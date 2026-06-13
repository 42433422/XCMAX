import { type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import type { TaskItem } from './useChatPersistence'

export interface UseChatResponseAttachDeps {
  messages: Ref<ChatMessage[]>
  lastRequestContextSummary: Ref<string>
  taskList: Ref<TaskItem[]>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  createTaskId: (prefix: string) => string
}

export function useChatResponseAttach(deps: UseChatResponseAttachDeps) {
  const { messages, lastRequestContextSummary, taskList, upsertTask, createTaskId } = deps

  function attachThinkingStepsToLastAiMessage(data: any): void {
    const thinkingSteps = String(
      data?.data?.data?.thinking_steps
      || data?.data?.thinking_steps
      || data?.thinking_steps
      || ''
    ).trim()
    if (!thinkingSteps) return

    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.thinkingSteps = thinkingSteps
        break
      }
    }
  }

  function getLastAiMessageRef(): string {
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        return `${i}`
      }
    }
    return ''
  }

  function attachTodoStepsToLastAiMessage(data: any): void {
    const todoRaw = data?.data?.data?.todo
    if (!Array.isArray(todoRaw) || !todoRaw.length) return
    const todoSteps = todoRaw.map((x: any) => String(x || '').trim()).filter(Boolean)
    if (!todoSteps.length) return

    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.todoSteps = todoSteps
        break
      }
    }
  }

  function attachWorkflowTraceToLastAiMessage(data: any): void {
    const action = String(data?.data?.action || '').trim()
    const nodeResultsRaw = data?.data?.data?.node_results
    const nodeResults = Array.isArray(nodeResultsRaw)
      ? nodeResultsRaw.map((x: any) => ({
        node_id: String(x?.node_id || ''),
        success: !!x?.success,
        tool_id: String(x?.tool_id || ''),
        action: String(x?.action || ''),
        error: String(x?.error || '')
      })).filter((x: any) => x.node_id)
      : []
    if (!action && !nodeResults.length) return

    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.workflowAction = action
        if (nodeResults.length) {
          msg.nodeResults = nodeResults
        }
        break
      }
    }
  }

  function attachContextSummaryToLastAiMessage(): void {
    const summary = String(lastRequestContextSummary.value || '').trim()
    if (!summary) return
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.contextSummary = summary
        break
      }
    }
  }

  function syncTaskFromChatResponse(resp: any, userText: string) {
    const action = String(resp?.data?.action || '').trim()
    const messageRef = getLastAiMessageRef()
    if (action === 'workflow_confirmation_required') {
      const pendingId = String(resp?.data?.data?.pending_workflow_id || createTaskId('wf'))
      upsertTask({
        id: pendingId,
        type: 'workflow',
        source: 'workflow',
        title: `工作流任务：${String(userText || '').slice(0, 30) || '待确认任务'}`,
        status: 'queued',
        progress: 10,
        summary: '等待确认执行',
        messageRef,
        payload: { response: resp }
      })
      return
    }
    if (action === 'workflow_done' || action === 'workflow_failed') {
      const target = taskList.value.find((t) => t.type === 'workflow' && (t.status === 'queued' || t.status === 'running'))
      if (!target) return
      if (action === 'workflow_done') {
        upsertTask({
          id: target.id,
          type: target.type,
          source: target.source,
          title: target.title,
          status: 'success',
          progress: 100,
          summary: '执行完成',
          messageRef
        })
      } else {
        upsertTask({
          id: target.id,
          type: target.type,
          source: target.source,
          title: target.title,
          status: 'failed',
          error: String(resp?.message || '工作流执行失败'),
          messageRef
        })
      }
      return
    }
    const nodeResults = Array.isArray(resp?.data?.data?.node_results) ? resp.data.data.node_results : []
    if (nodeResults.length) {
      const running = taskList.value.find((t) => t.type === 'workflow' && (t.status === 'queued' || t.status === 'running'))
      if (running) {
        const done = nodeResults.filter((x: any) => !!x?.success).length
        const progress = Math.max(15, Math.floor((done / nodeResults.length) * 100))
        upsertTask({
          id: running.id,
          type: running.type,
          source: running.source,
          title: running.title,
          status: 'running',
          progress,
          stage: `节点 ${done}/${nodeResults.length}`,
          messageRef
        })
      }
    }
  }

  return {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    syncTaskFromChatResponse,
  }
}
