<template src="./EtlCenterView.template.html"></template>
<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  etlApi,
  type EtlCapabilities,
  type EtlFieldMapping,
  type EtlRun,
  type EtlRunRow,
  type EtlTargetConfig,
  type EtlTemplate,
} from '@/api/etl'
import {
  batchFileStatusLabel,
  ignoredReasonLabel,
  useEtlFolderBatch,
} from '@/composables/useEtlFolderBatch'
import { useEtlRunActions } from '@/composables/useEtlRunActions'
import { useEtlRunPresentation } from '@/composables/useEtlRunPresentation'
import { useEtlTemplateSelection } from '@/composables/useEtlTemplateSelection'
import { tabForRunStatus, type EtlRunTab } from '@/utils/etlRunView'
import { ETL_FILE_ACCEPT, formatEtlBytes } from '@/utils/etlFileSelection'
import {
  actionLabel,
  actionReason,
  compactRecord,
  confidenceClass,
  diffText,
  documentHeaderFields,
  documentIssues,
  documentTables,
  documentTypeLabel,
  fileStructureLabel,
  formatTime,
  hasBlockingRowIssues,
  latestRecordSelectionText,
  ocrTableRow,
  rowAdviceReason,
  sheetPlanRows,
  sheetPlanStatusLabel,
  sheetRangeText,
  sheetRoleLabel,
  sheetStructureLabel,
  stageLabel,
  statusLabel,
} from '@/utils/etlCenterPresentation'

type TabId = EtlRunTab

const route = useRoute()
const router = useRouter()
const tabs: Array<{ id: TabId; step: string; label: string }> = [
  { id: 'upload', step: '1', label: '上传文件' },
  { id: 'mapping', step: '2', label: '字段映射' },
  { id: 'preview', step: '3', label: '预演确认' },
  { id: 'history', step: '4', label: '运行历史' },
]

const activeTab = ref<TabId>('upload')
const capabilities = ref<EtlCapabilities | null>(null)
const templates = ref<EtlTemplate[]>([])
const targetConfigs = ref<EtlTargetConfig[]>([])
const runs = ref<EtlRun[]>([])
const currentRun = ref<EtlRun | null>(null)
const targetType = ref('auto')
const targetConfigId = ref('')
const runRows = ref<EtlRunRow[]>([])
const rowPage = ref(1)
const rowTotal = ref(0)
const rowActionFilter = ref('')
const busy = ref(false)
const pageError = ref('')
const validRowsOnly = ref(false)
const editableMappings = ref<EtlFieldMapping[]>([])
const mappingUiTransform = reactive<Record<string, string>>({})
const mappingUiTransformJson = reactive<Record<string, string>>({})
const allowedUpdateFields = ref<string[]>([])
const ocrConfirmed = ref(false)
const documentConfirmed = ref(false)
const hasOcrRows = ref(false)
const showWebhookForm = ref(false)
const webhookDraft = reactive({ name: '', endpoint_url: '', headersJson: '{}', secret: '' })
const webhookTestMessage = ref('')
const shipmentTemplateMessage = ref('')
const shipmentTemplateName = ref('')
const personalTemplateName = ref('')
const customerProductPreviewMessage = ref('')
const selectedShipmentTemplateRegionId = ref('')
let pollTimer: ReturnType<typeof setTimeout> | null = null

const {
  templateSelection,
  compatibleTemplates,
  compatiblePresets,
  templateId,
  compatibilityPresetId,
  selectedCompatibilityPreset,
} = useEtlTemplateSelection({ capabilities, templates, targetType })

const {
  selectedFiles,
  ignoredFiles,
  selectionFolderName,
  fileInput,
  folderInput,
  maxFileBytes,
  selectedTotalBytes,
  incompatibleFiles,
  batchFinishedCount,
  batchFailedCount,
  batchProgress,
  selectionHeadline,
  startButtonText,
  onFileChange,
  onFolderChange,
  onDrop,
  clearSelection,
  removeSelectedFile,
  startPreview,
  openBatchRun,
} = useEtlFolderBatch({
  capabilities,
  targetType,
  templateId,
  compatibilityPresetId,
  targetConfigId,
  runs,
  currentRun,
  activeTab,
  busy,
  pageError,
  router,
  syncDraft,
  schedulePoll,
  loadRows,
})

