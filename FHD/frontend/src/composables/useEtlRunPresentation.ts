import { computed, type Ref } from 'vue'
import type { EtlAction, EtlCapabilities, EtlRun, EtlRunRow } from '@/api/etl'
import {
  documentTables,
  documentTypeLabel,
  hasBlockingRowIssues,
} from '@/utils/etlCenterPresentation'

interface EtlRunPresentationOptions {
  capabilities: Ref<EtlCapabilities | null>
  currentRun: Ref<EtlRun | null>
  targetType: Ref<string>
  runRows: Ref<EtlRunRow[]>
  allowedUpdateFields: Ref<string[]>
  validRowsOnly: Ref<boolean>
  selectedShipmentTemplateRegionId: Ref<string>
}

export function useEtlRunPresentation(options: EtlRunPresentationOptions) {
  const {
    capabilities,
    currentRun,
    targetType,
    runRows,
    allowedUpdateFields,
    validRowsOnly,
    selectedShipmentTemplateRegionId,
  } = options
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
  const bulkNewRows = computed(() => runRows.value.filter((row) => (
    !hasBlockingRowIssues(row)
    && !row.match_ref
    && row.suggested_action !== 'skip'
  )))
  const documentUnderstanding = computed<Record<string, unknown> | null>(() => {
    const value = currentRun.value?.source_features?.document_understanding
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null
  })
  const understoodDocuments = computed<Array<Record<string, unknown>>>(() => {
    const value = documentUnderstanding.value?.documents
    return Array.isArray(value)
      ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : []
  })
  const sheetInventory = computed<Array<Record<string, unknown>>>(() => {
    const detailsValue = currentRun.value?.details?.sheet_inventory
    const understandingValue = documentUnderstanding.value?.sheet_inventory
    const value = Array.isArray(detailsValue) ? detailsValue : understandingValue
    return Array.isArray(value)
      ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : []
  })
  const documentRoutes = computed<Array<Record<string, unknown>>>(() => {
    const value = currentRun.value?.details?.document_routes
    return Array.isArray(value)
      ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : []
  })
  const workbookRootRunId = computed(() => String(currentRun.value?.details?.workbook_root_run_id || '').trim())
  const hasPendingDocumentRoutes = computed(() => documentRoutes.value.some((route) => (
    ['planned', 'queued', 'previewing'].includes(String(route.status || ''))
  )))
  const llmPlanningText = computed(() => {
    const document = documentUnderstanding.value?.llm
    const structure = currentRun.value?.source_features?.llm_structure
    const mapping = currentRun.value?.source_features?.llm_mapping
    const entries = [document, structure, mapping].filter(
      (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object',
    )
    if (entries.some((item) => item.used_llm === true && item.degraded !== true)) {
      return '软件 LLM 已完成单据理解和字段建议'
    }
    if (entries.some((item) => item.degraded === true)) return 'LLM 已降级，当前结果由确定性规则生成'
    return '当前结构由确定性规则识别'
  })
  const documentSummaryText = computed(() => {
    const original = String(documentUnderstanding.value?.summary || '').trim()
    const englishWords = original.match(/[A-Za-z]{3,}/g) || []
    if (/[\u3400-\u9fff]/u.test(original) && englishWords.length < 3) return original
    if (!understoodDocuments.value.length) return llmPlanningText.value
    const labels = [...new Set(understoodDocuments.value.map((document) => (
      documentTypeLabel(document.document_type)
    )))]
    const tableCount = understoodDocuments.value.reduce(
      (total, document) => total + documentTables(document).length,
      0,
    )
    return `识别为${labels.join('、')}，共 ${understoodDocuments.value.length} 张单；已定位单据头和 ${tableCount} 个明细表，等待人工确认。`
  })
  const requiresDocumentConfirmation = computed(() => (
    documentUnderstanding.value?.requires_confirmation === true
  ))
  const canReanalyzeDocumentWithLlm = computed(() => {
    const llm = documentUnderstanding.value?.llm
    return (
      currentRun.value?.status === 'preview_ready'
      && Boolean(
        llm
        && typeof llm === 'object'
        && !Array.isArray(llm)
        && (llm as Record<string, unknown>).degraded === true,
      )
    )
  })
  const sourceFieldOptions = computed(() => {
    const headers = Array.isArray(currentRun.value?.source_features?.headers)
      ? currentRun.value.source_features.headers.map((item) => String(item || '')).filter(Boolean)
      : []
    const rowHeaders = runRows.value.flatMap((row) => Object.keys(row.source || {}))
    return [...new Set([...headers, ...rowHeaders])]
  })
  const canExecute = computed(() => {
    if (!currentRun.value || currentRun.value.status !== 'preview_ready') return false
    if (requiresDocumentConfirmation.value && !currentRun.value.draft.document_confirmed) return false
    if (currentRun.value.summary.error && !validRowsOnly.value) return false
    return currentRun.value.summary.new + currentRun.value.summary.update > 0
  })
  const summaryCards = computed(() => [
    { action: 'new', label: '新增', count: currentRun.value?.summary.new || 0 },
    { action: 'update', label: '更新', count: currentRun.value?.summary.update || 0 },
    { action: 'skip', label: '跳过', count: currentRun.value?.summary.skip || 0 },
    { action: 'error', label: '需确认', count: currentRun.value?.summary.error || 0 },
  ])
  const savedShipmentTemplate = computed<Record<string, unknown> | null>(() => {
    const candidate = currentRun.value?.details?.shipment_document_template
    return candidate && typeof candidate === 'object' && !Array.isArray(candidate)
      ? candidate as Record<string, unknown>
      : null
  })
  const savedShipmentTemplateName = computed(() => String(savedShipmentTemplate.value?.name || '').trim())
  const shipmentTemplateCandidates = computed<Array<Record<string, unknown>>>(() => {
    const listed = currentRun.value?.source_features?.shipment_template_candidates
    if (Array.isArray(listed)) {
      return listed.filter(
        (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item),
      )
    }
    const legacy = currentRun.value?.source_features?.shipment_template_candidate
    return legacy && typeof legacy === 'object' && !Array.isArray(legacy)
      ? [legacy as Record<string, unknown>]
      : []
  })
  const shipmentTemplateCandidate = computed<Record<string, unknown> | null>(() => {
    const selected = shipmentTemplateCandidates.value.find(
      (candidate) => String(candidate.source_region_id || '') === selectedShipmentTemplateRegionId.value,
    )
    return selected || shipmentTemplateCandidates.value[0] || null
  })
  const shipmentTemplateCandidateName = computed(() => String(shipmentTemplateCandidate.value?.name || '').trim())
  const linkedCustomerProductPreview = computed<Record<string, unknown> | null>(() => {
    const linked = currentRun.value?.details?.linked_customer_products_preview
    return linked && typeof linked === 'object' && !Array.isArray(linked)
      ? linked as Record<string, unknown>
      : null
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
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null
  })
  const detectedRegions = computed<Array<Record<string, unknown>>>(() => {
    const value = currentRun.value?.source_features?.regions
    return Array.isArray(value)
      ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : []
  })
  const workbookSheetPlan = computed<Array<Record<string, unknown>>>(() => {
    const value = currentRun.value?.source_features?.sheet_plan
    return Array.isArray(value)
      ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : []
  })
  const latestRecordSelection = computed<Record<string, unknown> | null>(() => {
    const value = currentRun.value?.source_features?.latest_record_selection
    return value && typeof value === 'object' && !Array.isArray(value)
      ? value as Record<string, unknown>
      : null
  })

  return {
    currentCapability,
    updatableFields,
    allowedActionsForRow,
    bulkNewRows,
    documentUnderstanding,
    understoodDocuments,
    sheetInventory,
    documentRoutes,
    workbookRootRunId,
    hasPendingDocumentRoutes,
    documentSummaryText,
    requiresDocumentConfirmation,
    canReanalyzeDocumentWithLlm,
    sourceFieldOptions,
    canExecute,
    summaryCards,
    savedShipmentTemplate,
    savedShipmentTemplateName,
    shipmentTemplateCandidates,
    shipmentTemplateCandidate,
    shipmentTemplateCandidateName,
    linkedCustomerProductPreview,
    linkedCustomerNames,
    runOutcomeText,
    regionSummary,
    detectedRegions,
    workbookSheetPlan,
    latestRecordSelection,
    llmPlanningText,
  }
}
