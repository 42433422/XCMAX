/**
 * 客来来 AI 沟通副驾驶与跟进任务（拆分自 components/im/KellaiCustomerInbox.vue，行为保持一致）：
 * 草稿生成与审批、复制草稿、跟进任务创建与决策、指标计算。
 */
import { computed, ref } from 'vue'
import type { Ref } from 'vue'
import kellaiBindingApi, {
  type KellaiConversationMessage,
  type KellaiCopilotDraft,
  type KellaiFollowUpMetrics,
  type KellaiFollowUpTask,
} from '@/api/kellaiBinding'

export interface UseKellaiCopilotDeps {
  activeCustomerId: Ref<number | null>
  messages: Ref<KellaiConversationMessage[]>
  error: Ref<string>
}

export function useKellaiCopilot({ activeCustomerId, messages, error }: UseKellaiCopilotDeps) {
  const copilotDraft = ref<KellaiCopilotDraft | null>(null)
  const followUpTasks = ref<KellaiFollowUpTask[]>([])
  const followUpMetrics = ref<KellaiFollowUpMetrics | null>(null)
  const copilotBusy = ref(false)
  const taskBusy = ref(false)
  const copiedDraft = ref(false)

  const currentDraftTask = computed(() => {
    const draftId = copilotDraft.value?.draft_id
    if (!draftId) return null
    return followUpTasks.value.find((task) => task.source_draft_id === draftId) || null
  })

  /** loadMessages 成功后回填会话派生数据（与拆分前赋值顺序一致）。 */
  function applyConversationData(draft: KellaiCopilotDraft | null, tasks: KellaiFollowUpTask[], metrics: KellaiFollowUpMetrics | null): void {
    copilotDraft.value = draft
    followUpTasks.value = tasks
    followUpMetrics.value = metrics
    copiedDraft.value = false
  }

  /** 会话清空时的重置（不触碰 copiedDraft，与拆分前行为一致）。 */
  function resetConversationState(): void {
    copilotDraft.value = null
    followUpTasks.value = []
    followUpMetrics.value = null
  }

  function upsertFollowUpTask(task: KellaiFollowUpTask): void {
    const index = followUpTasks.value.findIndex((item) => item.task_id === task.task_id)
    if (index >= 0) followUpTasks.value.splice(index, 1, task)
    else followUpTasks.value.unshift(task)
    followUpMetrics.value = calculateFollowUpMetrics(followUpTasks.value)
  }

  function calculateFollowUpMetrics(tasks: KellaiFollowUpTask[]): KellaiFollowUpMetrics {
    const success = tasks.filter((task) => task.outcome_result === 'success').length
    const noResult = tasks.filter((task) => task.outcome_result === 'no_result').length
    const failedOutcomes = tasks.filter((task) => task.outcome_result === 'failed').length
    const evaluated = success + noResult + failedOutcomes
    return {
      total: tasks.length,
      open: tasks.filter((task) => task.status === 'open').length,
      completed: tasks.filter((task) => task.status === 'completed').length,
      failed: tasks.filter((task) => task.status === 'failed').length,
      cancelled: tasks.filter((task) => task.status === 'cancelled').length,
      outcomes: { success, no_result: noResult, failed: failedOutcomes },
      success_rate: evaluated ? success / evaluated : null,
    }
  }

  async function createFollowUpTask(): Promise<void> {
    if (!copilotDraft.value?.draft_id || currentDraftTask.value) return
    taskBusy.value = true
    error.value = ''
    try {
      const task = await kellaiBindingApi.createFollowUpTask(copilotDraft.value.draft_id)
      upsertFollowUpTask(task)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '跟进任务创建失败'
    } finally {
      taskBusy.value = false
    }
  }

  async function decideFollowUpTask(
    task: KellaiFollowUpTask,
    decision: 'complete' | 'cancel',
    outcomeResult: 'success' | 'no_result' | 'failed' | '',
  ): Promise<void> {
    taskBusy.value = true
    error.value = ''
    try {
      const updated = await kellaiBindingApi.decideFollowUpTask(
        task.task_id,
        decision,
        outcomeResult,
      )
      upsertFollowUpTask(updated)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '跟进任务更新失败'
    } finally {
      taskBusy.value = false
    }
  }

  async function generateCopilotDraft(): Promise<void> {
    if (!activeCustomerId.value || !messages.value.length) return
    copilotBusy.value = true
    copiedDraft.value = false
    error.value = ''
    try {
      copilotDraft.value = await kellaiBindingApi.generateDraft(activeCustomerId.value)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'AI 摘要与回复草稿生成失败'
    } finally {
      copilotBusy.value = false
    }
  }

  async function decideCopilotDraft(decision: 'approve' | 'reject'): Promise<void> {
    if (!copilotDraft.value?.draft_id) return
    copilotBusy.value = true
    error.value = ''
    try {
      copilotDraft.value = await kellaiBindingApi.decideDraft(copilotDraft.value.draft_id, decision)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '草稿审批失败'
    } finally {
      copilotBusy.value = false
    }
  }

  async function copyApprovedDraft(): Promise<void> {
    if (!copilotDraft.value?.reply_draft || copilotDraft.value.status !== 'approved_for_manual_send') return
    try {
      await navigator.clipboard.writeText(copilotDraft.value.reply_draft)
      copiedDraft.value = true
    } catch {
      error.value = '无法复制草稿，请手动选择文本复制'
    }
  }

  return {
    copilotDraft,
    followUpTasks,
    followUpMetrics,
    copilotBusy,
    taskBusy,
    copiedDraft,
    currentDraftTask,
    applyConversationData,
    resetConversationState,
    createFollowUpTask,
    decideFollowUpTask,
    generateCopilotDraft,
    decideCopilotDraft,
    copyApprovedDraft,
  }
}

export type KellaiCopilot = ReturnType<typeof useKellaiCopilot>