const {
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
} = useEtlRunPresentation({
  capabilities,
  currentRun,
  targetType,
  runRows,
  allowedUpdateFields,
  validRowsOnly,
  selectedShipmentTemplateRegionId,
})

const {
  saveCurrentAsTemplate,
  saveCurrentAsShipmentTemplate,
  previewCustomerProductsFromShipment,
  refreshRuns,
  selectRun,
  openDocumentRoute,
  openWorkbookRoot,
  retryRun,
  reanalyzeDocumentWithLlm,
  rollbackRun,
  saveWebhook,
  testWebhook,
} = useEtlRunActions({
  currentRun,
  runs,
  templates,
  targetConfigs,
  targetType,
  targetConfigId,
  activeTab,
  rowPage,
  rowActionFilter,
  runRows,
  rowTotal,
  busy,
  pageError,
  personalTemplateName,
  shipmentTemplateName,
  shipmentTemplateMessage,
  customerProductPreviewMessage,
  showWebhookForm,
  webhookDraft,
  webhookTestMessage,
  shipmentTemplateCandidate,
  linkedCustomerProductPreview,
  workbookRootRunId,
  router,
  syncDraft,
  schedulePoll,
  loadRows,
})

async function bootstrap() {
  busy.value = true
  pageError.value = ''
  try {
    const [caps, templateRows, history, configs] = await Promise.all([
      etlApi.capabilities(),
      etlApi.templates(),
      etlApi.runs(),
      etlApi.targetConfigs(),
    ])
    capabilities.value = caps
    templates.value = templateRows
    runs.value = history
    targetConfigs.value = configs
    if (
      targetType.value !== 'auto'
      && !caps.targets.some((item) => item.type === targetType.value)
    ) {
      targetType.value = 'auto'
    }
    const requestedRun = String(route.query.run_id || '')
    if (requestedRun) {
      currentRun.value = await etlApi.run(requestedRun)
      syncDraft()
      activeTab.value = tabForRunStatus(currentRun.value.status)
      if (currentRun.value.status === 'preview_ready') await loadRows()
      schedulePoll()
    }
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '数据对接中心加载失败'
  } finally {
    busy.value = false
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  if (
    !currentRun.value
    || (
      !['queued', 'previewing', 'executing'].includes(currentRun.value.status)
      && !hasPendingDocumentRoutes.value
    )
  ) return
  pollTimer = setTimeout(async () => {
    if (!currentRun.value) return
    try {
      currentRun.value = await etlApi.run(currentRun.value.id)
      syncDraft()
      if (currentRun.value.status === 'preview_ready') {
        activeTab.value = 'preview'
        await loadRows()
        await refreshRuns()
      }
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '读取运行进度失败'
    }
    schedulePoll()
  }, 1200)
}

function syncDraft() {
  if (!currentRun.value) return
  const candidateIds = shipmentTemplateCandidates.value
    .map((candidate) => String(candidate.source_region_id || '').trim())
    .filter(Boolean)
  if (!candidateIds.includes(selectedShipmentTemplateRegionId.value)) {
    selectedShipmentTemplateRegionId.value = candidateIds[0] || ''
  }
  editableMappings.value = (currentRun.value.draft.field_mappings || []).map((item) => ({
    ...item,
    transforms: [...(item.transforms || [])],
  }))
  for (const [index, mapping] of editableMappings.value.entries()) {
    const firstOp = String(mapping.transforms?.[0]?.op || '')
    mappingUiTransform[String(index)] = ['', 'trim', 'number', 'date'].includes(firstOp) ? firstOp : 'custom'
    mappingUiTransformJson[String(index)] = JSON.stringify(mapping.transforms || [])
  }
  allowedUpdateFields.value = [...(currentRun.value.draft.allowed_update_fields || [])]
  ocrConfirmed.value = Boolean(currentRun.value.draft.ocr_confirmed)
  documentConfirmed.value = Boolean(currentRun.value.draft.document_confirmed)
}

async function saveMappings() {
  if (!currentRun.value) return
  busy.value = true
  try {
    const mappings = editableMappings.value.map((mapping, index) => {
      const mode = mappingUiTransform[String(index)]
      const parsed = mode === 'custom'
        ? JSON.parse(mappingUiTransformJson[String(index)] || '[]')
        : mode ? [{ op: mode }] : []
      if (!Array.isArray(parsed)) throw new Error(`${mapping.target} 的转换规则必须是 JSON 数组`)
      return { ...mapping, transforms: parsed }
    })
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      field_mappings: mappings,
      allowed_update_fields: allowedUpdateFields.value,
      ocr_confirmed: ocrConfirmed.value,
      document_confirmed: documentConfirmed.value,
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

async function confirmDocumentStructure() {
  if (!currentRun.value || !requiresDocumentConfirmation.value) return
  busy.value = true
  pageError.value = ''
  try {
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      document_confirmed: true,
    })
    syncDraft()
    if (currentRun.value.status === 'preview_ready') await loadRows()
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '单据结构确认失败'
  } finally {
    busy.value = false
  }
}

async function loadRows() {
  if (!currentRun.value || currentRun.value.total_rows === 0) {
    runRows.value = []
    rowTotal.value = 0
    return
  }
  const result = await etlApi.rows(currentRun.value.id, rowPage.value, 50, rowActionFilter.value)
  runRows.value = result.items
  rowTotal.value = result.total
  hasOcrRows.value = result.items.some((row) => row.provenance.ocr === true)
}

async function setRowActionFilter(action: string) {
  if (action === rowActionFilter.value) return
  rowActionFilter.value = action
  rowPage.value = 1
  await loadRows()
}

function onRowActionFilterChange(event: Event) {
  void setRowActionFilter((event.target as HTMLSelectElement).value)
}

async function overrideRow(row: EtlRunRow, event: Event) {
  if (!currentRun.value) return
  const action = (event.target as HTMLSelectElement).value
  busy.value = true
  try {
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      row_overrides: { [String(row.id)]: action },
    })
    await loadRows()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '逐行动作保存失败'
  } finally {
    busy.value = false
  }
}

