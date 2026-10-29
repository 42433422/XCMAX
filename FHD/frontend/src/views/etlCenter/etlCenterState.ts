/**
 * 数据对接中心共享状态（拆分自 views/EtlCenterView.vue，行为保持一致）。
 */
import { reactive, ref, watch } from 'vue'
import type { EtlCapabilities, EtlFieldMapping, EtlRun, EtlRunRow, EtlTargetConfig, EtlTemplate } from '@/api/etl'
import type { EtlRunTab } from '@/utils/etlRunView'

export type TabId = EtlRunTab

export const ETL_CENTER_TABS: Array<{ id: TabId; step: string; label: string }> = [
  { id: 'upload', step: '1', label: '上传文件' },
  { id: 'mapping', step: '2', label: '字段映射' },
  { id: 'preview', step: '3', label: '核对写入' },
  { id: 'history', step: '4', label: '运行历史' },
]

export function createEtlCenterState() {
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
  watch([() => currentRun.value?.id, () => currentRun.value?.preview_revision], () => {
    reviewedPreviewRevision.value = null
    validRowsOnly.value = false
  }, { flush: 'sync' })
  watch(() => currentRun.value?.id, () => {
    rowPage.value = 1
    requestedRowPage.value = 1
    rowActionFilter.value = ''
    sourceSheetFilter.value = sourceSheetInput.value = ''
    sourceRowFilter.value = sourceRowInput.value = ''
    runRows.value = []
    rowTotal.value = 0
  }, { flush: 'sync' })
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
  }
}

export type EtlCenterState = ReturnType<typeof createEtlCenterState>
