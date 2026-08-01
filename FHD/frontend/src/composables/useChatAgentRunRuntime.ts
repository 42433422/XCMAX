import { onBeforeUnmount, type Ref } from 'vue'
import agentRunsApi, { type AgentRun } from '@/api/agentRuns'
import type { ChatMessage } from './useChatMessages'
import type { TaskItem } from './useChatPersistence'
import { asRecord, asString } from '@/utils/typeGuards'

interface Options {
  messages: Ref<ChatMessage[]>
  taskList: Ref<TaskItem[]>
  retryTaskLocal: (id: string) => unknown
  addAndSaveMessage: (content: string, role: 'ai') => Promise<void>
  syncAgentRunEvents: (runId: string, userText?: string) => Promise<boolean>
  restoreRecentAgentRuns: (userId: string) => Promise<string[]>
  attachAgentRunTraceToLastAiMessage: () => void
  getUserId: () => string
  isLoading: Ref<boolean>
  setLoadingProgress: (text: string) => void
  stopLoadingProgress: () => void
  sendFallback: (message: string) => Promise<void>
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : asString(error, fallback)
}

export function useChatAgentRunRuntime(options: Options) {
  const timers = new Map<string, ReturnType<typeof setTimeout>>()

  function stopTracePolling(runId: string): void {
    const id = String(runId || '').trim()
    const timer = id ? timers.get(id) : undefined
    if (timer) clearTimeout(timer)
    if (id) timers.delete(id)
  }

  function startTracePolling(runId: string, attachToCurrentMessage = true): void {
    const id = String(runId || '').trim()
    if (!id || timers.has(id)) return
    let ticks = 0
    const schedule = () => {
      timers.set(id, setTimeout(async () => {
        ticks += 1
        let terminal = false
        try {
          terminal = await options.syncAgentRunEvents(id, '')
          if (attachToCurrentMessage) options.attachAgentRunTraceToLastAiMessage()
        } catch {
          // Best-effort polling retries on the next tick.
        }
        if (terminal || ticks >= 150) stopTracePolling(id)
        else schedule()
      }, 2000))
    }
    schedule()
  }

  async function retryTask(id: string): Promise<void> {
    const task = options.taskList.value.find((item) => item.id === id)
    if (!task || task.type !== 'agent_run') {
      options.retryTaskLocal(id)
      return
    }
    const payload = asRecord(task.payload)
    const runId = asString(payload.agentRunId || payload.run_id).trim()
      || String(task.id || '').replace(/^agent_/, '')
    if (!runId) {
      await options.addAndSaveMessage('无法重试：任务缺少持久化 Run ID。', 'ai')
      return
    }
    try {
      const response = await agentRunsApi.restartRun(runId, { requested_by: options.getUserId() })
      const restarted = response?.data
      if (!response?.success || !restarted?.run_id) throw new Error(String(response?.message || '任务不能安全重启'))
      await options.addAndSaveMessage(`已创建新的安全重试任务。\n原任务：${runId}\n新任务：${restarted.run_id}`, 'ai')
      await options.syncAgentRunEvents(restarted.run_id, restarted.message || task.title)
      options.attachAgentRunTraceToLastAiMessage()
      if (!['completed', 'failed', 'cancelled'].includes(restarted.status)) startTracePolling(restarted.run_id)
    } catch (error: unknown) {
      await options.addAndSaveMessage(`无法自动重试：${errorMessage(error, '该任务可能已产生业务变更，请先人工复核。')}`, 'ai')
    }
  }

  async function confirmWorkflowFromCard(): Promise<void> {
    const pendingMessage = [...options.messages.value].reverse().find(
      (message) => message?.role === 'ai' && message.approvalCard?.status === 'pending',
    )
    const pendingCard = pendingMessage?.approvalCard
    const runId = String(pendingCard?.agent_run_id || pendingCard?.run_id || '').trim()
    if (runId && pendingCard?.approval_required && pendingMessage?.approvalCard) {
      try {
        options.isLoading.value = true
        options.setLoadingProgress('正在提交正式审批...')
        const response = await agentRunsApi.submitApproval(runId, { requested_by: options.getUserId() })
        const requestIds = Array.isArray(response?.data?.approval_request_ids)
          ? response.data.approval_request_ids.filter(Boolean) : []
        if (!response?.success || !requestIds.length) throw new Error(String(response?.message || '审批请求提交失败'))
        pendingMessage.approvalCard = { ...pendingMessage.approvalCard, status: 'confirmed', approval_request_ids: requestIds }
        await options.addAndSaveMessage(`审批已提交；审批中心通过后将继续原任务。\n审批单：${requestIds.join('、')}\n任务回执：${runId}`, 'ai')
        await options.syncAgentRunEvents(runId, String(response.data?.run?.message || ''))
        options.attachAgentRunTraceToLastAiMessage()
        startTracePolling(runId)
      } catch (error: unknown) {
        await options.addAndSaveMessage(`提交审批失败：${errorMessage(error, '未知错误')}。原任务仍保留，可稍后重试。`, 'ai')
      } finally {
        options.isLoading.value = false
        options.stopLoadingProgress()
      }
      return
    }
    if (runId && pendingMessage?.approvalCard) {
      try {
        options.isLoading.value = true
        options.setLoadingProgress('正在执行已确认的业务步骤...')
        const response = await agentRunsApi.continueRun(runId, { approved_by: options.getUserId() })
        const run = response?.data as AgentRun | undefined
        if (!response?.success || !run) throw new Error(String(response?.message || '任务继续执行失败'))
        pendingMessage.approvalCard = { ...pendingMessage.approvalCard, status: 'confirmed' }
        const steps = Array.isArray(run.steps) ? run.steps : []
        const lastOutput = [...steps].reverse().find((step) => step?.output)?.output || {}
        const detail = String(lastOutput.message || lastOutput.error || run.error || '').trim()
        const text = run.status === 'completed'
          ? `执行完成：${detail || '所有业务步骤均已完成并写入工具回执。'}\n任务回执：${run.run_id}`
          : run.status === 'failed'
            ? `执行失败：${detail || '业务工具未完成变更。'}\n任务回执：${run.run_id}`
            : `已确认当前步骤，任务状态：${run.status}。\n任务回执：${run.run_id}`
        await options.addAndSaveMessage(text, 'ai')
        await options.syncAgentRunEvents(runId, String(run.message || ''))
        options.attachAgentRunTraceToLastAiMessage()
        if (!['completed', 'failed', 'cancelled'].includes(run.status)) startTracePolling(runId)
      } catch (error: unknown) {
        await options.addAndSaveMessage(`确认执行失败：${errorMessage(error, '未知错误')}。原任务仍保留，可稍后重试。`, 'ai')
      } finally {
        options.isLoading.value = false
        options.stopLoadingProgress()
      }
      return
    }
    if (pendingMessage?.approvalCard) pendingMessage.approvalCard = { ...pendingMessage.approvalCard, status: 'confirmed' }
    await options.sendFallback('确认')
  }

  async function cancelWorkflowFromCard(): Promise<void> {
    const pendingMessage = [...options.messages.value].reverse().find(
      (message) => message?.role === 'ai' && message.approvalCard?.status === 'pending',
    )
    const runId = String(pendingMessage?.approvalCard?.agent_run_id || pendingMessage?.approvalCard?.run_id || '').trim()
    if (runId && pendingMessage?.approvalCard) {
      try {
        const response = await agentRunsApi.cancelRun(runId, { cancelled_by: options.getUserId() })
        const run = response?.data as AgentRun | undefined
        if (!response?.success || !run) throw new Error(String(response?.message || '任务取消失败'))
        pendingMessage.approvalCard = { ...pendingMessage.approvalCard, status: 'cancelled' }
        await options.addAndSaveMessage(`任务已取消，未执行后续业务变更。\n任务回执：${run.run_id}`, 'ai')
        await options.syncAgentRunEvents(runId, String(run.message || ''))
        options.attachAgentRunTraceToLastAiMessage()
      } catch (error: unknown) {
        await options.addAndSaveMessage(`取消失败：${errorMessage(error, '未知错误')}。原任务仍保留。`, 'ai')
      }
      return
    }
    if (pendingMessage?.approvalCard) pendingMessage.approvalCard = { ...pendingMessage.approvalCard, status: 'cancelled' }
    await options.sendFallback('取消')
  }

  async function restoreAndPoll(userId: string): Promise<void> {
    for (const runId of await options.restoreRecentAgentRuns(userId)) startTracePolling(runId, false)
  }

  onBeforeUnmount(() => {
    for (const runId of timers.keys()) stopTracePolling(runId)
  })

  return { retryTask, startTracePolling, confirmWorkflowFromCard, cancelWorkflowFromCard, restoreAndPoll }
}
