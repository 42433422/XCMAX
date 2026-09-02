/**
 * AI 制作草稿 · 可编辑草稿表单（由 EmployeeAiDraftReview.vue 原单文件机械迁出，行为不变）。
 */
import { ref, watch } from 'vue'
import type { PipelineStages } from '../../../composables/useEmployeeAiDraft'
import type { DraftForm } from './employeeDraftReviewHelpers'

export function useDraftForm(stages: PipelineStages) {
  const draft = ref<DraftForm>({
    id: '',
    name: '',
    role: '',
    scenario: '',
    industry: '',
    complexity: 'medium',
    systemPrompt: '',
    pricingTier: 'free',
    pricingCny: 0,
    pricingPeriod: 'month',
    skills: [],
  })

  watch(
    () => stages.suggest_skills.data,
    (list) => {
      if (!list || !list.length) return
      draft.value.skills = list.map((s) => ({
        name: s.name,
        brief: s.brief,
        unverified: Boolean(s.unverified),
      }))
    },
    { immediate: true },
  )

  watch(
    () => stages.parse_intent.data,
    (d) => {
      if (!d) return
      draft.value.id = d.id
      draft.value.name = d.name
      draft.value.role = d.role
      draft.value.scenario = d.scenario
      draft.value.industry = d.industry
      draft.value.complexity = d.complexity
    },
    { immediate: true },
  )

  watch(
    () => stages.design_v2.data,
    (d) => {
      if (!d) return
      const agent = (d.cognition as Record<string, unknown>)?.agent as Record<string, unknown>
      if (agent?.system_prompt) draft.value.systemPrompt = String(agent.system_prompt)
    },
    { immediate: true },
  )

  watch(
    () => stages.suggest_pricing.data,
    (d) => {
      if (!d) return
      draft.value.pricingTier = d.tier
      draft.value.pricingCny = d.cny
      draft.value.pricingPeriod = d.period
    },
    { immediate: true },
  )

  return { draft }
}
