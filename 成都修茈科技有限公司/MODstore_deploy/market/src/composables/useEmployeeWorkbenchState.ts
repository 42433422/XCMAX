import { computed, ref } from 'vue'
import { api } from '../api'
import { applyTemplateV2 } from '../employeeConfigV2'

export interface WorkflowOption {
  id?: number | string
  sandbox_status?: { status?: string } | null
  [k: string]: unknown
}

export interface EmployeeWorkbenchStateInputs {
  parseWorkflowIdFromEntry: (entry: any) => number
  inferWorkflowIdFromManifest: (manifest: any, index: number) => number
}

export function useEmployeeWorkbenchState({
  parseWorkflowIdFromEntry,
  inferWorkflowIdFromManifest,
}: EmployeeWorkbenchStateInputs) {
  const employeeTemplateId = ref('workflow')
  const employeeConfigV2 = ref(applyTemplateV2('workflow'))
  const employeeConfigErrors = ref<string[]>([])
  const currentStep = ref(0)
  const cardModeEnabled = ref(true)

  const wizardSteps = [
    { id: 0, label: '0 模板' },
    { id: 1, label: '1 身份' },
    { id: 2, label: '2 感知' },
    { id: 3, label: '3 记忆' },
    { id: 4, label: '4 认知' },
    { id: 5, label: '5 行动' },
    { id: 6, label: '6 协作(心脏)' },
    { id: 7, label: '7 管理' },
    { id: 8, label: '8 测试审核' },
    { id: 9, label: '9 上架发布' },
  ]

  const listingHints = ref({
    industryRaw: '',
    industryCoerced: '',
    priceFromManifest: null,
  })

  const selectedFile = ref<File | null>(null)
  const packageScanMessage = ref('')
  const packageScanKind = ref('info')
  const uploading = ref(false)
  const loading = ref(false)
  const v1CatalogLoadError = ref('')
  const error = ref('')
  const success = ref('')
  const myEmployees = ref<unknown[]>([])

  const linkedModId = ref('')
  const linkedWorkflowIndex = ref(0)
  const linkedModName = ref('')
  const linkedModArtifact = ref('mod')
  const workflowJsonText = ref('')
  const workflowSaving = ref(false)
  const exportZipBusy = ref(false)
  const workflowPanelErr = ref('')
  const workflowPanelOk = ref('')
  const linkedManifestSnapshot = ref<Record<string, unknown> | null>(null)
  const showLinkedModPanel = ref(false)
  const packageManifestWorkflowId = ref(0)
  const eligibleWorkflows = ref<WorkflowOption[]>([])
  const allWorkflowOptions = ref<WorkflowOption[]>([])
  const workflowGateLoading = ref(false)
  const workflowGateError = ref('')

  const packageScanFlashClass = computed(() => {
    if (packageScanKind.value === 'ok') return 'flash-success'
    if (packageScanKind.value === 'warn') return 'flash-warn'
    return 'flash-info'
  })

  const resolvedWorkflowId = computed(() => {
    try {
      const o = JSON.parse(workflowJsonText.value || '{}')
      const fromEditor = parseWorkflowIdFromEntry(o)
      if (fromEditor > 0) return fromEditor
    } catch {
      /* fall through */
    }
    const snap = linkedManifestSnapshot.value
    if (snap && typeof snap === 'object') {
      const fromManifest = inferWorkflowIdFromManifest(snap, linkedWorkflowIndex.value)
      if (fromManifest > 0) return fromManifest
    }
    const p = packageManifestWorkflowId.value
    return Number.isFinite(p) && p > 0 ? p : 0
  })

  const safeResolvedWorkflowId = computed(() => {
    const n = Number(resolvedWorkflowId.value || 0)
    return Number.isFinite(n) && n > 0 ? n : 0
  })

  const selectedWorkflowStatus = computed(() => {
    const wid = safeResolvedWorkflowId.value
    if (!(wid > 0)) return null
    return (allWorkflowOptions.value || []).find((w) => Number(w?.id || 0) === wid) || null
  })

  const workflowGate = computed(() => {
    if (workflowGateLoading.value) return 'loading'
    const wid = safeResolvedWorkflowId.value
    if (!(wid > 0)) return 'idle'
    if ((eligibleWorkflows.value || []).some((w) => Number(w?.id || 0) === wid)) return 'pass'
    const status = String(selectedWorkflowStatus.value?.sandbox_status?.status || '').trim()
    if (status === 'stale' || status === 'fail' || status === 'untested') return status
    return workflowGateError.value ? 'fail' : 'fail'
  })

  const workflowGateMessage = computed(() => {
    if (workflowGateLoading.value) return '正在读取工作流沙箱状态'
    if (workflowGateError.value) return workflowGateError.value
    const wid = safeResolvedWorkflowId.value
    if (!(wid > 0)) return '请先选择已通过沙箱测试的工作流'
    if (workflowGate.value === 'pass') return `工作流 #${wid} 已通过沙箱测试，可继续配置员工模块`
    if (workflowGate.value === 'stale') return `工作流 #${wid} 已变更，请重新运行沙箱测试`
    if (workflowGate.value === 'untested') return `工作流 #${wid} 尚未运行沙箱测试`
    return `工作流 #${wid} 最近一次沙箱测试未通过`
  })

  const workflowGatePass = computed(() => workflowGate.value === 'pass')

  async function loadEligibleWorkflows() {
    workflowGateLoading.value = true
    workflowGateError.value = ''
    try {
      const res = await api.listEmployeeEligibleWorkflows()
      eligibleWorkflows.value = Array.isArray(res?.workflows) ? res.workflows : []
      allWorkflowOptions.value = Array.isArray(res?.all_workflows) ? res.all_workflows : eligibleWorkflows.value
    } catch (e) {
      eligibleWorkflows.value = []
      allWorkflowOptions.value = []
      workflowGateError.value = (e as Error)?.message || String(e)
    } finally {
      workflowGateLoading.value = false
    }
  }

  return {
    employeeTemplateId,
    employeeConfigV2,
    employeeConfigErrors,
    currentStep,
    cardModeEnabled,
    wizardSteps,
    listingHints,
    selectedFile,
    packageScanMessage,
    packageScanKind,
    uploading,
    loading,
    v1CatalogLoadError,
    error,
    success,
    myEmployees,
    linkedModId,
    linkedWorkflowIndex,
    linkedModName,
    linkedModArtifact,
    workflowJsonText,
    workflowSaving,
    exportZipBusy,
    workflowPanelErr,
    workflowPanelOk,
    linkedManifestSnapshot,
    showLinkedModPanel,
    packageManifestWorkflowId,
    eligibleWorkflows,
    allWorkflowOptions,
    workflowGateLoading,
    workflowGateError,
    packageScanFlashClass,
    resolvedWorkflowId,
    safeResolvedWorkflowId,
    selectedWorkflowStatus,
    workflowGate,
    workflowGateMessage,
    workflowGatePass,
    loadEligibleWorkflows,
  }
}
