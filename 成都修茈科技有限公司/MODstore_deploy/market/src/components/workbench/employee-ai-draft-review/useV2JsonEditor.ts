/**
 * AI 制作草稿 · V2 JSON 内联编辑器（由 EmployeeAiDraftReview.vue 原单文件机械迁出，行为不变）。
 */
import { ref } from 'vue'
import type { PipelineStages } from '../../../composables/useEmployeeAiDraft'

export function useV2JsonEditor(stages: PipelineStages) {
  const jsonEditTarget = ref<string | null>(null)
  const jsonEditContent = ref('')
  const jsonEditError = ref('')
  const v2Override = ref<Record<string, unknown>>({})

  function editV2Json(field: 'perception' | 'memory' | 'actions') {
    const d = stages.design_v2.data
    if (!d) return
    jsonEditTarget.value = field
    const current = v2Override.value[field] ?? d[field]
    jsonEditContent.value = JSON.stringify(current, null, 2)
    jsonEditError.value = ''
  }

  function applyJsonEdit() {
    try {
      const parsed = JSON.parse(jsonEditContent.value)
      if (jsonEditTarget.value) {
        v2Override.value[jsonEditTarget.value] = parsed
      }
      jsonEditTarget.value = null
      jsonEditError.value = ''
    } catch (e: unknown) {
      jsonEditError.value = `JSON 格式错误: ${(e as Error)?.message}`
    }
  }

  return { jsonEditTarget, jsonEditContent, jsonEditError, v2Override, editV2Json, applyJsonEdit }
}
