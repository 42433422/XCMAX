import agentRunsApi from '@/api/agentRuns'
import { bindPendingFirstAiTaskRun, isFirstAiTaskPending } from '@/constants/productFlow'
import type { ChatLocalScope } from './chat-orchestration/chatOrchestrationShared'
import type { ChatMessageExtras } from './useChatMessages'

interface UseOnboardingFirstOrderRunOptions {
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
  async function tryStart(message: string, scope: ChatLocalScope): Promise<boolean> {
    if (!isFirstOrderPrompt(message)) return false
    if (!scope.isCurrent()) return true
    const targetSessionId = scope.sessionId
    await options.saveMessage('user', message, targetSessionId)
    if (!scope.isCurrent()) return true
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
      if (!scope.isCurrent()) {
        if (scope.isOwnerCurrent()) await options.saveMessage('ai', runId ? `新手第一单已创建任务 ${runId}。请到原任务工作区核对状态；停止回复不会撤销已执行操作。` : '新手第一单启动结果未确认，请到任务工作区核对，勿重复提交。', targetSessionId)
        return true
      }
      if (!runId || !bindPendingFirstAiTaskRun(runId, message)) {
        throw new Error('未能绑定新手第一单任务')
      }
      await options.addAndSaveMessage(
        'AI 第一单已进入任务工作区。客户和商品查询完成后，请在任务卡片中确认写入演示出货单。',
        'ai',
        undefined,
        targetSessionId,
      )
      if (scope.isCurrent()) await options.refreshTasks()
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error || '未知错误')
      if (!scope.isOwnerCurrent()) return true
      if (!scope.isCurrent()) {
        await options.saveMessage('ai', `AI 第一单启动返回错误：${detail}。请先核对任务状态，勿重复提交。`, targetSessionId)
        return true
      }
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