async function bulkOverride(action: 'new' | 'skip') {
  if (!currentRun.value) return
  const candidates = action === 'new'
    ? bulkNewRows.value
    : runRows.value.filter((row) => !hasBlockingRowIssues(row))
  if (!candidates.length) return
  busy.value = true
  try {
    currentRun.value = await etlApi.patchDraft(currentRun.value.id, {
      row_overrides: Object.fromEntries(candidates.map((row) => [String(row.id), action])),
    })
    await loadRows()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '批量动作保存失败'
  } finally {
    busy.value = false
  }
}

async function executeCurrentRun() {
  if (!currentRun.value || !canExecute.value) return
  busy.value = true
  try {
    currentRun.value = await etlApi.execute(currentRun.value.id, validRowsOnly.value)
    activeTab.value = 'history'
    await refreshRuns()
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '执行失败'
    if (currentRun.value) currentRun.value = await etlApi.run(currentRun.value.id).catch(() => currentRun.value)
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
function targetLabel(type: string) {
  if (type === 'auto') return '智能识别（推荐）'
  return capabilities.value?.targets.find((item) => item.type === type)?.label || type
}
function routesForSheet(sheet: Record<string, unknown>) {
  const sheetName = String(sheet.sheet || '')
  return documentRoutes.value.filter((route) => String(route.sheet || '') === sheetName)
}

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<style scoped src="./EtlCenterView.css"></style>
