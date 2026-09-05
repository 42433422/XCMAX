/**
 * 数据对接中心字段映射动作（拆分自 views/EtlCenterView.vue，行为保持一致）：
 * 保存映射、常用转换、样例查询与目标字段查找。
 */
import type { ComputedRef } from 'vue'
import type { EtlTargetCapability } from '@/api/etl'
import { etlApi } from '@/api/etl'
import type { EtlCenterState } from './etlCenterState'

export interface EtlCenterDraftActionsDeps {
  state: EtlCenterState
  currentCapability: ComputedRef<EtlTargetCapability | undefined>
  syncDraft: () => void
  loadRows: () => Promise<void>
  schedulePoll: () => void
  refreshRuns: () => Promise<void>
}

export function createEtlCenterDraftActions({
  state,
  currentCapability,
  syncDraft,
  loadRows,
  schedulePoll,
  refreshRuns,
}: EtlCenterDraftActionsDeps) {
  const { busy, pageError, currentRun, activeTab, runRows, editableMappings, mappingUiTransform, mappingUiTransformJson, allowedUpdateFields, ocrConfirmed } =
    state

  async function saveMappings() {
    if (!currentRun.value) return
    busy.value = true
    pageError.value = ''
    try {
      const mappings = editableMappings.value.map((mapping, index) => {
        const parsed = JSON.parse(mappingUiTransformJson[String(index)] || '[]')
        if (!Array.isArray(parsed)) throw new Error(`${mapping.target} 的转换规则必须是 JSON 数组`)
        return { ...mapping, transforms: parsed }
      })
      currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
        field_mappings: mappings,
        allowed_update_fields: allowedUpdateFields.value,
        ocr_confirmed: ocrConfirmed.value,
      })
      syncDraft()
      activeTab.value = currentRun.value.status === 'previewing' ? 'upload' : 'preview'
      if (currentRun.value.status === 'preview_ready') await loadRows()
      schedulePoll()
      await refreshRuns()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '映射保存失败'
    } finally {
      busy.value = false
    }
  }

  function targetField(key: string) {
    return currentCapability.value?.fields.find((field) => field.key === key)
  }

  function applyCommonTransform(target: string) {
    const op = mappingUiTransform[target]
    if (op === 'custom') return
    mappingUiTransformJson[target] = JSON.stringify(op ? [{ op }] : [])
  }

  function mappingSample(source: string): string {
    if (!source) return '—'
    const value = runRows.value.find((row) => row.source[source] != null)?.source[source]
    return value == null ? '—' : String(value).slice(0, 80)
  }

  return {
    saveMappings,
    targetField,
    applyCommonTransform,
    mappingSample,
  }
}

export type EtlCenterDraftActions = ReturnType<typeof createEtlCenterDraftActions>
