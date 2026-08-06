<template src="./EtlCenterView.template.html"></template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  etlApi,
  type EtlAction,
  type EtlCapabilities,
  type EtlFieldMapping,
  type EtlRun,
  type EtlRunRow,
  type EtlTargetConfig,
  type EtlTemplate,
} from '@/api/etl'
import {
  useEtlFolderBatch,
} from '@/composables/useEtlFolderBatch'
import { useEtlTemplateSelection } from '@/composables/useEtlTemplateSelection'
import { tabForRunStatus, type EtlRunTab } from '@/utils/etlRunView'
type TabId = EtlRunTab

const route = useRoute()
const router = useRouter()
const tabs: Array<{ id: TabId; step: string; label: string }> = [
  { id: 'upload', step: '1', label: '上传文件' },
  { id: 'mapping', step: '2', label: '字段映射' },
  { id: 'preview', step: '3', label: '核对写入' },
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
/** 上传解析就绪后直接写入业务库（真实导入，不是停在预演）。 */
const autoWriteEnabled = ref(true)
const pendingAutoWriteIds = ref(new Set<string>())
const validRowsOnly = ref(false)
const editableMappings = ref<EtlFieldMapping[]>([])
const mappingUiTransform = reactive<Record<string, string>>({})
const mappingUiTransformJson = reactive<Record<string, string>>({})
const allowedUpdateFields = ref<string[]>([])
const ocrConfirmed = ref(false)
const hasOcrRows = ref(false)
const showWebhookForm = ref(false)
const webhookDraft = reactive({ name: '', endpoint_url: '', headersJson: '{}', secret: '' })
const webhookTestMessage = ref('')
const shipmentTemplateMessage = ref('')
const customerProductPreviewMessage = ref('')
const selectedShipmentTemplateRegionId = ref('')
let pollTimer: ReturnType<typeof setTimeout> | null = null
const autoWriteInFlight = new Set<string>()

function markAutoWrite(runId: string) {
  pendingAutoWriteIds.value = new Set([...pendingAutoWriteIds.value, runId])
}

async function tryAutoWrite(run: EtlRun) {
  if (!autoWriteEnabled.value) return
  if (!pendingAutoWriteIds.value.has(run.id)) return
  if (run.status !== 'preview_ready') return
  if (autoWriteInFlight.has(run.id)) return
  autoWriteInFlight.add(run.id)
  const nextPending = new Set(pendingAutoWriteIds.value)
  nextPending.delete(run.id)
  pendingAutoWriteIds.value = nextPending
  const writable = (run.summary.new || 0) + (run.summary.update || 0)
  if (writable <= 0) {
    autoWriteInFlight.delete(run.id)
    currentRun.value = run
    syncDraft()
    activeTab.value = 'preview'
    await loadRows()
    pageError.value = '解析完成，但没有可写入行（全部跳过或错误）。请核对后手动写入。'
    return
  }
  busy.value = true
  pageError.value = ''
  try {
    const onlyValid = (run.summary.error || 0) > 0
    validRowsOnly.value = onlyValid
    currentRun.value = await etlApi.execute(run.id, onlyValid)
    activeTab.value = 'history'
    await refreshRuns()
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '自动写入失败'
    currentRun.value = await etlApi.run(run.id).catch(() => run)
    syncDraft()
    activeTab.value = 'preview'
    if (currentRun.value?.status === 'preview_ready') await loadRows()
  } finally {
    autoWriteInFlight.delete(run.id)
    busy.value = false
  }
}

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
  autoWriteEnabled,
  markAutoWrite,
  tryAutoWrite,
  syncDraft,
  schedulePoll,
  loadRows,
})

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
  row.validation_issues.length === 0
  && !row.match_ref
  && row.suggested_action !== 'skip'
)))
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
  return candidate && typeof candidate === 'object' && !Array.isArray(candidate)
    ? candidate as Record<string, unknown>
    : null
})
const savedShipmentTemplateName = computed(() => (
  String(savedShipmentTemplate.value?.name || '').trim()
))
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
const shipmentTemplateCandidateName = computed(() => (
  String(shipmentTemplateCandidate.value?.name || '').trim()
))
const linkedCustomerProductPreview = computed<Record<string, unknown> | null>(() => {
  const linked = currentRun.value?.details?.linked_customer_products_preview
  return linked && typeof linked === 'object' && !Array.isArray(linked)
    ? linked as Record<string, unknown>
    : null
})
const linkedCustomerNames = computed(() => {
  const names = runRows.value
    .map((row) => String(row.normalized.customer_name || '').trim())
    .filter(Boolean)
  return [...new Set(names)]
})
const plannedBusinessRows = computed(() => {
  if (!currentRun.value) return 0
  return currentRun.value.summary.new
    + currentRun.value.summary.update
    + currentRun.value.summary.skip
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
const llmPlanningText = computed(() => {
  const structure = currentRun.value?.source_features?.llm_structure
  const mapping = currentRun.value?.source_features?.llm_mapping
  const entries = [structure, mapping].filter(
    (item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object',
  )
  if (entries.some((item) => item.used_llm === true && item.degraded !== true)) return '软件 LLM 已参与结构或字段建议'
  if (entries.some((item) => item.degraded === true)) return 'LLM 已降级，当前结果由确定性规则生成'
  return '当前结构由确定性规则识别'
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
  if (!currentRun.value || !['queued', 'previewing', 'executing'].includes(currentRun.value.status)) return
  pollTimer = setTimeout(async () => {
    if (!currentRun.value) return
    try {
      currentRun.value = await etlApi.run(currentRun.value.id)
      syncDraft()
      if (currentRun.value.status === 'preview_ready') {
        if (autoWriteEnabled.value && pendingAutoWriteIds.value.has(currentRun.value.id)) {
          await tryAutoWrite(currentRun.value)
        } else {
          activeTab.value = 'preview'
          await loadRows()
          await refreshRuns()
        }
      } else if (currentRun.value.status === 'completed') {
        activeTab.value = 'history'
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
}

async function saveMappings() {
  if (!currentRun.value) return
  busy.value = true
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
    : runRows.value.filter((row) => row.validation_issues.length === 0)
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

async function saveCurrentAsTemplate() {
  if (!currentRun.value) return
  const name = window.prompt('模板名称', `${targetLabel(currentRun.value.target_type)}-${new Date().toLocaleDateString()}`)
  if (!name?.trim()) return
  busy.value = true
  try {
    await etlApi.createTemplate({
      name: name.trim(),
      target_type: currentRun.value.target_type,
      draft: currentRun.value.draft,
      source_features: currentRun.value.source_features,
    })
    templates.value = await etlApi.templates()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '模板保存失败'
  } finally {
    busy.value = false
  }
}

async function saveCurrentAsShipmentTemplate() {
  if (!currentRun.value || currentRun.value.target_type !== 'shipment_records') return
  const requestedName = window.prompt(
    '发货单版式名称（可选；留空将按识别到的客户命名）',
    '',
  )
  if (requestedName === null) return
  const name = requestedName.trim()
  busy.value = true
  shipmentTemplateMessage.value = ''
  try {
    const result = await etlApi.saveShipmentTemplate(
      currentRun.value.id,
      name,
      String(shipmentTemplateCandidate.value?.source_region_id || ''),
    )
    shipmentTemplateMessage.value = result.name
      ? `已保存“${result.name}”。${result.message}`
      : result.message
    currentRun.value = await etlApi.run(currentRun.value.id)
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '发货单版式保存失败'
  } finally {
    busy.value = false
  }
}

async function previewCustomerProductsFromShipment() {
  if (!currentRun.value || currentRun.value.target_type !== 'shipment_records') return
  const sourceRun = currentRun.value
  const linkedRunId = String(linkedCustomerProductPreview.value?.run_id || '').trim()
  if (linkedRunId) {
    busy.value = true
    pageError.value = ''
    try {
      const customerProductRun = await etlApi.run(linkedRunId)
      currentRun.value = customerProductRun
      targetType.value = 'customer_products'
      rowPage.value = 1
      rowActionFilter.value = ''
      runRows.value = []
      rowTotal.value = 0
      if (!runs.value.some((run) => run.id === customerProductRun.id)) {
        runs.value = [customerProductRun, ...runs.value]
      }
      customerProductPreviewMessage.value = '这是同一上传文件自动建立的客户及产品导入任务；尚未执行，不会写入客户库或产品库。'
      syncDraft()
      activeTab.value = tabForRunStatus(customerProductRun.status)
      if (customerProductRun.status === 'preview_ready') await loadRows()
      await router.replace({ path: '/business-docking', query: { run_id: customerProductRun.id } })
      schedulePoll()
    } catch (error) {
      pageError.value = error instanceof Error ? error.message : '读取关联客户及产品任务失败'
    } finally {
      busy.value = false
    }
    return
  }
  if (!sourceRun.upload_id) {
    pageError.value = '原始上传文件不可用，无法创建客户及产品导入。请重新上传该工作簿。'
    return
  }
  busy.value = true
  pageError.value = ''
  shipmentTemplateMessage.value = ''
  customerProductPreviewMessage.value = ''
  try {
    const customerProductRun = await etlApi.preview({
      upload_id: sourceRun.upload_id,
      target_type: 'customer_products',
    })
    currentRun.value = customerProductRun
    targetType.value = 'customer_products'
    rowPage.value = 1
    rowActionFilter.value = ''
    runRows.value = []
    rowTotal.value = 0
    const retainedRuns = runs.value.some((run) => run.id === sourceRun.id)
      ? runs.value
      : [sourceRun, ...runs.value]
    runs.value = [
      customerProductRun,
      ...retainedRuns.filter((run) => run.id !== customerProductRun.id),
    ]
    customerProductPreviewMessage.value = '已从同一上传文件创建客户及产品导入任务；请核对后点击“写入数据库”。'
    if (autoWriteEnabled.value) markAutoWrite(customerProductRun.id)
    syncDraft()
    activeTab.value = 'preview'
    await router.replace({
      path: '/business-docking',
      query: { run_id: customerProductRun.id },
    })
    if (customerProductRun.status === 'preview_ready' && autoWriteEnabled.value) {
      await tryAutoWrite(customerProductRun)
    } else {
      schedulePoll()
    }
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '创建客户及产品导入失败'
  } finally {
    busy.value = false
  }
}

async function refreshRuns() {
  runs.value = await etlApi.runs()
  if (currentRun.value) {
    const latest = runs.value.find((item) => item.id === currentRun.value?.id)
    if (latest) currentRun.value = latest
  }
}

async function selectRun(run: EtlRun) {
  customerProductPreviewMessage.value = ''
  currentRun.value = await etlApi.run(run.id)
  syncDraft()
  activeTab.value = 'history'
  await router.replace({ path: '/business-docking', query: { run_id: run.id } })
  schedulePoll()
}

async function retryRun() {
  if (!currentRun.value) return
  busy.value = true
  try {
    currentRun.value = await etlApi.retry(currentRun.value.id)
    activeTab.value = 'upload'
    schedulePoll()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '重试失败'
  } finally {
    busy.value = false
  }
}

async function rollbackRun() {
  if (!currentRun.value || !window.confirm('确认撤销本次内部写入？更新将恢复前镜像，新增记录将被删除。')) return
  busy.value = true
  try {
    currentRun.value = await etlApi.rollback(currentRun.value.id)
    await refreshRuns()
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : '撤销失败'
  } finally {
    busy.value = false
  }
}

async function saveWebhook() {
  busy.value = true
  try {
    const headers = JSON.parse(webhookDraft.headersJson || '{}')
    if (!headers || Array.isArray(headers) || typeof headers !== 'object') {
      throw new Error('普通请求头必须是 JSON 对象')
    }
    const config = await etlApi.createTargetConfig({
      name: webhookDraft.name,
      endpoint_url: webhookDraft.endpoint_url,
      headers,
      secret: webhookDraft.secret,
    })
    targetConfigs.value = await etlApi.targetConfigs()
    targetConfigId.value = config.id
    showWebhookForm.value = false
    webhookDraft.name = ''
    webhookDraft.endpoint_url = ''
    webhookDraft.headersJson = '{}'
    webhookDraft.secret = ''
  } catch (error) {
    pageError.value = error instanceof Error ? error.message : 'Webhook 配置保存失败'
  } finally {
    busy.value = false
  }
}

async function testWebhook() {
  if (!targetConfigId.value) return
  busy.value = true
  webhookTestMessage.value = ''
  try {
    await etlApi.testTarget(targetConfigId.value)
    webhookTestMessage.value = '连接测试成功'
  } catch (error) {
    webhookTestMessage.value = error instanceof Error ? error.message : '连接测试失败'
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
function actionLabel(action: string) {
  return ({ new: '新增', update: '更新', skip: '跳过', error: '错误' } as Record<string, string>)[action] || action
}
function actionReason(action: string) {
  return action === 'skip' ? '重复数据，默认不写入' : '无差异'
}
function stageLabel(stage: string) {
  return ({ queued: '等待后台任务', parsing: '解析文件', validating: '转换与校验', preview_ready: '解析完成', executing: '执行写入' } as Record<string, string>)[stage] || stage
}
function statusLabel(status: string) {
  return ({ queued: '排队中', previewing: '解析中', preview_ready: '待写入', executing: '写入中', completed: '已写入', failed: '失败', interrupted: '已中断' } as Record<string, string>)[status] || status
}
function sheetRoleLabel(role: unknown) {
  return ({
    delivery_note_template_and_records: '送货单版式与发货数据',
    supporting_customer_product_data: '客户与产品补充数据',
    finance_or_reconciliation: '财务或对账附表',
    reference_catalog: '参考目录',
    non_target_appendix: '非业务附表',
  } as Record<string, string>)[String(role || '')] || '工作表'
}
function sheetPlanStatusLabel(status: unknown) {
  return ({
    included: '纳入本次导入',
    reviewed: '已读取，仅作参考',
    excluded: '已排除',
  } as Record<string, string>)[String(status || '')] || '已检查'
}
function sheetPlanRows(item: Record<string, unknown>) {
  const rows = Number(item.rows || 0)
  return Number.isFinite(rows) && rows > 0 ? `${rows} 行候选数据` : ''
}
function latestRecordSelectionText(selection: Record<string, unknown>) {
  const stale = Number(selection.stale_records_skipped || 0)
  const future = Number(selection.future_dated_records_skipped || 0)
  const parts = [
    !Number.isFinite(stale) || stale <= 0
      ? '同一客户同一产品按来源日期择最新有效记录。'
      : `同一客户同一产品已按来源日期选择最新有效记录，并排除 ${stale} 条较早或同日旧记录。`,
  ]
  if (Number.isFinite(future) && future > 0) parts.push(`另隔离 ${future} 条未来日期记录。`)
  return parts.join(' ')
}
function confidenceClass(value: number) {
  return value >= 0.9 ? 'confidence-high' : value >= 0.6 ? 'confidence-medium' : 'confidence-low'
}
function compactRecord(value: Record<string, unknown>) {
  return Object.entries(value).slice(0, 5).map(([key, item]) => `${key}: ${String(item ?? '')}`).join(' · ')
}
function ocrTableRow(row: EtlRunRow) {
  const table = row.provenance.table_position
  return table && typeof table === 'object' && 'row' in table
    ? String((table as Record<string, unknown>).row || row.source_row)
    : String(row.source_row)
}
function diffText(row: EtlRunRow) {
  return JSON.stringify({ 更新前: row.before, 更新后: row.after }, null, 2)
}
function formatTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

onMounted(bootstrap)
onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer)
})
</script>

<style scoped src="./EtlCenterView.css"></style>
