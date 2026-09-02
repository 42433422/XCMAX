/**
 * 共享响应式状态（ref / computed）与状态取值函数。
 *
 * 由 AdminDutyEmployeeGraph.vue 原文机械迁出：声明顺序与初值逐字保留。
 */
import { ref, computed } from 'vue'
import type { Node, Edge } from '@vue-flow/core'
import { providerRowHasUsableKey } from '../../../domain/llm/providerCredential'
import type { LlmProviderStatus } from '../../../domain/llm/types'
import type { EmployeeCapabilityView } from '../../../domain/butlerEmployeeProfile'
import type { ClientWorkshop } from '../../../domain/clientWorkshops'
import {
  ALL_AREAS, AREA_COLORS, LLM_ACT_COLOR, LLM_ACT_LABEL, isVirtualEmployee, isDutyGraphMember,
} from './adminDutyConstants'
import type {
  EmpRow, HealthSt, HealthLv, LlmProviderSt, EmpLlmCfg, LlmActLv, EmpCapability,
  RunNodeStatus, DutyGraphRun, NoKeyResponse, AllHandsReport, AllHandsProgress,
  MeetingMinutesBlock, MeetingMinutesEmailMeta, ViewMode, ExecRow,
} from './adminDutyTypes'

export function useAdminDutyState() {
const employees  = ref<EmpRow[]>([])

const healthMap  = ref<Record<string, HealthSt>>({})

const depsMap    = ref<Record<string, string[]>>({})

const loading    = ref(false)

const loadingP2  = ref(false)

const error      = ref('')


const llmStatusMap = ref<Record<string, LlmProviderSt>>({})   // provider → status

const llmFernetConfigured = ref(false)

const llmStatusFailed = ref(false)

const empLlmMap    = ref<Record<string, EmpLlmCfg>>({})       // emp id → LLM config


const viewMode       = ref<ViewMode>('department')

const showGapPanel   = ref(false)

const gapFocusHint   = ref('')

const autoRefresh    = ref(false)

const countdown      = ref(30)

const capabilityMap  = ref<Record<string, EmpCapability>>({})

const capLoading     = ref(false)

const runNodeStatusMap = ref<Record<string, RunNodeStatus>>({})

const showStatsDetail = ref(false)

const showMoreActions = ref(false)

const detailCollapsed = ref<Record<string, boolean>>({})

const empCapabilityViewMap = ref<Record<string, EmployeeCapabilityView>>({})


const showNoKeyPanel = ref(false)

const noKeyLoading = ref(false)

const noKeyError = ref('')

const noKeyData = ref<NoKeyResponse | null>(null)

const noKeyBusyRow = ref<Record<string, boolean>>({})


const showAllHandsPanel = ref(false)

const allHandsBusy = ref(false)

const allHandsError = ref('')

const allHandsReport = ref<AllHandsReport | null>(null)

const allHandsWithResearch = ref(true)

const allHandsExpanded = ref<Record<string, boolean>>({})

const allHandsPlainOpen = ref<Record<string, boolean>>({})

const allHandsPlainText = ref<Record<string, string>>({})

const allHandsPlainLoading = ref<Record<string, boolean>>({})

const allHandsPlainReqGen = ref<Record<string, number>>({})

const allHandsMeetingMinutes = ref<MeetingMinutesBlock | null>(null)

const allHandsMeetingMinutesEmail = ref<MeetingMinutesEmailMeta | null>(null)


const allHandsSessionId = ref('')

const allHandsQuestion = ref('')

const allHandsProgress = ref<AllHandsProgress>({
  stage: 'prepare',
  total: 0,
  completed: 0,
  ok: 0,
  error: 0,
  percent: 0,
  current_employee_id: '',
  current_employee_name: '',
  current_employee_status: '',
  updated_at: '',
})


const showRunPanel = ref(false)

const runTargetId = ref('')

const runTaskBrief = ref('')

const runInputJson = ref('{}')

const runIncludeDependencies = ref(true)

const runAllowHighRisk = ref(false)

const runMaxConcurrency = ref(2)

const runBusy = ref(false)

const runError = ref('')

const latestRun = ref<DutyGraphRun | null>(null)


const flowNodes = ref<Node[]>([])

const flowEdges = ref<Edge[]>([])


const taskBrief     = ref('')

const taskInputJson = ref('{}')

const dispatchConfirmHighRisk = ref(false)

const taskRunning   = ref(false)

const taskResult    = ref<string | null>(null)

const taskError     = ref<string | null>(null)

const showDispatch  = ref(false)


const selectedEmp = ref<EmpRow | null>(null)

const selectedWorkshop = ref<ClientWorkshop | null>(null)

const workshopRouteCopied = ref(false)


const execItems = ref<ExecRow[]>([])

const execTotal = ref(0)

const execLoading = ref(false)

const execLoadingMore = ref(false)

const execError = ref('')


const onDutyEmployees = computed<EmpRow[]>(() =>
  employees.value.filter((e) => e.source !== 'v1_catalog' && isDutyGraphMember(e)),
)


function healthLevel(id: string): HealthLv {
  const h = healthMap.value[id]
  if (!h) return 'unknown'
  if (h.total === 0) return 'idle'
  return h.rate >= 80 ? 'healthy' : 'warn'
}


function empAreaColor(id: string): string {
  for (const [area, { ids }] of Object.entries(ALL_AREAS)) {
    if (ids.includes(id)) return AREA_COLORS[area] ?? '#6366f1'
  }
  return '#6366f1'
}


function llmActLevel(id: string): LlmActLv {
  const cfg = empLlmMap.value[id]
  if (!cfg) return 'unknown'
  if (!cfg.needsLlm) return 'echo_only'
  if (llmStatusFailed.value) return 'unknown'
  // 前端虚拟员工（数字管家）：seed 早于 /api/llm/status 完成，empLlmMap.activated 会一度为 false；
  // 且无密钥修复面板只列服务端 catalog 员工，不含虚拟 id。这里按当前账户密钥实时判定，避免「徽章 1、列表 0」。
  if (isVirtualEmployee(id)) {
    return anyProviderHasUsableKey() ? 'activated' : 'no_key'
  }
  return cfg.activated ? 'activated' : 'no_key'
}


function anyProviderHasUsableKey(): boolean {
  const fernetOk = llmFernetConfigured.value
  for (const row of Object.values(llmStatusMap.value)) {
    if (providerRowHasUsableKey(row as LlmProviderStatus, fernetOk)) return true
  }
  return false
}


function runStatusLevel(id: string): RunNodeStatus {
  return runNodeStatusMap.value[id] ?? 'idle'
}


function capabilityLevel(id: string): 'executable' | 'blocked' | 'unknown' {
  const cap = capabilityMap.value[id]
  if (!cap) return 'unknown'
  return cap.executable ? 'executable' : 'blocked'
}


function capabilityColor(id: string): string {
  const lv = capabilityLevel(id)
  if (lv === 'executable') return '#22c55e'
  if (lv === 'blocked') return '#ef4444'
  return '#6b7280'
}


function capabilityLabel(id: string): string {
  const cap = capabilityMap.value[id]
  if (!cap) return '能力未知'
  if (cap.executable) return '可执行'
  if (cap.reasons?.length) return `不可执行：${cap.reasons.join('；')}`
  return '不可执行'
}


  return {
    employees,
    healthMap,
    depsMap,
    loading,
    loadingP2,
    error,
    llmStatusMap,
    llmFernetConfigured,
    llmStatusFailed,
    empLlmMap,
    viewMode,
    showGapPanel,
    gapFocusHint,
    autoRefresh,
    countdown,
    capabilityMap,
    capLoading,
    runNodeStatusMap,
    showStatsDetail,
    showMoreActions,
    detailCollapsed,
    empCapabilityViewMap,
    showNoKeyPanel,
    noKeyLoading,
    noKeyError,
    noKeyData,
    noKeyBusyRow,
    showAllHandsPanel,
    allHandsBusy,
    allHandsError,
    allHandsReport,
    allHandsWithResearch,
    allHandsExpanded,
    allHandsPlainOpen,
    allHandsPlainText,
    allHandsPlainLoading,
    allHandsPlainReqGen,
    allHandsMeetingMinutes,
    allHandsMeetingMinutesEmail,
    allHandsSessionId,
    allHandsQuestion,
    allHandsProgress,
    showRunPanel,
    runTargetId,
    runTaskBrief,
    runInputJson,
    runIncludeDependencies,
    runAllowHighRisk,
    runMaxConcurrency,
    runBusy,
    runError,
    latestRun,
    flowNodes,
    flowEdges,
    taskBrief,
    taskInputJson,
    dispatchConfirmHighRisk,
    taskRunning,
    taskResult,
    taskError,
    showDispatch,
    selectedEmp,
    selectedWorkshop,
    workshopRouteCopied,
    execItems,
    execTotal,
    execLoading,
    execLoadingMore,
    execError,
    onDutyEmployees,
    healthLevel,
    empAreaColor,
    llmActLevel,
    anyProviderHasUsableKey,
    runStatusLevel,
    capabilityLevel,
    capabilityColor,
    capabilityLabel,
  }
}

export type AdminDutyState = ReturnType<typeof useAdminDutyState>
