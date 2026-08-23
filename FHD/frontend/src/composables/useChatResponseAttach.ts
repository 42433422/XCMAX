import { type Ref } from 'vue'
import type { ChatMessage } from './useChatMessages'
import type { TaskItem } from './useChatPersistence'
import type { ChatPlannerPayload } from '@/types/chat'
import type { AgentRunEvent } from '@/api/agentRuns'
import { parseApprovalCardFromPayload } from '@/utils/chatApprovalCard'
import { buildAgentRunTraceFromEvents, isTrivialChatTrace } from '@/utils/agentRunTraceModel'
import { asRecord, asArray, asString, asNumber, asBoolean } from '@/utils/typeGuards'

export interface UseChatResponseAttachDeps {
  messages: Ref<ChatMessage[]>
  lastRequestContextSummary: Ref<string>
  taskList: Ref<TaskItem[]>
  upsertTask: (item: Partial<TaskItem> & Pick<TaskItem, 'id' | 'type' | 'source' | 'title' | 'status'>) => void
  createTaskId: (prefix: string) => string
}

function nestedData(data: ChatPlannerPayload): Record<string, unknown> {
  return asRecord(asRecord(data.data).data)
}

export function useChatResponseAttach(deps: UseChatResponseAttachDeps) {
  const { messages, lastRequestContextSummary, taskList, upsertTask, createTaskId } = deps

  function attachThinkingStepsToLastAiMessage(data: ChatPlannerPayload): void {
    const inner = nestedData(data)
    const envelope = asRecord(data.data)
    const thinkingSteps = asString(inner.thinking_steps || envelope.thinking_steps || data.thinking_steps).trim()
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

  function attachTodoStepsToLastAiMessage(data: ChatPlannerPayload): void {
    const todoRaw = nestedData(data).todo
    if (!Array.isArray(todoRaw) || !todoRaw.length) return
    const todoSteps = todoRaw.map((x) => asString(x).trim()).filter(Boolean)
    if (!todoSteps.length) return

    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.todoSteps = todoSteps
        break
      }
    }
  }

  function attachWorkflowTraceToLastAiMessage(data: ChatPlannerPayload): void {
    const envelope = asRecord(data.data)
    const action = asString(envelope.action).trim()
    const nodeResultsRaw = nestedData(data).node_results
    const nodeResults = asArray<Record<string, unknown>>(nodeResultsRaw)
      .map((x) => ({
        node_id: asString(x.node_id),
        success: !!x.success,
        tool_id: asString(x.tool_id),
        action: asString(x.action),
        error: asString(x.error),
        message: asString(x.message),
        output_preview: asString(x.output_preview),
        retries: asNumber(x.retries, 0),
        retryable: asBoolean(x.retryable, true),
        recovery_hint: asString(x.recovery_hint),
        duration_ms: asNumber(x.duration_ms, 0),
      }))
      .filter((x) => x.node_id)
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

  function attachApprovalCardToLastAiMessage(data: ChatPlannerPayload): void {
    const card = parseApprovalCardFromPayload(data)
    if (!card) return
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.approvalCard = card
        break
      }
    }
  }

  /**
   * 把最近 agent_run task 的 RunEvent[] 重建为 Codex 风格执行流 trace，
   * 挂到最近一条 AI 消息上（在 ChatMessageList 内联渲染）。
   *
   * 数据来源：useAgentRunEvents.ts 的 buildAgentRunTaskUpdate 会把 events
   * 塞进 TaskItem.payload.agentEvents；这里消费它，零后端改动。
   */
  function attachAgentRunTraceToLastAiMessage(): void {
    const messageRef = getLastAiMessageRef()
    if (!messageRef) return
    const target = taskList.value.find((t) => {
      if (t.type !== 'agent_run' && t.type !== 'agent_task') return false
      if (t.messageRef && t.messageRef !== messageRef) return false
      const events = asArray(asRecord(t.payload).agentEvents)
      return events.length > 0
    })
    if (!target) return
    const payload = asRecord(target.payload)
    const runId = asString(payload.activeRunId || payload.agentRunId) || target.id.replace(/^agent_(?:task_)?/, '')
    const events = asArray<AgentRunEvent>(payload.agentEvents)
    if (!events.length) return
    const trace = buildAgentRunTraceFromEvents(events, runId)
    // 闲聊无工具 / 单次成功只读工具：气泡只保留答案正文，不挂智能任务时间线与计划图
    if (isTrivialChatTrace(trace)) {
      for (let i = messages.value.length - 1; i >= 0; i -= 1) {
        const msg = messages.value[i]
        if (msg?.role === 'ai') {
          delete msg.agentRunTrace
          break
        }
      }
      return
    }
    for (let i = messages.value.length - 1; i >= 0; i -= 1) {
      const msg = messages.value[i]
      if (msg?.role === 'ai') {
        msg.agentRunTrace = trace
        break
      }
    }
  }

  function syncTaskFromChatResponse(resp: ChatPlannerPayload, userText: string) {
    const envelope = asRecord(resp.data)
    const action = asString(envelope.action).trim()
    const messageRef = getLastAiMessageRef()
    if (action === 'workflow_confirmation_required') {
      const pendingId = asString(nestedData(resp).pending_workflow_id) || createTaskId('wf')
      upsertTask({
        id: pendingId,
        type: 'workflow',
        source: 'workflow',
        title: `工作流任务：${String(userText || '').slice(0, 30) || '待确认任务'}`,
        status: 'queued',
        progress: 10,
        summary: '等待确认执行',
        messageRef,
        payload: { response: resp },
      })
      return
    }
    if (action === 'workflow_done' || action === 'workflow_failed') {
      const target = taskList.value.find((t) => t.type === 'workflow' && (t.status === 'queued' || t.status === 'running'))
      const nodeResults = asArray<Record<string, unknown>>(nestedData(resp).node_results)
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
          messageRef,
          payload: {
            ...(target.payload || {}),
            workflowNodeResults: nodeResults,
          },
        })
      } else {
        upsertTask({
          id: target.id,
          type: target.type,
          source: target.source,
          title: target.title,
          status: 'failed',
          error: asString(resp.message) || '工作流执行失败',
          messageRef,
          payload: {
            ...(target.payload || {}),
            workflowNodeResults: nodeResults,
          },
        })
      }
      return
    }
    const nodeResults = asArray<Record<string, unknown>>(nestedData(resp).node_results)
    if (nodeResults.length) {
      const running = taskList.value.find((t) => t.type === 'workflow' && (t.status === 'queued' || t.status === 'running'))
      if (running) {
        const done = nodeResults.filter((x) => !!x.success).length
        const progress = Math.max(15, Math.floor((done / nodeResults.length) * 100))
        upsertTask({
          id: running.id,
          type: running.type,
          source: running.source,
          title: running.title,
          status: 'running',
          progress,
          stage: `节点 ${done}/${nodeResults.length}`,
          messageRef,
        })
      }
    }
  }

  return {
    getLastAiMessageRef,
    attachThinkingStepsToLastAiMessage,
    attachTodoStepsToLastAiMessage,
    attachWorkflowTraceToLastAiMessage,
    attachApprovalCardToLastAiMessage,
    attachContextSummaryToLastAiMessage,
    attachAgentRunTraceToLastAiMessage,
    syncTaskFromChatResponse,
  }
}
