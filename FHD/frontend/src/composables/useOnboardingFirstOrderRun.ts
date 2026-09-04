import agentRunsApi from '@/api/agentRuns'
import { bindPendingFirstAiTaskRun, isFirstAiTaskPending } from '@/constants/productFlow'
import type { ChatMessageExtras } from './useChatMessages'

interface UseOnboardingFirstOrderRunOptions {
  sessionId: () => string
  saveMessage: (role: 'user' | 'ai' | 'task', content: string, targetSessionId?: string) => Promise<void>
  addAndSaveMessage: (
    content: string,
    role?: 'user' | 'ai' | 'task',
    extras?: ChatMessageExtras,
    targetSessionId?: string,
  ) => Promise<void>
  refreshTasks: () => Promise<void>
}

function isFirstOrderPrompt(message: string): boolean {
  return isFirstAiTaskPending() && message.includes('新手第一单') && message.includes('演示出货单')
}

/** Route the seeded onboarding prompt through the durable AgentRun path. */
export function useOnboardingFirstOrderRun(options: UseOnboardingFirstOrderRunOptions) {
  async function tryStart(message: string): Promise<boolean> {
    if (!isFirstOrderPrompt(message)) return false
    const targetSessionId = options.sessionId()
    await options.saveMessage('user', message, targetSessionId)
    try {
      const response = await agentRunsApi.createRun({
        message,
        auto_execute: true,
        runtime_context: {
          conversation_id: targetSessionId,
          source: 'product_onboarding_first_order',
        },
      })
      const runId = String(response?.data?.run_id || '').trim()
      if (!runId || !bindPendingFirstAiTaskRun(runId, message)) {
        throw new Error('未能绑定新手第一单任务')
      }
      await options.addAndSaveMessage(
        'AI 第一单已进入任务工作区。客户和商品查询完成后，请在任务卡片中确认写入演示出货单。',
        'ai',
        undefined,
        targetSessionId,
      )
      await options.refreshTasks()
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || '未知错误')
      await options.addAndSaveMessage(
        `AI 第一单启动失败：${detail}。新手任务已保留，可再次发送重试。`,
        'ai',
        undefined,
        targetSessionId,
      )
    }
    return true
  }

  return { tryStart }
}
