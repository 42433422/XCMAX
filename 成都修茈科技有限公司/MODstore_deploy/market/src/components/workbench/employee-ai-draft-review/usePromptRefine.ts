/**
 * AI 制作草稿 · System Prompt AI 优化（由 EmployeeAiDraftReview.vue 原单文件机械迁出，行为不变）。
 */
import { ref } from 'vue'
import type { Ref } from 'vue'
import type { DraftForm } from './employeeDraftReviewHelpers'
import { authJsonHeaders } from './employeeDraftReviewHelpers'

export function usePromptRefine(draft: Ref<DraftForm>) {
  const refineLoading = ref(false)
  const refineError = ref('')
  const refineDiff = ref('')
  const _refineInstruction = ref('')

  async function openRefinePrompt() {
    const instruction = window.prompt('优化指令（例如：增加拒绝服务的边界说明）', '')
    if (!instruction) return
    refineLoading.value = true
    refineError.value = ''
    refineDiff.value = ''
    try {
      const res = await fetch('/api/workbench/employee-ai/refine-prompt', {
        method: 'POST',
        headers: authJsonHeaders(),
        body: JSON.stringify({
          current_prompt: draft.value.systemPrompt,
          instruction,
          role_context: `${draft.value.role} - ${draft.value.scenario}`,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || `HTTP ${res.status}`)
      }
      const data = await res.json()
      draft.value.systemPrompt = data.improved_prompt
      refineDiff.value = data.diff_explanation || ''
    } catch (e: unknown) {
      refineError.value = `优化失败: ${(e as Error)?.message || String(e)}`
    } finally {
      refineLoading.value = false
    }
  }

  return { refineLoading, refineError, refineDiff, openRefinePrompt }
}
