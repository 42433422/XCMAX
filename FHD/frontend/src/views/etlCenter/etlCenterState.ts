/**
 * 资料整理流程步骤与已有业务导入任务的审阅状态。
 */
import { getCurrentScope, onScopeDispose, reactive, ref, watch } from 'vue'
import type { EtlCapabilities, EtlFieldMapping, EtlRun, EtlRunRow, EtlTargetConfig, EtlTemplate } from '@/api/etl'
import type { EtlRunTab } from '@/utils/etlRunView'

export type TabId = EtlRunTab

export const ETL_CENTER_TABS = [
  { id: 'archive', label: '上传归档原件' },
  { id: 'classification', label: '识别单据' },
  { id: 'fragments', label: '切片与续表确认' },
  { id: 'cleaning', label: '逐片清理' },
  { id: 'template', label: '选择并保存模板' },
] as const

export const ETL_RUN_TABS: Array<{ id: TabId; step: string; label: string }> = [
  { id: 'upload', step: '1', label: '处理进度' },
  { id: 'mapping', step: '2', label: '字段映射' },
  { id: 'preview', step: '3', label: '核对写入' },
  { id: 'history', step: '4', label: '运行历史' },
]

export function createEtlCenterState() {
  const activeTab = ref<TabId>('history')
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
  const sourceSheetFilter = ref('')
  const sourceRowFilter = ref<number | ''>('')
  const sourceSheetInput = ref('')
  const sourceRowInput = ref<number | ''>('')
  const requestedRowPage = ref<number | ''>(1)
  const rowsLoading = ref(false)
  const busy = ref(false)
  const pageError = ref('')
  const reviewedPreviewRevision = ref<string | null>(null)
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
  const pollTimer: { value: ReturnType<typeof setTimeout> | null } = { value: null }
  // Invalidate async results even when the operator switches away and back to the same query.
  let readGeneration = 0
  let busyGeneration = 0
  let disposed = false
  watch([() => currentRun.value?.id, () => currentRun.value?.preview_revision, () => currentRun.value?.status, rowPage, rowActionFilter, sourceSheetFilter, sourceRowFilter],
    ([id, revision], [previousId, previousRevision]) => {
      readGeneration += 1
      reviewedPreviewRevision.value = null
      runRows.value = []
      hasOcrRows.value = false
      if (id !== previousId || revision !== previousRevision) validRowsOnly.value = false
      if (id !== previousId) {
        rowPage.value = 1
        requestedRowPage.value = 1
        rowActionFilter.value = ''
        sourceSheetFilter.value = sourceSheetInput.value = ''
        sourceRowFilter.value = sourceRowInput.value = ''
        rowTotal.value = 0
      }
    }, { flush: 'sync' })
  function captureReadContext() {
    const generation = readGeneration
    return () => !disposed && generation === readGeneration
  }
  function beginBusy() {
    const generation = ++busyGeneration
    busy.value = true
    return () => {
      // An older completion must not release a newer operation's loading state.
      if (!disposed && generation === busyGeneration) busy.value = false
    }
  }
  if (getCurrentScope()) onScopeDispose(() => {
    disposed = true
    readGeneration += 1
    if (pollTimer.value) clearTimeout(pollTimer.value)
    pollTimer.value = null
  })

  return {
    activeTab,
    capabilities,
    templates,
    targetConfigs,
    runs,
    currentRun,
    targetType,
    targetConfigId,
    runRows,
    rowPage,
    rowTotal,
    rowActionFilter,
    sourceSheetFilter,
    sourceRowFilter,
    sourceSheetInput,
    sourceRowInput,
    requestedRowPage,
    rowsLoading,
    busy,
    pageError,
    reviewedPreviewRevision,
    validRowsOnly,
    editableMappings,
    mappingUiTransform,
    mappingUiTransformJson,
    allowedUpdateFields,
    ocrConfirmed,
    hasOcrRows,
    showWebhookForm,
    webhookDraft,
    webhookTestMessage,
    shipmentTemplateMessage,
    customerProductPreviewMessage,
    selectedShipmentTemplateRegionId,
    pollTimer,
    captureReadContext,
    beginBusy,
  }
}

export type EtlCenterState = ReturnType<typeof createEtlCenterState>
