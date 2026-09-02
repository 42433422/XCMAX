/**
 * 数据对接中心派生计算属性（拆分自 views/EtlCenterView.vue，行为保持一致）。
 */
import { computed } from 'vue'
import type { EtlAction, EtlRunRow } from '@/api/etl'
import type { EtlCenterState } from './etlCenterState'

export interface EtlCenterDerivedDeps {
  state: EtlCenterState
}

export function createEtlCenterDerived({ state }: EtlCenterDerivedDeps) {
  const { capabilities, currentRun, targetType, runRows, validRowsOnly, allowedUpdateFields } = state

  const currentCapability = computed(() => {
    const target = currentRun.value?.target_type || targetType.value
    return capabilities.value?.targets.find((item) => item.type === target)
  })
  const updatableFields = computed(() => currentCapability.value?.fields.filter((field) => field.updatable) || [])
  function allowedActionsForRow(row: EtlRunRow): EtlAction[] {
    const actions = currentCapability.value?.supported_actions || ['new', 'skip']
    return [...new Set([...actions, 'skip'])].filter((item): item is EtlAction => {
      if (item === 'error') return false
      if (item === 'update' && (!row.match_ref || allowedUpdateFields.value.length === 0)) return false
      if (item === 'new' && (row.match_ref || row.suggested_action === 'skip')) return false
      return true
    })
  }
  const bulkNewRows = computed(() =>
    runRows.value.filter((row) => row.validation_issues.length === 0 && !row.match_ref && row.suggested_action !== 'skip'),
  )
  const canExecute = computed(() => {
    if (!currentRun.value || currentRun.value.status !== 'preview_ready') return false
    if (currentRun.value.summary.error && !validRowsOnly.value) return false
    return currentRun.value.summary.new + currentRun.value.summary.update > 0
  })
  const summaryCards = computed(() => [
    { action: 'new', label: '新增', count: currentRun.value?.summary.new || 0 },
    { action: 'update', label: '更新', count: currentRun.value?.summary.update || 0 },
    { action: 'skip', label: '跳过', count: currentRun.value?.summary.skip || 0 },
    { action: 'error', label: '错误', count: currentRun.value?.summary.error || 0 },
  ])
  const savedShipmentTemplate = computed<Record<string, unknown> | null>(() => {
    const candidate = currentRun.value?.details?.shipment_document_template
    return candidate && typeof candidate === 'object' && !Array.isArray(candidate) ? (candidate as Record<string, unknown>) : null
  })
  const savedShipmentTemplateName = computed(() => String(savedShipmentTemplate.value?.name || '').trim())
  const shipmentTemplateCandidates = computed<Array<Record<string, unknown>>>(() => {
    const listed = currentRun.value?.source_features?.shipment_template_candidates
    if (Array.isArray(listed)) {
      return listed.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    }
    const legacy = currentRun.value?.source_features?.shipment_template_candidate
    return legacy && typeof legacy === 'object' && !Array.isArray(legacy) ? [legacy as Record<string, unknown>] : []
  })
  const shipmentTemplateCandidate = computed<Record<string, unknown> | null>(() => {
    const selected = shipmentTemplateCandidates.value.find(
      (candidate) => String(candidate.source_region_id || '') === state.selectedShipmentTemplateRegionId.value,
    )
    return selected || shipmentTemplateCandidates.value[0] || null
  })
  const shipmentTemplateCandidateName = computed(() => String(shipmentTemplateCandidate.value?.name || '').trim())
  const linkedCustomerProductPreview = computed<Record<string, unknown> | null>(() => {
    const linked = currentRun.value?.details?.linked_customer_products_preview
    return linked && typeof linked === 'object' && !Array.isArray(linked) ? (linked as Record<string, unknown>) : null
  })
  const linkedCustomerNames = computed(() => {
    const names = runRows.value.map((row) => String(row.normalized.customer_name || '').trim()).filter(Boolean)
    return [...new Set(names)]
  })
  const plannedBusinessRows = computed(() => {
    if (!currentRun.value) return 0
    return currentRun.value.summary.new + currentRun.value.summary.update + currentRun.value.summary.skip
  })
  const runOutcomeText = computed(() => {
    if (!currentRun.value) return ''
    const summary = currentRun.value.summary
    if (currentRun.value.status === 'completed') {
      return `已写入 ${summary.executed} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
    }
    return `计划处理 ${plannedBusinessRows.value} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
  })
  const regionSummary = computed<Record<string, unknown> | null>(() => {
    const value = currentRun.value?.source_features?.region_summary
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
  })
  const detectedRegions = computed<Array<Record<string, unknown>>>(() => {
    const value = currentRun.value?.source_features?.regions
    return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
  })
  const workbookSheetPlan = computed<Array<Record<string, unknown>>>(() => {
    const value = currentRun.value?.source_features?.sheet_plan
    return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object') : []
  })
  const latestRecordSelection = computed<Record<string, unknown> | null>(() => {
    const value = currentRun.value?.source_features?.latest_record_selection
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
  })
  const llmPlanningText = computed(() => {
    const structure = currentRun.value?.source_features?.llm_structure
    const mapping = currentRun.value?.source_features?.llm_mapping
    const entries = [structure, mapping].filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    if (entries.some((item) => item.used_llm === true && item.degraded !== true)) return '软件 LLM 已参与结构或字段建议'
    if (entries.some((item) => item.degraded === true)) return 'LLM 已降级，当前结果由确定性规则生成'
    return '当前结构由确定性规则识别'
  })

  return {
    currentCapability,
    updatableFields,
    allowedActionsForRow,
    bulkNewRows,
    canExecute,
    summaryCards,
    savedShipmentTemplate,
    savedShipmentTemplateName,
    shipmentTemplateCandidates,
    shipmentTemplateCandidate,
    shipmentTemplateCandidateName,
    linkedCustomerProductPreview,
    linkedCustomerNames,
    plannedBusinessRows,
    runOutcomeText,
    regionSummary,
    detectedRegions,
    workbookSheetPlan,
    latestRecordSelection,
    llmPlanningText,
  }
}

export type EtlCenterDerived = ReturnType<typeof createEtlCenterDerived>
