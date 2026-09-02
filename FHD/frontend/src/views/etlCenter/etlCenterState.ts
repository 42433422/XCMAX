/**
 * 数据对接中心共享状态（拆分自 views/EtlCenterView.vue，行为保持一致）。
 */
import { reactive, ref } from 'vue'
import type { EtlCapabilities, EtlFieldMapping, EtlRun, EtlRunRow, EtlTargetConfig, EtlTemplate } from '@/api/etl'
import { useTutorialImportAutoWrite } from '@/composables/useTutorialImportAutoWrite'
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
  const busy = ref(false)
  const pageError = ref('')
  /** 正常工作流保持自动写入；教学课程强制停在预览，等待学习者亲自确认。 */
  const autoWriteEnabled = useTutorialImportAutoWrite()
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
  const pollTimer: { value: ReturnType<typeof setTimeout> | null } = { value: null }
  const autoWriteInFlight = new Set<string>()

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
    busy,
    pageError,
    autoWriteEnabled,
    pendingAutoWriteIds,
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
    autoWriteInFlight,
  }
}

export type EtlCenterState = ReturnType<typeof createEtlCenterState>
