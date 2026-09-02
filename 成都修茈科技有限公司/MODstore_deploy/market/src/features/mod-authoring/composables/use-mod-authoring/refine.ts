// AI 管线建议与 System Prompt 优化（原单体实现原样迁移）。
import { computed, ref } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import { api } from '@/api'
import { asLooseRecord } from '../../types'
import type { ModAuthoringData } from './types'
import type { Flash } from './core'

export interface RefineDeps {
  modData: Ref<ModAuthoringData | null>
  modId: ComputedRef<string>
  flash: Flash
  reload: () => Promise<void>
}

export function createRefine(deps: RefineDeps) {
  const { modData, modId, flash, reload } = deps

  // ── AI pipeline suggestions (读自 employee_config_v2.metadata) ────────────────
  const suggestedSkills = computed<Array<{ name: string; brief: string }>>(() => {
    const meta = asLooseRecord(modData.value?.manifest?.employee_config_v2?.metadata)
    return Array.isArray(meta.suggested_skills) ? (meta.suggested_skills as Array<{ name: string; brief: string }>) : []
  })

  const suggestedPricing = computed<{
    tier: string
    cny: number
    period: string
    reasoning?: string
  } | null>(() => {
    const meta = asLooseRecord(modData.value?.manifest?.employee_config_v2?.metadata)
    return meta.suggested_pricing && typeof meta.suggested_pricing === 'object'
      ? (meta.suggested_pricing as {
          tier: string
          cny: number
          period: string
          reasoning?: string
        })
      : null
  })

  // ── Refine system prompt ──────────────────────────────────────────────────────
  const refinePromptLoading = ref(false)
  const refinePromptError = ref('')
  const refinePromptDiff = ref('')

  async function handleRefineSystemPrompt() {
    const v2 = asLooseRecord(modData.value?.manifest?.employee_config_v2)
    const cognition = asLooseRecord(v2.cognition)
    const agent = asLooseRecord(cognition.agent)
    const currentPrompt = String(agent.system_prompt || '')
    if (!currentPrompt) {
      flash('请先在配置中填写 system_prompt', false)
      return
    }
    const instruction = window.prompt('优化说明（可选）', '') || ''
    if (!instruction.trim()) return
    refinePromptLoading.value = true
    refinePromptError.value = ''
    refinePromptDiff.value = ''
    try {
      const res = await api.refineSystemPrompt({
        current_prompt: currentPrompt,
        instruction,
        role_context: `${modData.value?.manifest?.name || ''} - ${modData.value?.manifest?.description || ''}`,
      })
      if (!res?.improved_prompt) throw new Error('未收到优化结果')
      // Write back into manifest
      const mf = JSON.parse(JSON.stringify(modData.value?.manifest || {}))
      if (!mf.employee_config_v2) mf.employee_config_v2 = {}
      if (!mf.employee_config_v2.cognition) mf.employee_config_v2.cognition = {}
      if (!mf.employee_config_v2.cognition.agent) mf.employee_config_v2.cognition.agent = {}
      mf.employee_config_v2.cognition.agent.system_prompt = res.improved_prompt
      await api.putModManifest(modId.value, mf)
      refinePromptDiff.value = res.diff_explanation || ''
      flash('System Prompt 已优化并保存', true)
      await reload()
    } catch (e) {
      refinePromptError.value = (e as Error)?.message || String(e)
      flash(`Prompt 优化失败: ${refinePromptError.value}`, false)
    } finally {
      refinePromptLoading.value = false
    }
  }

  function applyPricingSuggestion() {
    if (!suggestedPricing.value) return
    // The pricing suggestion shows up in the guide; this helper opens the publishing modal
    // if it exists, or just copies the suggestion to clipboard as a hint.
    const p = suggestedPricing.value
    const text = `建议定价：${p.tier} ¥${p.cny}/${p.period === 'month' ? '月' : p.period === 'year' ? '年' : '次'}`
    navigator.clipboard?.writeText(text).then(
      () => flash('已复制定价建议', true),
      () => flash(text, true),
    )
  }
  // ─────────────────────────────────────────────────────────────────────────────

  return {
    suggestedSkills,
    suggestedPricing,
    refinePromptLoading,
    refinePromptError,
    refinePromptDiff,
    handleRefineSystemPrompt,
    applyPricingSuggestion,
  }
}
