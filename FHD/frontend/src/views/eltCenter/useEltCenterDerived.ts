/**
 * 数据对接中心派生计算属性（拆分自 views/EltCenterView.vue，行为保持一致）。
 */
import { computed } from 'vue'
import type { EltAction, EltRunRow } from '@/api/elt'
import type { EltCenterState } from './eltCenterState'
import { resultNeedsVerification, targetOperation } from './eltCenterShared'

export interface EltCenterDerivedDeps {
  state: EltCenterState
}

export function createEltCenterDerived({ state }: EltCenterDerivedDeps) {
  const { capabilities, currentRun, targetType, runRows, validRowsOnly, allowedUpdateFields } = state

  const currentCapability = computed(() => {
    const target = currentRun.value?.target_type || targetType.value
    return capabilities.value?.targets.find((item) => item.type === target)
  })
  const updatableFields = computed(() => currentCapability.value?.fields.filter((field) => field.updatable) || [])
  function allowedActionsForRow(row: EltRunRow): EltAction[] {
    const actions = currentCapability.value?.supported_actions || ['new', 'skip']
    return [...new Set([...actions, 'skip'])].filter((item): item is EltAction => {
      if (item === 'error') return false
      if (item === 'update' && (!row.match_ref || allowedUpdateFields.value.length === 0)) return false
      if (item === 'new' && (row.match_ref || row.suggested_action === 'skip')) return false
      return true
    })
  }
  const bulkNewRows = computed(() =>
    runRows.value.filter((row) => row.validation_issues.length === 0 && !row.match_ref && row.suggested_action !== 'skip'),
  )
  const draftChanged = computed(() => {
    if (!currentRun.value) return false
    try {
      const mappings = state.editableMappings.value.map((mapping, index) => ({
        ...mapping, transforms: JSON.parse(state.mappingUiTransformJson[String(index)] || '[]'),
      }))
      const draft = currentRun.value.draft
      return JSON.stringify(mappings) !== JSON.stringify(draft.field_mappings || [])
        || JSON.stringify(allowedUpdateFields.value) !== JSON.stringify(draft.allowed_update_fields || [])
        || state.ocrConfirmed.value !== Boolean(draft.ocr_confirmed)
    } catch {
      return true
    }
  })
  const canExecute = computed(() => {
    if (!currentRun.value || currentRun.value.status !== 'preview_ready') return false
    if (!runRows.value.length || state.rowPage.value < 1 || (state.rowPage.value - 1) * 50 >= state.rowTotal.value) return false
    if (draftChanged.value) return false
    if (!currentRun.value.preview_revision || currentRun.value.preview_revision !== state.reviewedPreviewRevision.value) return false
    if (currentRun.value.summary.error && !validRowsOnly.value) return false
    return currentRun.value.summary.new + currentRun.value.summary.update > 0
  })
  const canReplay = computed(() => {
    const run = currentRun.value
    const snapshot = run?.details.source_snapshot
    return Boolean(run && !resultNeedsVerification(run) && ['preview_ready', 'completed', 'failed', 'interrupted'].includes(run.status) &&
      snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot) && (snapshot as Record<string, unknown>).version === 1)
  })
  const operation = computed(() => targetOperation(currentRun.value?.target_type || targetType.value))
  const canRetry = computed(() => Boolean(currentRun.value && ['failed', 'interrupted'].includes(currentRun.value.status) &&
    !currentRun.value.rollback_status && !resultNeedsVerification(currentRun.value)))
  const sourceColumns = computed(() => {
    const headers = currentRun.value?.source_features.headers
    return [...new Set([
      ...(Array.isArray(headers) ? headers.filter((item): item is string => typeof item === 'string') : []),
      ...runRows.value.flatMap(row => Object.keys(row.source)),
      ...(currentRun.value?.draft.field_mappings || []).map(mapping => mapping.source),
    ])].filter(Boolean)
  })
  const sourceSheets = computed(() => [...new Set(runRows.value.map(row => row.source_sheet))])
  const rowPageCount = computed(() => Math.max(1, Math.ceil(state.rowTotal.value / 50)))
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
    if (currentRun.value.target_type === 'template_review') return currentRun.value.status === 'template_review_saved'
      ? '模板已保存；知识库与业务写入结果请到审批工作台核对。' : '请回到导入核对候选模板，确认使用后才会保存并入库。'
    const summary = currentRun.value.summary
    if (currentRun.value.rollback_status === 'completed') {
      const rollback = currentRun.value.receipt.rollback as { rows?: number } | undefined
      return `已撤销本次写入；已回退 ${rollback?.rows ?? summary.executed} 行`
    }
    if (currentRun.value.status === 'completed') {
      return `${operation.value.count} ${summary.executed} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
    }
    if (['failed', 'interrupted', 'outcome_unknown'].includes(currentRun.value.status) || resultNeedsVerification(currentRun.value)) {
      return `已确认${operation.value.verb} ${summary.executed} 行；计划新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
    }
    return `计划处理 ${plannedBusinessRows.value} 行；新增 ${summary.new}、更新 ${summary.update}、跳过 ${summary.skip}`
  })
  const recoveryMessage = computed(() => {
    const run = currentRun.value
    if (!run || run.rollback_status === 'completed') return ''
    if (resultNeedsVerification(run)) return '结果尚未确认，请先核对业务库或外部系统，并联系管理员处理；暂勿再次执行或撤销。'
    if (!['failed', 'interrupted'].includes(run.status)) return ''
    const remaining = Math.max(0, run.summary.new + run.summary.update - run.summary.executed)
    return `其余计划处理的 ${remaining} 行结果待核对，不能直接认定为未处理。请先核对实际数据；重新校验只生成预演，仍需再次审核确认。`
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
    draftChanged,
    canExecute,
    canReplay,
    canRetry,
    operation,
    recoveryMessage,
    sourceColumns,
    sourceSheets,
    rowPageCount,
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

export type EltCenterDerived = ReturnType<typeof createEltCenterDerived>
