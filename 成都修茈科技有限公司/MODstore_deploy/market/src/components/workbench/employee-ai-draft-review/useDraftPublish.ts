/**
 * AI 制作草稿 · 清单装配与发布（由 EmployeeAiDraftReview.vue 原单文件机械迁出，行为不变）。
 */
import { ref } from 'vue'
import type { Ref } from 'vue'
import type { PipelineStatus } from '../../../composables/useEmployeeAiDraft'
import type { DraftForm } from './employeeDraftReviewHelpers'
import { authJsonHeaders } from './employeeDraftReviewHelpers'

interface UseDraftPublishCtx {
  status: PipelineStatus
  draft: Ref<DraftForm>
  v2Override: Ref<Record<string, unknown>>
  canPublish: Ref<boolean>
  emitPublished: (modId: string) => void
}

export function useDraftPublish(ctx: UseDraftPublishCtx) {
  const { status, draft, v2Override, canPublish, emitPublished } = ctx

  const publishLoading = ref(false)
  const publishError = ref('')

  function _buildManifest(): Record<string, unknown> {
    const base = JSON.parse(JSON.stringify(status.manifest || {})) as Record<string, unknown>
    base.id = draft.value.id || base.id
    base.name = draft.value.name || base.name
    base.description = draft.value.scenario || base.description
    base.industry = draft.value.industry || base.industry

    const emp = (base.employee as Record<string, unknown>) || {}
    emp.label = draft.value.name || String(emp.label || '')
    base.employee = emp

    const v2 = (base.employee_config_v2 as Record<string, unknown>) || {}
    const identity = (v2.identity as Record<string, unknown>) || {}
    identity.id = draft.value.id
    identity.name = draft.value.name
    identity.description = draft.value.scenario
    v2.identity = identity

    if (v2Override.value.perception) v2.perception = v2Override.value.perception
    if (v2Override.value.memory) v2.memory = v2Override.value.memory
    if (v2Override.value.actions) v2.actions = v2Override.value.actions

    const cog = (v2.cognition as Record<string, unknown>) || {}
    const agent = (cog.agent as Record<string, unknown>) || {}
    agent.system_prompt = draft.value.systemPrompt
    cog.agent = agent
    if (draft.value.skills.length) {
      cog.skills = draft.value.skills.map((s) => ({
        name: s.name,
        brief: s.brief,
        unverified: s.unverified,
      }))
    }
    v2.cognition = cog

    const meta = (v2.metadata as Record<string, unknown>) || {}
    if (draft.value.skills.length) {
      meta.suggested_skills = draft.value.skills.map((s) => ({
        name: s.name,
        brief: s.brief,
        unverified: s.unverified,
      }))
    }
    if (draft.value.pricingCny > 0 || draft.value.pricingTier !== 'free') {
      meta.suggested_pricing = {
        tier: draft.value.pricingTier,
        cny: draft.value.pricingCny,
        period: draft.value.pricingPeriod,
      }
    }
    v2.metadata = meta
    base.employee_config_v2 = v2

    return base
  }

  async function publish() {
    if (!canPublish.value) return
    publishLoading.value = true
    publishError.value = ''
    try {
      const manifest = _buildManifest()
      const res = await fetch('/api/mods/ai-scaffold', {
        method: 'POST',
        headers: authJsonHeaders(),
        body: JSON.stringify({
          brief: `${draft.value.role}: ${draft.value.scenario}`,
          suggested_id: draft.value.id,
          replace: true,
          _manifest_override: manifest,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body?.detail || body?.error || `HTTP ${res.status}`)
      }
      const data = await res.json()
      const modId = data?.id || draft.value.id
      emitPublished(String(modId))
    } catch (e: unknown) {
      publishError.value = `发布失败: ${(e as Error)?.message || String(e)}`
    } finally {
      publishLoading.value = false
    }
  }

  function openInAuthoring() {
    if (!canPublish.value) return
    const id = draft.value.id
    if (!id) return
    // Persist full manifest so WorkbenchShell can hydrate without an API round-trip
    const manifest = _buildManifest()
    sessionStorage.setItem('modstore_employee_prefill', JSON.stringify(manifest))
    window.open(`/market/#/workbench/shell/employee/${encodeURIComponent(id)}?fromAi=1`, '_blank')
  }

  return { publishLoading, publishError, publish, openInAuthoring }
}
