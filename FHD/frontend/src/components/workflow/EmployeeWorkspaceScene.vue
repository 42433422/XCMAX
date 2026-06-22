<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import {
  formatWorkDurationShort,
  totalWorkMs,
  useNowMsTicker,
  useWorkflowEmployeeDesks,
  type WorkflowEmployeeDeskRow,
} from '@/composables/useWorkflowEmployeeDesks'
import YuangongStation from '@/components/workflow/YuangongStation.vue'
import WorkflowEmployeeInspector from '@/components/workflow/WorkflowEmployeeInspector.vue'
import {
  YUANGONG_ENTRY_STITCH_PNG,
  YUANGONG_ENTRY_WORKFLOW_PNG,
  YUANGONG_ENTRY_WORKFLOW_SVG,
} from '@/constants/yuangongAssets'
import DutyRosterWorkflowLoopView from '@/components/workflow/DutyRosterWorkflowLoopView.vue'
import SelfEvolutionLoopRuntimePanel from '@/components/workflow/SelfEvolutionLoopRuntimePanel.vue'
import { useDutyRoster } from '@/composables/useDutyRoster'
import { workflowRegistryEntryBelongsToStack } from '@/utils/workflowEmployeeScope'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import type { EnterpriseModStack } from '@/constants/enterpriseModStack'
import { resolveEnterpriseModStack } from '@/utils/enterpriseModStackApi'
import { useWorkflowEmployeeRegistrySync } from '@/composables/useWorkflowEmployeeRegistrySync'

const ENTRY_BG_STITCH = YUANGONG_ENTRY_STITCH_PNG
const ENTRY_BG_WORKFLOW_PNG = YUANGONG_ENTRY_WORKFLOW_PNG
const ENTRY_BG_WORKFLOW_SVG = YUANGONG_ENTRY_WORKFLOW_SVG

const router = useRouter()
const route = useRoute()
const isAdminConsole = isAdminConsoleSpa()
// SSOT 派生：运行时从后端 /api/system/duty-roster 获取编制矩阵
const { allPlannedIds: ALL_PLANNED_YUANGON_PKG_IDS, employeeLabels: YUANGON_PKG_ROLE_LABELS, ensureLoaded: ensureDutyRosterLoaded } = useDutyRoster()
const wfEmp = useWorkflowAiEmployeesStore()
useWorkflowEmployeeRegistrySync()
const { desks, statusLine, ariaLabel, isBusy } = useWorkflowEmployeeDesks()
const nowMs = useNowMsTicker(30000)
const loopRuntime = ref<Record<string, unknown> | null>(null)
let loopRuntimeTimer: number | null = null

const enterpriseStack = ref<EnterpriseModStack | null>(null)
const DUTY_ROSTER_VIEW_TOKENS = new Set(['department', 'dept', '六部门', 'hub', 'center', '中心', '中心图', 'legacy-area', 'area', '物理', '物理分区', 'client', 'workshop', '车间', '客户端车间'])

/** 企业 Mod 栈内 AI 员工工位（排除平台编制 employee_pack 等游离项） */
const workspaceDesks = computed(() => {
  const stack = enterpriseStack.value
  const filtered = desks.value.filter((d) => {
    // 管理端只显示平台编制员工（ALL_PLANNED_YUANGON_PKG_IDS，SSOT 派生），隔离企业 Mod 栈员工（如 attendance_ai 等）
    if (isAdminConsole && !ALL_PLANNED_YUANGON_PKG_IDS.value.has(d.empId)) return false
    return workflowRegistryEntryBelongsToStack(d, stack)
  })
  // 管理端：工作流注册表无平台编制员工时，从 SSOT 54 岗构建占位工位，确保编制员工可见
  if (isAdminConsole && filtered.length === 0) {
    return [...ALL_PLANNED_YUANGON_PKG_IDS.value].map((id) => ({
      empId: id,
      panelTitle: `工作流 · ${YUANGON_PKG_ROLE_LABELS.value[id] ?? id}`,
      shortName: YUANGON_PKG_ROLE_LABELS.value[id] ?? id,
      enabled: false,
    }))
  }
  return filtered
})

const selectedEmpId = ref<string | null>(null)

watch(
  () => workspaceDesks.value.map((d) => d.empId).join('\0'),
  () => {
    const list = workspaceDesks.value
    if (!list.length) {
      selectedEmpId.value = null
      return
    }
    const cur = selectedEmpId.value
    if (!cur || !list.some((d) => d.empId === cur)) {
      selectedEmpId.value = list[0].empId
    }
  },
  { immediate: true }
)

function routeEmployeeId(): string {
  const raw = route.query.employee
  if (typeof raw === 'string') return raw.trim()
  if (Array.isArray(raw)) return String(raw[0] || '').trim()
  return ''
}

function syncWorkspaceEmployeeQuery(empId?: string | null) {
  const id = loopString(empId)
  const current = routeEmployeeId()
  if (id === current) return
  const nextQuery = { ...route.query }
  if (id) nextQuery.employee = id
  else delete nextQuery.employee
  void router.replace({ query: nextQuery })
}

function normalizeDutyRosterView(raw: unknown): string {
  const token = String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}

const routeFocusedEmployeeId = computed(() => routeEmployeeId())
const routeFocusedEmployeeInWorkspace = computed(() => {
  const id = routeFocusedEmployeeId.value
  return !!id && workspaceDesks.value.some((d) => d.empId === id)
})

watch(
  [() => route.query.employee, () => workspaceDesks.value.map((d) => d.empId).join('\0')],
  () => {
    const id = routeEmployeeId()
    if (!id) return
    if (workspaceDesks.value.some((d) => d.empId === id)) {
      selectedEmpId.value = id
    }
  },
  { immediate: true },
)

function selectDesk(empId: string) {
  selectedEmpId.value = empId
  syncWorkspaceEmployeeQuery(empId)
}

const entryBgUrl = ref(ENTRY_BG_STITCH)

function onEntryBgError() {
  if (entryBgUrl.value === ENTRY_BG_STITCH) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_PNG
  } else if (entryBgUrl.value === ENTRY_BG_WORKFLOW_PNG) {
    entryBgUrl.value = ENTRY_BG_WORKFLOW_SVG
  }
}

const totalCount = computed(() => workspaceDesks.value.length)
const rosterCount = computed(() => ALL_PLANNED_YUANGON_PKG_IDS.value.size)
const visualizedEmployeeCount = computed(() => Math.max(totalCount.value, rosterCount.value))
const enabledCount = computed(() => workspaceDesks.value.filter((d) => d.enabled).length)
const busyCount = computed(() => workspaceDesks.value.filter((d) => isBusy(d)).length)
const idleEnabledCount = computed(() => Math.max(0, enabledCount.value - busyCount.value))
const selectedDesk = computed(() =>
  workspaceDesks.value.find((d) => d.empId === selectedEmpId.value) || null,
)
const panoramaLocation = computed<RouteLocationRaw>(() => {
  if (isAdminConsole && router.hasRoute('duty-roster-graph')) {
    return { name: 'duty-roster-graph', query: { view: 'department' } }
  }
  return { name: 'workflow-employee-stitch-full' }
})
const dutyRosterLoopLocation = computed<RouteLocationRaw>(() => {
  if (router.hasRoute('duty-roster-graph')) {
    return { name: 'duty-roster-graph', query: { view: 'department' } }
  }
  return panoramaLocation.value
})
const dutyRosterDepartmentLocation = computed<RouteLocationRaw>(() => {
  if (router.hasRoute('duty-roster-graph')) {
    return { name: 'duty-roster-graph', query: { view: 'department' } }
  }
  return panoramaLocation.value
})
const entryKicker = computed(() =>
  isAdminConsole ? '管理端可视化 · 六部门' : '企业版全景 · 四部门'
)
const entryLead = computed(() =>
  isAdminConsole
    ? `进入管理端六部门流程可视化，查看 ${rosterCount.value} 岗 AI 员工在编制图谱、流程派发和执行回写中的状态。`
    : '进入企业端四部门节点图，查看企业 Mod 栈下工具、执行、服务、管理工位与任务快照。'
)
const entryCtaText = computed(() =>
  isAdminConsole ? '进入六部门可视化' : '进入企业全景'
)

const workspaceStatSub = computed(() => {
  const label = enterpriseStack.value?.stackShortLabel
  return label
    ? `企业 Mod「${label}」栈内工位`
    : '企业 Mod 栈内工位'
})

onMounted(() => {
  // SSOT 派生：触发后端 /api/system/duty-roster 加载（失败时 composable 自动回退到构建时硬编码常量）
  void ensureDutyRosterLoaded()
  void resolveEnterpriseModStack().then((stack) => {
    enterpriseStack.value = stack
  })
  void refreshLoopRuntime()
  loopRuntimeTimer = window.setInterval(() => {
    void refreshLoopRuntime()
  }, 30000)
})

onBeforeUnmount(() => {
  if (loopRuntimeTimer != null) window.clearInterval(loopRuntimeTimer)
  loopRuntimeTimer = null
})

function loopRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

function loopArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function loopString(v: unknown): string {
  return String(v ?? '').trim()
}

async function refreshLoopRuntime() {
  try {
    loopRuntime.value = await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(40) as Record<string, unknown>
  } catch {
    loopRuntime.value = null
  }
}

function collectLoopEmployeeIds(value: unknown, out: Set<string>) {
  if (value == null) return
  if (typeof value === 'string') {
    const matches = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
    for (const id of matches) {
      if (ALL_PLANNED_YUANGON_PKG_IDS.value.has(id)) out.add(id)
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectLoopEmployeeIds(item, out)
    return
  }
  if (typeof value !== 'object') return
  const row = value as Record<string, unknown>
  const direct = loopString(row.employee_id || row.employeeId || row.emp_id || row.empId || row.actor || row.assignee)
  if (direct && ALL_PLANNED_YUANGON_PKG_IDS.value.has(direct)) out.add(direct)
  for (const child of Object.values(row)) collectLoopEmployeeIds(child, out)
}

const loopParticipantIds = computed(() => {
  const ids = new Set<string>()
  const payload = loopRuntime.value || {}
  for (const item of loopArray(loopRecord(payload).participants)) {
    const id = loopString(loopRecord(item).employee_id || loopRecord(item).id)
    if (id && ALL_PLANNED_YUANGON_PKG_IDS.value.has(id)) ids.add(id)
  }
  collectLoopEmployeeIds(loopRecord(payload).evidence, ids)
  collectLoopEmployeeIds(loopRecord(payload).memory, ids)
  return Array.from(ids).slice(0, 12)
})

const loopRawParticipantIds = computed(() => {
  const ids = new Set<string>()
  const payload = loopRuntime.value || {}
  for (const item of loopArray(loopRecord(payload).participants)) {
    const id = loopString(loopRecord(item).employee_id || loopRecord(item).id)
    if (id) ids.add(id)
  }
  for (const timeline of loopArray(loopRecord(payload).run_timelines)) {
    for (const item of loopArray(loopRecord(timeline).items)) {
      const id = loopString(loopRecord(item).employee_id || loopRecord(item).actor || loopRecord(item).assignee)
      if (id) ids.add(id)
    }
  }
  return Array.from(ids)
})

const loopRosterAlignment = computed(() => loopRecord(loopRuntime.value?.roster_alignment))
const loopRosterGate = computed(() => loopRecord(loopRosterAlignment.value.gate))
const loopRosterRemediation = computed(() => loopRecord(loopRosterAlignment.value.remediation))
const loopUiBridge = computed(() => loopRecord(loopRuntime.value?.ui_bridge))
const loopActiveGates = computed(() => loopRecord(loopRuntime.value?.active_gates))
const loopActiveGateBlockingKeys = computed(() =>
  loopArray(loopActiveGates.value.blocking_keys)
    .map((key) => loopString(key))
    .filter(Boolean),
)
const loopGovernanceAudit = computed(() => loopRecord(loopRuntime.value?.governance_audit))
const loopGovernanceAuditSummary = computed(() => loopRecord(loopGovernanceAudit.value.summary))
const loopGovernanceAuditLast = computed(() => loopRecord(loopGovernanceAudit.value.last))
const loopEmployeeSpaceBridge = computed(() => loopRecord(loopUiBridge.value.employee_space))
const loopGovernanceAction = computed(() => loopRecord(loopUiBridge.value.governance_action))
const loopGovernanceAuditLastTargets = computed(() =>
  loopArray(loopGovernanceAuditLast.value.target_employee_ids)
    .map((id) => loopString(id))
    .filter(Boolean),
)
const loopGovernanceAuditLastSummary = computed(() => {
  const summary = loopRecord(loopGovernanceAuditLast.value.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  return ''
})
const loopBridgePrimaryEmployeeId = computed(() =>
  loopFirstText(
    loopUiBridge.value.primary_employee_id,
    loopArray(loopUiBridge.value.target_employee_ids)[0],
  ),
)
const loopBridgeBlockedEmployeeIds = computed(() =>
  loopArray(loopUiBridge.value.blocked_employee_ids)
    .map((id) => loopString(id))
    .filter(Boolean),
)
const dutyRosterGovernanceLocation = computed<RouteLocationRaw>(() => {
  const view = normalizeDutyRosterView(loopUiBridge.value.primary_view)
  const employeeId = loopBridgePrimaryEmployeeId.value
  if (router.hasRoute('duty-roster-graph')) {
    return {
      name: 'duty-roster-graph',
      query: employeeId ? { view, employee: employeeId } : { view },
    }
  }
  return dutyRosterLoopLocation.value
})
const loopOutOfRosterParticipantIds = computed(() => {
  const backendIds = loopArray(loopRosterAlignment.value.out_of_roster_ids).map((id) => loopString(id)).filter(Boolean)
  if (backendIds.length || loopRosterAlignment.value.out_of_roster_count != null) return backendIds
  return loopRawParticipantIds.value.filter((id) => !ALL_PLANNED_YUANGON_PKG_IDS.value.has(id))
})
const loopOutOfRosterCount = computed(() =>
  loopNumber(loopRosterAlignment.value.out_of_roster_count) ?? loopOutOfRosterParticipantIds.value.length,
)
const loopNotDeployedCount = computed(() =>
  loopNumber(loopRosterAlignment.value.not_deployed_count) ?? 0,
)
const loopAlignedPlannedCount = computed(() =>
  loopNumber(loopRosterAlignment.value.planned_count) ?? visualizedEmployeeCount.value,
)
const loopAlignedInRosterCount = computed(() =>
  loopNumber(loopRosterAlignment.value.in_roster_count) ?? loopParticipantIds.value.length,
)
const loopAlignedInDeployedCount = computed(() =>
  loopNumber(loopRosterAlignment.value.in_deployed_count) ?? loopAlignedInRosterCount.value,
)

const loopParticipantRoleLabels = computed(() => {
  const labels: Record<string, string> = {}
  const payload = loopRuntime.value || {}
  for (const item of loopArray(loopRecord(payload).participants)) {
    const row = loopRecord(item)
    const id = loopString(row.employee_id || row.id)
    if (!id) continue
    const role = loopString(row.role_label || row.role)
    const stageLabels = loopArray(row.stage_labels).map((x) => loopString(x)).filter(Boolean)
    const stages = loopArray(row.stages).map((x) => loopString(x)).filter(Boolean)
    labels[id] = role || stageLabels[0] || stages[0] || ''
  }
  return labels
})

function loopParticipantDisplay(id: string): string {
  const label = loopParticipantRoleLabels.value[id]
  return label ? `${id} · ${label}` : id
}

function dutyRosterEmployeeLocation(id: string): RouteLocationRaw {
  const employeeId = loopString(id)
  if (employeeId && router.hasRoute('duty-roster-graph')) {
    return { name: 'duty-roster-graph', query: { view: 'hub', employee: employeeId } }
  }
  return panoramaLocation.value
}

const loopGate = computed(() => loopRecord(loopRuntime.value?.current_gate))
const loopEvidence = computed(() => loopRecord(loopRuntime.value?.evidence))
const loopMergeDecision = computed(() => loopRecord(loopRuntime.value?.merge_decision))
const loopMetrics = computed(() => loopRecord(loopRuntime.value?.evolution_metrics_summary))
const loopOpenRunCount = computed(() => loopArray(loopEvidence.value.open_run_ids).length)
const loopRuntimeSchemaVersion = computed(() => loopFirstText(loopRecord(loopRuntime.value).schema_version))
const loopRuntimeContract = computed(() => loopRecord(loopRuntime.value?.contract))
const loopRuntimeContractValidation = computed(() => loopRecord(loopRuntime.value?.contract_validation))
const loopRuntimeSurfaceReadinessCards = computed(() => {
  const readiness = loopRecord(loopRuntimeContractValidation.value.surface_readiness)
  const surfaces = [
    { key: 'employee_space', label: '员工空间', role: '执行现场' },
    { key: 'duty_roster_graph', label: '编制图谱', role: '治理准入' },
    { key: 'self_evolution_loop_runtime', label: 'Runtime', role: '完整链路' },
  ]
  return surfaces.map((surface) => {
    const item = loopRecord(readiness[surface.key])
    const missing = loopArray(item.missing).map((value) => loopString(value)).filter(Boolean)
    const known = Object.keys(item).length > 0
    const ok = item.ok === true
    const severity = loopFirstText(item.severity, ok ? 'ok' : known && missing.length ? 'bad' : 'warn')
    const blocked = known && ok === false
    return {
      key: surface.key,
      label: surface.label,
      role: surface.role,
      ok,
      known,
      blocked,
      stateLabel: ok ? '就绪' : blocked ? '异常' : '未知',
      ctaLabel: ok ? '查看链路' : blocked ? '处理断点' : '等待状态',
      tone: severity === 'bad' || blocked ? 'bad' : severity === 'warn' || !known ? 'warn' : 'ok',
      action: loopFirstText(item.action, ok ? 'watch' : known ? 'inspect_runtime_contract' : 'waiting_runtime_contract'),
      detail: loopFirstText(item.detail, missing.length ? `missing ${missing.slice(0, 3).join(' / ')}` : known ? 'contract ready' : '等待后端暴露该 surface readiness'),
      sourceLabel: known ? 'source · contract_validation.surface_readiness' : 'waiting · runtime surface readiness missing',
      missing,
      target: loopFirstText(item.target_surface, surface.key),
      view: loopFirstText(item.target_view, 'runtime'),
    }
  })
})
const loopRuntimeContractRequiredFields = computed(() =>
  loopArray(loopRuntimeContract.value.required_top_level).map((item) => loopString(item)).filter(Boolean),
)
const loopRuntimeContractMissingFields = computed(() => {
  const backendMissing = loopArray(loopRuntimeContractValidation.value.missing_fields)
    .map((item) => loopString(item))
    .filter(Boolean)
  if (backendMissing.length || loopRuntimeContractValidation.value.ok === false) return backendMissing
  const payload = loopRecord(loopRuntime.value)
  return loopRuntimeContractRequiredFields.value.filter((field) => !(field in payload))
})
const loopRuntimeContractMissingNested = computed(() =>
  loopArray(loopRuntimeContractValidation.value.missing_nested)
    .map((item) => loopString(item))
    .filter(Boolean),
)
const loopRuntimeSurfaceReadiness = computed(() =>
  loopRecord(loopRecord(loopRuntimeContractValidation.value.surface_readiness).employee_space),
)
const loopRuntimeSurfaceReadinessOk = computed(() => loopRuntimeSurfaceReadiness.value.ok === true)
const loopRuntimeSurfaceMissing = computed(() =>
  loopArray(loopRuntimeSurfaceReadiness.value.missing)
    .map((item) => loopString(item))
    .filter(Boolean),
)
const loopRuntimeSurfaceIncidents = computed(() =>
  loopArray(loopRuntimeContractValidation.value.surface_incidents)
    .map((item) => loopRecord(item))
    .filter((item) => loopString(item.surface) === 'employee_space'),
)
const loopRuntimeSurfaceIncident = computed(() => loopRuntimeSurfaceIncidents.value[0] || {})
const loopRuntimeSurfaceIncidentSummary = computed(() =>
  loopRecord(loopRuntimeContractValidation.value.surface_incident_summary),
)
const loopRuntimeContractStatus = computed(() => {
  const topLevel = loopRecord(loopRuntime.value?.contract_status)
  return Object.keys(topLevel).length
    ? topLevel
    : loopRecord(loopRuntimeContractValidation.value.contract_status)
})
const loopRuntimeContractPrimaryRoute = computed(() =>
  loopRecord(loopRuntimeContractStatus.value.primary_route),
)
const loopRuntimePrimaryRouteLocation = computed<RouteLocationRaw>(() => {
  const surface = loopString(loopRuntimeContractPrimaryRoute.value.surface)
  const view = normalizeDutyRosterView(loopRuntimeContractPrimaryRoute.value.view)
  const routeEmployeeId = loopFirstText(
    loopRuntimeContractPrimaryRoute.value.employee_id,
    loopArray(loopRuntimeContractPrimaryRoute.value.target_employee_ids)[0],
    loopBridgePrimaryEmployeeId.value,
    routeFocusedEmployeeId.value,
  )
  if (surface === 'duty_roster_graph') {
    if (router.hasRoute('duty-roster-graph')) {
      return {
        name: 'duty-roster-graph',
        query: routeEmployeeId ? { view, employee: routeEmployeeId } : { view },
      }
    }
    return dutyRosterGovernanceLocation.value
  }
  if (surface === 'employee_space' && routeEmployeeId) {
    return { query: { employee: routeEmployeeId } }
  }
  return dutyRosterLoopLocation.value || { query: { view } }
})
const loopRuntimePrimaryRouteLabel = computed(() => {
  const label = loopString(loopRuntimeContractPrimaryRoute.value.label)
  if (label) return label
  const surface = loopString(loopRuntimeContractPrimaryRoute.value.surface)
  if (surface === 'duty_roster_graph') return '打开编制图谱'
  if (surface === 'employee_space') return '定位员工空间'
  return '打开完整 Loop'
})
const loopRuntimeContractOk = computed(() =>
  loopRuntimeSchemaVersion.value === 'self_maintenance_runtime.v1'
  && loopRuntimeContractRequiredFields.value.length > 0
  && loopRuntimeContractMissingFields.value.length === 0
  && loopRuntimeSurfaceReadinessOk.value
)
const loopStatusLabel = computed(() => {
  if (!loopRuntime.value) return '待连接'
  if (!loopRuntimeContractOk.value) return 'Contract 异常'
  if (loopOpenRunCount.value > 0) return '运行中'
  if (loopGate.value.should_run === true) return '达到阈值'
  const reason = loopString(loopGate.value.reason)
  return reason === 'cooldown' ? '冷却中' : '待命'
})

function loopFirstText(...values: unknown[]): string {
  for (const value of values) {
    const text = loopString(value)
    if (text) return text
  }
  return ''
}

function loopNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const loopMissingEvidenceCount = computed(() =>
  loopNumber(
    loopEvidence.value.missing_count
      ?? loopEvidence.value.missingEvidenceCount
      ?? loopEvidence.value.gap_count
      ?? loopGate.value.missing_count,
  ),
)

const loopGateReasonText = computed(() =>
  loopFirstText(loopGate.value.reason, loopGate.value.trigger_reason, loopGate.value.message, '等待证据阈值'),
)

const loopRuntimeCards = computed(() => {
  const missing = loopMissingEvidenceCount.value
  const mergeAction = loopFirstText(loopMergeDecision.value.action, loopMergeDecision.value.verdict, '等待决策')
  const riskText = loopFirstText(
    loopMergeDecision.value.safety_score_v3,
    loopMergeDecision.value.safety_score_v2,
    loopMergeDecision.value.risk_score_v1,
    '未评分',
  )
  return [
    {
      key: 'status',
      label: 'Loop 状态',
      value: loopStatusLabel.value,
      sub: loopRuntime.value && !loopRuntimeContractOk.value
        ? `版本=${loopRuntimeSchemaVersion.value || '未知'}，不是当前状态检查`
        : loopOpenRunCount.value > 0 ? `${loopOpenRunCount.value} 个 run 未闭环` : loopGateReasonText.value,
      tone: loopRuntime.value && !loopRuntimeContractOk.value ? 'bad' : loopOpenRunCount.value > 0 ? 'run' : loopRuntime.value ? 'ok' : 'warn',
    },
    {
      key: 'workers',
      label: '上岗参与',
      value: `${loopParticipantIds.value.length}`,
      sub: `覆盖 ${visualizedEmployeeCount.value} 编制工位中的调度员工`,
      tone: loopParticipantIds.value.length > 0 ? 'run' : 'warn',
    },
    {
      key: 'gate',
      label: '证据门禁',
      value: missing == null ? (loopGate.value.should_run === true ? '已触发' : '未触发') : `${missing}`,
      sub: loopGate.value.should_run === true ? '达到阈值，可委派员工' : loopGateReasonText.value,
      tone: loopGate.value.should_run === true ? 'run' : 'ok',
    },
    {
      key: 'merge',
      label: '合并准入',
      value: mergeAction,
      sub: `risk/safety ${riskText}`,
      tone: String(mergeAction).toLowerCase().includes('block') ? 'bad' : 'ok',
    },
    {
      key: 'metrics',
      label: '进化门禁',
      value: loopMetrics.value.pause === true ? '暂停' : '放行',
      sub: loopFirstText(loopMetrics.value.reason, `history ${loopMetrics.value.history_count ?? 0}`),
      tone: loopMetrics.value.pause === true ? 'bad' : 'ok',
    },
  ]
})

type LoopTimelineItem = {
  runId: string
  employeeId: string
  label: string
  status: string
  role: string
  stage: string
  at: string
}

const loopTimelineItems = computed(() => {
  const rows: LoopTimelineItem[] = []
  const payload = loopRecord(loopRuntime.value)
  for (const timeline of loopArray(payload.run_timelines)) {
    const timelineRecord = loopRecord(timeline)
    const runId = loopFirstText(timelineRecord.run_id, timelineRecord.id)
    for (const item of loopArray(timelineRecord.items)) {
      const row = loopRecord(item)
      rows.push({
        runId,
        employeeId: loopFirstText(row.employee_id, row.actor, row.assignee),
        label: loopFirstText(row.label, row.title, row.event, row.step, row.kind, row.action, 'loop step'),
        status: loopFirstText(row.status, row.verdict, row.result, row.state),
        role: loopFirstText(row.role_label, row.role, row.actor_role),
        stage: loopFirstText(row.stage_label, row.stage, row.phase),
        at: loopFirstText(row.at, row.created_at, row.updated_at, row.ts),
      })
    }
  }
  return rows.slice(-30)
})

const loopPipelineStages = computed(() => {
  const defs = [
    {
      key: 'sense',
      label: '感知',
      hint: '证据/incident',
      tokens: ['sense', 'perception', 'incident', 'evidence', 'scan', '缺证'],
      fallbackActive: loopMissingEvidenceCount.value != null || loopGate.value.should_run === true,
    },
    {
      key: 'assign',
      label: '派工',
      hint: '上岗员工认领',
      tokens: ['assign', 'dispatch', 'brief', 'market', '认领', '派工', '委派'],
      fallbackActive: loopParticipantIds.value.length > 0,
    },
    {
      key: 'repair',
      label: '修复',
      hint: '代码/报告任务',
      tokens: ['repair', 'fix', 'code', 'patch', 'report', '修复', '变更'],
      fallbackActive: loopOpenRunCount.value > 0,
    },
    {
      key: 'review',
      label: '复核',
      hint: 'Review + QA',
      tokens: ['review', 'qa', 'test', 'verdict', '复核', '测试'],
      fallbackActive: loopString(loopMergeDecision.value.qa_verdict) !== '',
    },
    {
      key: 'gate',
      label: '合并门禁',
      hint: '准入/治理',
      tokens: ['merge', 'gate', 'policy', 'governance', 'roster', '合并', '门禁'],
      fallbackActive: Object.keys(loopMergeDecision.value).length > 0 || Object.keys(loopActiveGates.value).length > 0,
    },
  ]
  return defs.map((def) => {
    const matched = loopTimelineItems.value.filter((item) => {
      const text = `${item.label} ${item.status} ${item.role} ${item.stage}`.toLowerCase()
      return def.tokens.some((token) => text.includes(String(token).toLowerCase()))
    })
    const workers = Array.from(new Set(matched.map((item) => item.employeeId).filter(Boolean)))
    const blocked = matched.some((item) => /fail|failed|block|blocked|error|reject/i.test(item.status))
    const latest = matched[matched.length - 1]
    const active = matched.length > 0 || def.fallbackActive
    return {
      key: def.key,
      label: def.label,
      hint: def.hint,
      count: matched.length,
      workers,
      latest: latest ? loopFirstText(latest.status, latest.label, latest.stage) : '',
      tone: blocked ? 'bad' : active ? 'run' : 'idle',
    }
  })
})

const loopActiveGateCards = computed(() =>
  loopArray(loopActiveGates.value.items).map((item, index) => {
    const row = loopRecord(item)
    const blocking = row.blocking === true || row.ok === false
    return {
      key: loopFirstText(row.key, row.name, `gate-${index}`),
      label: loopFirstText(row.label, row.key, row.name, 'gate'),
      value: blocking ? '阻断' : '放行',
      sub: loopFirstText(row.reason, row.detail, row.status, 'policy clear'),
      tone: blocking ? 'bad' : 'ok',
    }
  }),
)

const loopWorkerTaskCards = computed(() => {
  const participantRecords: Record<string, Record<string, unknown>> = {}
  const payload = loopRecord(loopRuntime.value)
  for (const item of loopArray(payload.participants)) {
    const row = loopRecord(item)
    const id = loopString(row.employee_id || row.id)
    if (id) participantRecords[id] = row
  }
  const timelineByEmployee: Record<string, LoopTimelineItem[]> = {}
  for (const item of loopTimelineItems.value) {
    if (!item.employeeId) continue
    if (!timelineByEmployee[item.employeeId]) timelineByEmployee[item.employeeId] = []
    timelineByEmployee[item.employeeId].push(item)
  }
  const notDeployedIds = new Set(
    loopArray(loopRosterAlignment.value.not_deployed_ids)
      .map((id) => loopString(id))
      .filter(Boolean),
  )
  const isolatedIds = new Set([...loopBridgeBlockedEmployeeIds.value, ...loopOutOfRosterParticipantIds.value])
  return loopParticipantIds.value.map((id) => {
    const participant = loopRecord(participantRecords[id])
    const items = timelineByEmployee[id] || []
    const latest = items[items.length - 1]
    const role = loopFirstText(
      participant.role_label,
      participant.role,
      loopParticipantRoleLabels.value[id],
      'loop worker',
    )
    const department = loopFirstText(participant.department_label, participant.department_key, '未分部门')
    const rosterLabel = loopFirstText(participant.roster_label, participant.roster_status, '编制内')
    const dutyLabel = participant.duty_registered === false
      ? '未登记上岗'
      : loopFirstText(participant.duty_registered_label, '已登记上岗')
    const blocked = isolatedIds.has(id) || notDeployedIds.has(id)
    const latestStatus = loopFirstText(latest?.status, latest?.stage, latest?.label, items.length ? '有任务回写' : '等待派工')
    const failed = /fail|failed|block|blocked|error|reject/i.test(latestStatus)
    return {
      id,
      role,
      department,
      rosterLabel,
      dutyLabel,
      eventCount: items.length,
      latestStatus,
      latestLabel: loopFirstText(latest?.label, latest?.stage, latest?.runId),
      tone: blocked || failed ? 'bad' : items.length ? 'run' : 'idle',
    }
  })
})

const loopWorkOrderCards = computed(() => {
  const byRun: Record<string, LoopTimelineItem[]> = {}
  for (const item of loopTimelineItems.value) {
    const key = item.runId || item.employeeId || item.label || 'loop-work-order'
    if (!byRun[key]) byRun[key] = []
    byRun[key].push(item)
  }
  return Object.entries(byRun).slice(-8).map(([key, items]) => {
    const latest = items[items.length - 1]
    const employeeIds = Array.from(new Set(items.map((item) => item.employeeId).filter(Boolean)))
    const failed = items.some((item) => /fail|failed|block|blocked|error|reject/i.test(item.status))
    const done = items.some((item) => /pass|passed|done|success|merged|complete/i.test(item.status))
    const primaryEmployeeId = employeeIds[0] || loopBridgePrimaryEmployeeId.value
    return {
      key,
      runId: latest?.runId || key,
      title: loopFirstText(latest?.label, latest?.stage, 'Loop work order'),
      status: loopFirstText(latest?.status, done ? 'done' : 'in_progress'),
      stage: loopFirstText(latest?.stage, latest?.role, 'worker step'),
      workers: employeeIds,
      stepCount: items.length,
      tone: failed ? 'bad' : done ? 'ok' : 'run',
      to: primaryEmployeeId ? dutyRosterEmployeeLocation(primaryEmployeeId) : dutyRosterLoopLocation.value,
    }
  })
})

const loopFocusedEmployeeId = computed(() =>
  loopFirstText(routeFocusedEmployeeId.value, loopBridgePrimaryEmployeeId.value),
)

const loopFocusedWorkerTaskCard = computed(() =>
  loopWorkerTaskCards.value.find((worker) => worker.id === loopFocusedEmployeeId.value) || null,
)

const loopEmployeeSeparationMatrix = computed(() => {
  const idleRoster = Math.max(0, loopAlignedPlannedCount.value - loopAlignedInRosterCount.value)
  return [
    {
      key: 'on-duty',
      label: '上岗员工',
      value: `${loopAlignedInDeployedCount.value}`,
      sub: '允许进入自维护 loop 的真实工位员工',
      tone: loopAlignedInDeployedCount.value > 0 ? 'run' : 'warn',
    },
    {
      key: 'registered',
      label: '编制命中',
      value: `${loopAlignedInRosterCount.value}/${loopAlignedPlannedCount.value}`,
      sub: idleRoster ? `${idleRoster} 个编制工位本轮未参与` : '本轮参与者均落在编制基线内',
      tone: loopOutOfRosterCount.value ? 'bad' : 'ok',
    },
    {
      key: 'not-deployed',
      label: '待补上岗',
      value: `${loopNotDeployedCount.value}`,
      sub: loopNotDeployedCount.value
        ? loopArray(loopRosterAlignment.value.not_deployed_ids).map((id) => loopString(id)).filter(Boolean).slice(0, 4).join(' / ')
          || '编制内但未登记上岗'
        : '没有待补登记员工',
      tone: loopNotDeployedCount.value ? 'bad' : 'ok',
    },
    {
      key: 'isolated',
      label: '商店/非编制隔离',
      value: `${loopOutOfRosterCount.value}`,
      sub: loopOutOfRosterCount.value
        ? loopOutOfRosterParticipantIds.value.slice(0, 4).join(' / ')
        : '未把商店员工混入上岗 loop',
      tone: loopOutOfRosterCount.value ? 'bad' : 'ok',
    },
  ]
})

const loopWorkspaceActionCards = computed(() => {
  const blockingCount = Number(loopActiveGates.value.blocking_count ?? loopActiveGateBlockingKeys.value.length) || 0
  const primaryEmployeeId = loopBridgePrimaryEmployeeId.value
  const surfaceIncidentAction = loopFirstText(loopRuntimeSurfaceIncident.value.action, loopRuntimeSurfaceReadiness.value.action)
  const surfaceIncidentTarget = loopFirstText(loopRuntimeSurfaceIncident.value.target_surface, loopRuntimeSurfaceReadiness.value.target_surface)
  const surfaceIncidentCard = loopRuntimeSurfaceIncidents.value.length
    ? {
        key: 'surface-incident',
        label: 'Surface incident',
        title: loopFirstText(loopRuntimeSurfaceIncident.value.title, '员工空间 contract 事故'),
        detail: loopFirstText(
          loopRuntimeSurfaceIncident.value.detail,
          loopRuntimeSurfaceMissing.value.length
            ? `缺依赖：${loopRuntimeSurfaceMissing.value.slice(0, 4).join(' / ')}`
            : '后端 surface_incidents 要求处理',
        ),
        cta: surfaceIncidentTarget === 'duty_roster_graph' || surfaceIncidentAction === 'open_duty_roster_graph'
          ? '去编制图谱处理'
          : '查看完整 Loop',
        to: surfaceIncidentTarget === 'duty_roster_graph' || surfaceIncidentAction === 'open_duty_roster_graph'
          ? dutyRosterGovernanceLocation.value
          : dutyRosterLoopLocation.value,
        tone: 'bad',
      }
    : null
  return [
    ...(surfaceIncidentCard ? [surfaceIncidentCard] : []),
    {
      key: 'workers',
      label: '员工现场',
      title: loopOpenRunCount.value > 0 ? '追踪正在执行的员工' : '等待下一轮派工',
      detail: loopParticipantIds.value.length
        ? `${loopParticipantIds.value.length} 个上岗员工有 loop 上下文`
        : '当前还没有员工参与记录',
      cta: primaryEmployeeId ? '定位目标员工' : '看完整 Loop',
      to: primaryEmployeeId ? dutyRosterEmployeeLocation(primaryEmployeeId) : dutyRosterLoopLocation.value,
      tone: loopParticipantIds.value.length ? 'run' : 'warn',
    },
    {
      key: 'governance',
      label: '治理控制',
      title: loopNotDeployedCount.value || loopOutOfRosterCount.value ? '回编制图谱处理准入' : '编制边界正常',
      detail: loopNotDeployedCount.value
        ? `${loopNotDeployedCount.value} 个编制员工待补登记`
        : loopOutOfRosterCount.value
          ? `${loopOutOfRosterCount.value} 个非编制参与者已隔离`
          : '补登记、隔离、审计都在编制图谱执行',
      cta: '打开治理面',
      to: dutyRosterGovernanceLocation.value,
      tone: loopNotDeployedCount.value || loopOutOfRosterCount.value ? 'bad' : 'ok',
    },
    {
      key: 'gates',
      label: '结构化门禁',
      title: blockingCount ? '先处理阻断门禁' : '门禁当前放行',
      detail: blockingCount
        ? loopActiveGateBlockingKeys.value.join(' / ') || `${blockingCount} 个 gate blocking`
        : 'QA/Review/证据/编制/治理门禁没有阻断',
      cta: '查看门禁',
      to: dutyRosterLoopLocation.value,
      tone: blockingCount ? 'bad' : 'ok',
    },
  ]
})

const loopRuntimeTruthCards = computed(() => [
  {
    key: 'contract',
    label: 'Runtime contract',
    value: loopFirstText(loopRuntimeSchemaVersion.value, '未知'),
    sub: loopFirstText(
      loopRecord(loopRecord(loopRuntime.value).source).name,
      'schema/source missing',
    ),
    tone: loopRuntimeContractOk.value ? 'ok' : 'bad',
  },
  {
    key: 'contract-fields',
    label: 'Contract fields',
    value: loopRuntimeContractMissingFields.value.length || loopRuntimeSurfaceMissing.value.length
      ? `missing ${loopRuntimeContractMissingFields.value.length + loopRuntimeSurfaceMissing.value.length}`
      : `${loopNumber(loopRuntimeContractValidation.value.required_count) ?? loopRuntimeContractRequiredFields.value.length}`,
    sub: loopRuntimeContractMissingFields.value.length
      ? `缺字段=${loopRuntimeContractMissingFields.value.slice(0, 4).join(' / ')}`
      : loopRuntimeSurfaceMissing.value.length
      ? `本页缺依赖=${loopRuntimeSurfaceMissing.value.slice(0, 4).join(' / ')}`
      : loopArray(loopRuntimeContract.value.surfaces).length
      ? `surfaces=${loopArray(loopRuntimeContract.value.surfaces).map((item) => loopString(item)).filter(Boolean).join(' / ')}`
      : 'contract.required_top_level/surfaces missing',
    tone: loopRuntimeContractOk.value ? 'ok' : 'warn',
  },
  {
    key: 'surface-ready',
    label: 'Employee surface',
    value: loopRuntimeSurfaceReadinessOk.value ? '就绪' : '异常',
    sub: loopRuntimeSurfaceMissing.value.length
      ? `${loopFirstText(loopRuntimeSurfaceReadiness.value.action, 'repair')} · ${loopRuntimeSurfaceMissing.value.slice(0, 3).join(' / ')}`
      : loopFirstText(loopRuntimeSurfaceReadiness.value.title, `required=${loopArray(loopRuntimeSurfaceReadiness.value.required).length || 0}`),
    tone: loopRuntimeSurfaceReadinessOk.value ? 'ok' : 'bad',
  },
  {
    key: 'surface-incident',
    label: 'Surface incident',
    value: loopRuntimeSurfaceIncidents.value.length ? `${loopRuntimeSurfaceIncidents.value.length}` : 'none',
    sub: loopRuntimeSurfaceIncidents.value.length
      ? loopFirstText(loopRuntimeSurfaceIncident.value.action, loopRuntimeSurfaceIncident.value.title, 'inspect_runtime_contract')
      : 'employee_space 当前没有 contract incident',
    tone: loopRuntimeSurfaceIncidents.value.length ? 'bad' : 'ok',
  },
  {
    key: 'incident-summary',
    label: 'Incident summary',
    value: loopFirstText(loopRuntimeSurfaceIncidentSummary.value.status, `${loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ?? 0}`),
    sub: loopFirstText(loopRuntimeSurfaceIncidentSummary.value.primary_action)
      ? `${loopRuntimeSurfaceIncidentSummary.value.primary_action} -> ${loopFirstText(loopRuntimeSurfaceIncidentSummary.value.primary_target_surface, loopRuntimeSurfaceIncidentSummary.value.primary_surface, '未知')} · 总计 ${loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ?? 0}`
      : loopArray(loopRuntimeSurfaceIncidentSummary.value.surfaces).length
      ? `surfaces=${loopArray(loopRuntimeSurfaceIncidentSummary.value.surfaces).map((item) => loopString(item)).filter(Boolean).join(' / ')}`
      : '全局 surface incident clear',
    tone: loopNumber(loopRuntimeSurfaceIncidentSummary.value.total) ? 'warn' : 'ok',
  },
  {
    key: 'global-nested',
    label: 'Global nested audit',
    value: loopRuntimeContractMissingNested.value.length ? `missing ${loopRuntimeContractMissingNested.value.length}` : 'clear',
    sub: loopRuntimeContractMissingNested.value.length
      ? loopRuntimeContractMissingNested.value.slice(0, 4).join(' / ')
      : `全局=${loopRuntimeContractValidation.value.global_ok === false ? '异常' : '正常'} · 所有模块=${loopRuntimeContractValidation.value.all_surfaces_ok === false ? '异常' : '正常'}`,
    tone: loopRuntimeContractMissingNested.value.length ? 'warn' : 'ok',
  },
  {
    key: 'runtime',
    label: 'Runtime source',
    value: loopRuntime.value ? 'connected' : 'missing',
    sub: loopRuntime.value
      ? '来自 selfMaintenanceRuntimeStatus 实时接口'
      : '未拿到后端 runtime，当前页面不能证明 loop 已运行',
    tone: loopRuntime.value ? 'ok' : 'bad',
  },
  {
    key: 'ledger',
    label: 'Ledger evidence',
    value: loopTimelineItems.value.length ? `${loopTimelineItems.value.length}` : 'no events',
    sub: loopTimelineItems.value.length
      ? 'run_timelines 已回写员工 step'
      : '没有 timeline 事件，不伪造成员工执行',
    tone: loopTimelineItems.value.length ? 'run' : 'warn',
  },
  {
    key: 'participants',
    label: 'Employee binding',
    value: loopParticipantIds.value.length ? `${loopParticipantIds.value.length}` : 'none',
    sub: loopParticipantIds.value.length
      ? '已从 participants / ledger 绑定到上岗员工'
      : '没有 employee_id/actor 绑定',
    tone: loopParticipantIds.value.length ? 'run' : 'warn',
  },
  {
    key: 'governance',
    label: 'Governance audit',
    value: loopGovernanceAuditSummary.value.recent_count != null
      ? `${loopGovernanceAuditSummary.value.recent_count}`
      : 'no audit',
    sub: loopGovernanceAuditSummary.value.recent_count != null
      ? `health=${loopGovernanceAuditSummary.value.health || 'ok'}`
      : '没有治理审计记录，不隐藏风险',
    tone: loopGovernanceAuditSummary.value.health === 'bad' ? 'bad' : 'ok',
  },
])

const loopRuntimeFreshnessCards = computed(() => {
  const payload = loopRecord(loopRuntime.value)
  const generatedAt = loopFirstText(payload.generated_at, payload.created_at, payload.snapshot_at)
  const updatedAt = loopFirstText(payload.updated_at, payload.refreshed_at, payload.last_seen_at, payload.last_run_at)
  const ledgerAt = loopFirstText(
    loopTimelineItems.value[loopTimelineItems.value.length - 1]?.at,
    payload.latest_event_at,
    payload.latest_run_at,
  )
  return [
    {
      key: 'snapshot',
      label: 'Snapshot time',
      value: generatedAt || 'timestamp missing',
      sub: generatedAt ? '后端 runtime 快照时间' : '后端没有返回快照时间，不伪装实时',
      tone: generatedAt ? 'ok' : 'warn',
    },
    {
      key: 'refresh',
      label: 'Runtime update',
      value: updatedAt || '未知',
      sub: updatedAt ? '后端声明的最近更新时间' : '未拿到 updated/refreshed/last_seen 字段',
      tone: updatedAt ? 'ok' : 'warn',
    },
    {
      key: 'ledger',
      label: 'Latest ledger event',
      value: ledgerAt || 'no event time',
      sub: ledgerAt ? '最近一条 timeline 事件时间' : 'ledger 事件没有时间戳或没有事件',
      tone: ledgerAt ? 'run' : 'warn',
    },
  ]
})

const loopIsolationCards = computed(() => [
  {
    key: 'roster',
    label: '编制基线',
    value: `${loopAlignedPlannedCount.value}`,
    sub: '以编制图谱为准，不把商店员工混入工位',
    tone: 'ok',
  },
  {
    key: 'workspace',
    label: '员工空间',
    value: `${totalCount.value}`,
    sub: '只展示企业 Mod 栈内上岗工位',
    tone: totalCount.value > 0 ? 'run' : 'warn',
  },
  {
    key: 'loop',
    label: 'Loop 调度',
    value: `${loopAlignedInDeployedCount.value}`,
    sub: `编制命中 ${loopAlignedInRosterCount.value} · 已上岗命中`,
    tone: loopAlignedInDeployedCount.value > 0 ? 'run' : 'warn',
  },
  {
    key: 'not-deployed',
    label: '未登记上岗',
    value: `${loopNotDeployedCount.value}`,
    sub: loopNotDeployedCount.value
      ? loopArray(loopRosterAlignment.value.not_deployed_ids).map((id) => loopString(id)).filter(Boolean).slice(0, 3).join(' / ')
        || loopFirstText(loopRosterGate.value.reason, '编制内但未登记上岗')
      : '参与者均已登记上岗',
    tone: loopNotDeployedCount.value ? 'bad' : 'ok',
  },
  {
    key: 'blocked',
    label: '隔离拦截',
    value: `${loopOutOfRosterCount.value}`,
    sub: loopOutOfRosterCount.value
      ? loopOutOfRosterParticipantIds.value.slice(0, 3).join(' / ')
        || loopFirstText(loopRosterGate.value.reason, '非编制参与者已由后端隔离')
      : loopFirstText(loopRosterGate.value.action, '未发现非编制参与者'),
    tone: loopOutOfRosterCount.value ? 'bad' : 'ok',
  },
])

const loopDiagnosis = computed(() => {
  if (!loopRuntime.value) {
    return {
      tone: 'warn',
      title: 'Loop runtime 未连接',
      detail: '员工空间还没有拿到 self-maintenance runtime 状态，先检查 MODstore 后端和 market proxy。',
      actions: ['确认后端进程存活', '确认 /ops/self-maintenance/status 可访问'],
    }
  }
  if (!loopRuntimeContractOk.value) {
    const missingText = loopRuntimeContractMissingFields.value.length
      ? ` 缺字段：${loopRuntimeContractMissingFields.value.slice(0, 5).join(' / ')}。`
      : loopRuntimeSurfaceMissing.value.length
      ? ` 当前 surface 缺依赖：${loopRuntimeSurfaceMissing.value.slice(0, 5).join(' / ')}。`
      : ''
    return {
      tone: 'bad',
      title: loopFirstText(loopRuntimeSurfaceReadiness.value.title, 'Loop runtime contract 不匹配'),
      detail: `${loopRuntimeSurfaceReadiness.value.detail || `当前版本=${loopRuntimeSchemaVersion.value || '未知'}，员工空间只认 self_maintenance_runtime v1，避免旧接口被误判。`}${missingText}`,
      actions: [loopFirstText(loopRuntimeSurfaceReadiness.value.action, '检查后端 runtime status contract'), '回编制图谱查看治理待办'],
    }
  }
  if (loopRosterGate.value.action === 'hold' || loopNotDeployedCount.value) {
    const targets = loopArray(loopRosterRemediation.value.target_employee_ids).map((id) => loopString(id)).filter(Boolean)
    return {
      tone: 'bad',
      title: loopFirstText(loopRosterRemediation.value.title, '编制员工未登记上岗'),
      detail: `${loopFirstText(loopRosterRemediation.value.detail, '编制内但未登记上岗，需要补登记后才允许自维护自动放行。')}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
      actions: [loopFirstText(loopRosterRemediation.value.action, 'register_duty_employees'), '确认上岗员工和商店员工隔离'],
    }
  }
  if (loopRosterGate.value.blocking === true || loopOutOfRosterCount.value) {
    const targets = loopArray(loopRosterRemediation.value.target_employee_ids).map((id) => loopString(id)).filter(Boolean)
    return {
      tone: 'bad',
      title: loopFirstText(loopRosterRemediation.value.title, '发现非编制参与者'),
      detail: `${loopFirstText(loopRosterRemediation.value.detail, `后端 gate=${loopFirstText(loopRosterGate.value.action, 'isolate')}，原因：${loopFirstText(loopRosterGate.value.reason, 'out_of_roster_participants_detected')}。`)}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
      actions: [loopFirstText(loopRosterRemediation.value.action, 'isolate_out_of_roster_participants'), '按 gate 策略隔离非编制员工'],
    }
  }
  if (!loopParticipantIds.value.length) {
    return {
      tone: 'warn',
      title: '本轮未看到编制员工参与',
      detail: 'runtime 可能还没有打开 run，也可能 ledger 缺少 employee_id/actor 回写。',
      actions: ['等待缺证阈值触发', '检查 ledger 是否写 employee_id'],
    }
  }
  if (loopOpenRunCount.value > 0) {
    return {
      tone: 'run',
      title: '上岗员工正在参与自维护',
      detail: `${loopParticipantIds.value.length} 个编制员工参与，${loopOpenRunCount.value} 个 run 尚未闭环。`,
      actions: ['查看下方工位高亮', '进入完整 Loop 时间线'],
    }
  }
  return {
    tone: 'ok',
    title: 'Loop 边界正常',
    detail: `当前参与者都命中编制基线，门禁状态：${loopGateReasonText.value || '待命'}。`,
    actions: ['继续观察 30 秒轮询', '必要时手动刷新状态'],
  }
})

const loopGovernanceBridge = computed(() => {
  const bridgeTitle = loopFirstText(loopEmployeeSpaceBridge.value.title, loopUiBridge.value.title)
  if (loopRuntime.value && bridgeTitle) {
    return {
      tone: loopFirstText(loopUiBridge.value.tone, 'ok'),
      label: loopFirstText(loopEmployeeSpaceBridge.value.role, loopUiBridge.value.primary_surface, '执行面'),
      title: bridgeTitle,
      detail: loopFirstText(loopEmployeeSpaceBridge.value.detail, loopUiBridge.value.detail),
      cta: loopFirstText(loopEmployeeSpaceBridge.value.cta, '查看治理面'),
      actionLabel: loopFirstText(loopGovernanceAction.value.label, loopUiBridge.value.primary_action, '观察 Loop'),
      actionStatus: loopFirstText(loopGovernanceAction.value.status, 'informational'),
      actionExecutable: loopGovernanceAction.value.executable !== false,
      actionRequiresAdmin: loopGovernanceAction.value.requires_admin === true,
    }
  }
  if (!loopRuntime.value) {
    return {
      tone: 'warn',
      label: '管控面',
      title: '去编制图谱接入 runtime',
      detail: '员工空间只展示工位和执行态；后端 runtime、gate、补登记动作统一在编制图谱处理。',
      cta: '打开编制图谱',
      actionLabel: '连接 runtime',
      actionStatus: 'requires_check',
      actionExecutable: false,
      actionRequiresAdmin: false,
    }
  }
  if (loopRosterGate.value.action === 'hold' || loopNotDeployedCount.value) {
    const targets = loopArray(loopRosterRemediation.value.target_employee_ids)
      .map((id) => loopString(id))
      .filter(Boolean)
    return {
      tone: 'bad',
      label: '上岗治理',
      title: '需要在编制图谱补登记',
      detail: targets.length
        ? `待补登记：${targets.slice(0, 5).join(' / ')}。员工空间不直接改编制，避免工位页绕过上岗门禁。`
        : 'Loop gate 已进入 hold，需要回编制图谱执行上岗登记后再放行自维护。',
      cta: '去补登记',
      actionLabel: '补登记上岗员工',
      actionStatus: 'requires_action',
      actionExecutable: true,
      actionRequiresAdmin: true,
    }
  }
  if (loopRosterGate.value.blocking === true || loopOutOfRosterCount.value) {
    return {
      tone: 'bad',
      label: '隔离治理',
      title: '非编制员工必须在图谱隔离',
      detail: '员工空间只展示企业 Mod 栈工位；非编制/商店员工的隔离策略由编制图谱统一执行。',
      cta: '查看隔离',
      actionLabel: '隔离非编制参与者',
      actionStatus: 'enforced',
      actionExecutable: false,
      actionRequiresAdmin: true,
    }
  }
  if (loopParticipantIds.value.length) {
    return {
      tone: loopOpenRunCount.value > 0 ? 'run' : 'ok',
      label: '执行面',
      title: '员工空间展示真实工作现场',
      detail: '当前页负责看哪些上岗员工参与 Loop；编制图谱负责治理和准入，完整 Loop 负责时间线。',
      cta: '看治理面',
      actionLabel: '观察 Loop 状态',
      actionStatus: loopOpenRunCount.value > 0 ? '运行中' : '就绪',
      actionExecutable: false,
      actionRequiresAdmin: false,
    }
  }
  return {
    tone: 'warn',
    label: '等待派发',
    title: 'Loop 尚未把任务落到工位',
    detail: '先等缺证阈值或 incident 触发；触发后这里会高亮真实上岗员工，编制图谱会显示治理结论。',
    cta: '看门禁',
    actionLabel: '等待派发',
    actionStatus: 'waiting',
    actionExecutable: false,
    actionRequiresAdmin: false,
  }
})

function loopRoleGroupKey(row: Record<string, unknown>): 'scout' | 'fix' | 'review' | 'qa' | 'verify' | 'ops' | 'other' {
  const text = [
    row.role,
    row.role_label,
    row.stage,
    row.stage_label,
    ...loopArray(row.stages),
    ...loopArray(row.stage_labels),
  ].map((x) => loopString(x).toLowerCase()).join(' ')
  if (/scout|侦察|intake|dispatch|router|感知/.test(text)) return 'scout'
  if (/fix|repair|coding|修复|编码/.test(text)) return 'fix'
  if (/review|validator|评审|审查/.test(text)) return 'review'
  if (/qa|test|sandbox|测试|质检/.test(text)) return 'qa'
  if (/verify|self-check|验证|自检/.test(text)) return 'verify'
  if (/ops|host|运维|恢复/.test(text)) return 'ops'
  return 'other'
}

const loopRoleGroups = computed(() => {
  const meta: Record<string, { label: string; workers: string[] }> = {
    scout: { label: '侦察 / 派发', workers: [] },
    fix: { label: '修复 / 编码', workers: [] },
    review: { label: '评审 / 风险', workers: [] },
    qa: { label: 'QA / 沙箱', workers: [] },
    verify: { label: '验证 / 自检', workers: [] },
    ops: { label: '运维 / 宿主', workers: [] },
    other: { label: '其他参与', workers: [] },
  }
  const seen = new Set<string>()
  const payload = loopRuntime.value || {}
  for (const item of loopArray(loopRecord(payload).participants)) {
    const row = loopRecord(item)
    const id = loopString(row.employee_id || row.id)
    if (!id || !ALL_PLANNED_YUANGON_PKG_IDS.value.has(id)) continue
    meta[loopRoleGroupKey(row)].workers.push(loopParticipantDisplay(id))
    seen.add(id)
  }
  for (const id of loopParticipantIds.value) {
    if (!seen.has(id)) meta.other.workers.push(loopParticipantDisplay(id))
  }
  return Object.entries(meta)
    .map(([key, value]) => ({ key, ...value }))
    .filter((group) => group.workers.length > 0)
})

function progressPct(row: WorkflowEmployeeDeskRow): number {
  if (!row.enabled) return 0
  const p = row.snapshot?.progressPct
  if (typeof p !== 'number' || !Number.isFinite(p)) return 0
  return Math.max(0, Math.min(100, p))
}

function progressWidth(row: WorkflowEmployeeDeskRow): string {
  return `${progressPct(row)}%`
}

function toggleDesk(empId: string, ev: Event) {
  ev.stopPropagation()
  wfEmp.toggle(empId)
}

function processedShort(row: WorkflowEmployeeDeskRow): string {
  const n = row.session?.processedCount ?? 0
  if (n <= 999) return String(n)
  if (n <= 9_999) return `${(n / 1000).toFixed(1)}k`
  return `${Math.floor(n / 1000)}k`
}

function workShort(row: WorkflowEmployeeDeskRow): string {
  if (!row.enabled) return '—'
  return formatWorkDurationShort(totalWorkMs(row.session, nowMs.value))
}

function isLoopParticipant(empId: string): boolean {
  return loopParticipantIds.value.includes(empId)
}

function deskLoopState(row: WorkflowEmployeeDeskRow) {
  if (isLoopParticipant(row.empId)) {
    return {
      tone: 'run',
      label: '参与 Loop',
      detail: loopParticipantRoleLabels.value[row.empId] || '已被 self-maintenance runtime 标记为本轮参与员工',
    }
  }
  if (!row.enabled) {
    return {
      tone: 'off',
      label: '未托管',
      detail: '工位没有开启副窗托管；不会作为当前工作现场展示忙态。',
    }
  }
  if (!loopRuntime.value) {
    return {
      tone: 'warn',
      label: 'Loop 未连接',
      detail: '员工空间未拿到 self-maintenance runtime，暂时无法判断是否参与本轮自维护。',
    }
  }
  if (!loopParticipantIds.value.length) {
    return {
      tone: 'idle',
      label: '待派发',
      detail: '当前 runtime 未暴露编制参与者，可能还没达到缺证阈值或 ledger 未回写 employee_id。',
    }
  }
  return {
    tone: 'idle',
    label: '未参与本轮',
    detail: '本轮 self-maintenance runtime 有其他编制员工参与，当前工位未被调度。',
  }
}

const selectedDeskLoopState = computed(() =>
  selectedDesk.value ? deskLoopState(selectedDesk.value) : null,
)
</script>

<template>
  <section class="ews" aria-labelledby="ews-heading" data-tour="employee-workspace-desks">
    <h3 id="ews-heading" class="ews-sr-only">员工工作流：入口与工位实况</h3>

    <router-link
      :to="panoramaLocation"
      class="ews-entry"
      role="link"
      :aria-label="entryCtaText"
    >
      <div class="ews-entry-bg" aria-hidden="true">
        <img
          class="ews-entry-bg-img"
          :src="entryBgUrl"
          alt=""
          decoding="async"
          fetchpriority="low"
          @error="onEntryBgError"
        />
        <div class="ews-entry-vignette" />
      </div>
      <div class="ews-entry-ui">
        <p class="ews-entry-kicker">{{ entryKicker }}</p>
        <p class="ews-entry-lead">{{ entryLead }}</p>
        <div class="ews-entry-cta" aria-hidden="true">
          <span class="ews-entry-cta-arrow">→</span>
          <span class="ews-entry-cta-text">{{ entryCtaText }}</span>
        </div>
      </div>
    </router-link>

    <DutyRosterWorkflowLoopView surface="employee-space" compact />
    <SelfEvolutionLoopRuntimePanel surface="employee-space" compact />

    <div class="ews-loop-console" role="region" aria-label="当前自进化循环员工">
      <div class="ews-loop-cockpit">
        <div class="ews-loop-cockpit-copy">
          <span>循环驾驶舱</span>
          <strong>上岗员工正在执行自进化/自维护流程线</strong>
          <p>
            员工空间只展示真实上岗工位的执行现场；补登记、隔离、治理审计这些高风险动作统一回到编制图谱处理。
          </p>
        </div>
        <div class="ews-loop-cockpit-meter" aria-label="循环总体状态">
          <span>{{ loopStatusLabel }}</span>
          <strong>{{ loopAlignedInDeployedCount }}/{{ loopAlignedPlannedCount }}</strong>
          <small>on-duty coverage</small>
        </div>
        <div class="ews-loop-cockpit-meter ews-loop-cockpit-meter--gate" aria-label="Loop 门禁状态">
          <span>{{ loopActiveGates.ok === false ? '异常' : '正常' }}</span>
          <strong>{{ loopActiveGates.blocking_count ?? 0 }}</strong>
          <small>阻断中</small>
        </div>
      </div>

      <div class="ews-loop-role-map" aria-label="员工空间、编制图谱与完整 Loop 分工">
        <div
          class="ews-loop-role-map-node ews-loop-role-map-node--active"
          :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface) === 'employee_space' }"
        >
          <span>员工空间</span>
          <strong>执行现场</strong>
          <small>看上岗员工、任务 step、证据回写</small>
          <small>{{ loopFocusedEmployeeId ? `focus ${loopFocusedEmployeeId}` : `${loopOpenRunCount} open runs` }}</small>
        </div>
        <div class="ews-loop-role-map-arrow">↔</div>
        <div
          class="ews-loop-role-map-node"
          :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface) === 'duty_roster_graph' }"
        >
          <span>排班图谱</span>
          <strong>治理闸门</strong>
          <small>补登记、隔离非编制、审计复核</small>
          <small>{{ loopNotDeployedCount }} pending deploy · {{ loopOutOfRosterCount }} isolated risk</small>
        </div>
        <div class="ews-loop-role-map-arrow">→</div>
        <div
          class="ews-loop-role-map-node"
          :class="{ 'ews-loop-role-map-node--route': loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface) === 'self_evolution_loop_runtime' }"
        >
          <span>运行时面板</span>
          <strong>完整链路</strong>
          <small>状态检查、模块异常、时间线</small>
          <small>{{ loopFirstText(loopRuntimeContractPrimaryRoute.view, '运行时') }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }}</small>
        </div>
      </div>

      <div
        class="ews-loop-directive"
        :class="loopRuntimeContractStatus.tone === 'bad' ? 'ews-loop-directive--bad' : (loopNumber(loopRuntimeSurfaceIncidentSummary.total) ? 'ews-loop-directive--warn' : 'ews-loop-directive--ok')"
        aria-label="Loop 下一步动作"
      >
        <div class="ews-loop-directive-copy">
          <span>下一步操作</span>
          <strong>{{ loopFirstText(loopRuntimeContractStatus.label, loopRuntimeSurfaceReadiness.title, loopRuntimeContractOk ? 'Loop 可继续观察' : '需要处理运行契约') }}</strong>
          <small>{{ loopFirstText(loopRuntimeContractStatus.detail, loopRuntimeContractPrimaryRoute.detail, loopRuntimeSurfaceReadiness.detail, '后端 runtime 会给出下一步 surface 和 action') }}</small>
        </div>
        <div class="ews-loop-directive-meta">
          <span>{{ loopFirstText(loopRuntimeContractPrimaryRoute.action, loopRuntimeContractStatus.primary_action, 'watch_loop') }}</span>
          <strong>{{ loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface, 'employee_space') }}</strong>
          <small>{{ loopRuntimeContractPrimaryRoute.requires_admin ? '仅管理员' : '操作员' }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }}</small>
          <small v-if="loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0])">target {{ loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
        </div>
        <router-link :to="loopRuntimePrimaryRouteLocation" class="ews-loop-directive-link">{{ loopRuntimePrimaryRouteLabel }}</router-link>
      </div>

      <div class="ews-loop-section-head" aria-label="三端健康对照说明">
        <span>模块就绪</span>
        <strong>三端对照，断点不混在员工卡里</strong>
        <small>员工空间 / 排班图谱 / 运行时面板 同源读取状态检查；未知不当作故障。</small>
        <div class="ews-loop-section-legend" aria-label="就绪三态图例">
          <span class="ews-loop-section-dot ews-loop-section-dot--ok">就绪</span>
          <span class="ews-loop-section-dot ews-loop-section-dot--bad">异常</span>
          <span class="ews-loop-section-dot ews-loop-section-dot--warn">未知</span>
        </div>
      </div>

      <div class="ews-loop-surface-grid" aria-label="三端模块就绪">
        <div
          v-for="surface in loopRuntimeSurfaceReadinessCards"
          :key="surface.key"
          class="ews-loop-surface-card"
          :class="`ews-loop-surface-card--${surface.tone}`"
        >
          <span>{{ surface.label }}</span>
          <strong>{{ surface.stateLabel }}</strong>
          <small>{{ surface.role }} · {{ surface.action }}</small>
          <small>{{ surface.target }} / {{ surface.view }}</small>
          <em>{{ surface.missing.length ? surface.missing.slice(0, 4).join(' / ') : surface.detail }}</em>
          <router-link
            v-if="surface.known"
            :to="loopRuntimePrimaryRouteLocation"
            :aria-label="`${surface.label} ${surface.ctaLabel}：${surface.detail}`"
            :title="`${surface.label} · ${surface.target} / ${surface.view}`"
          >{{ surface.ctaLabel }}</router-link>
          <span
            v-else
            class="ews-loop-surface-wait"
            :aria-label="`${surface.label} 等待状态：${surface.detail}`"
            :title="`${surface.label} · ${surface.target} / ${surface.view}`"
          >{{ surface.ctaLabel }}</span>
          <small v-if="surface.known" class="ews-loop-surface-route-note">统一入口 · {{ loopRuntimePrimaryRouteLabel }}</small>
          <small class="ews-loop-surface-source-note">{{ surface.sourceLabel }}</small>
        </div>
      </div>

      <div class="ews-loop-truth-strip" aria-label="Loop 真实数据来源">
        <div
          class="ews-loop-truth-card ews-loop-truth-card--primary"
          :class="loopRuntimeContractStatus.tone === 'bad' ? 'ews-loop-truth-card--bad' : (loopNumber(loopRuntimeSurfaceIncidentSummary.total) ? 'ews-loop-truth-card--warn' : 'ews-loop-truth-card--ok')"
        >
          <span>主状态</span>
          <strong>{{ loopFirstText(loopRuntimeContractStatus.state, loopRuntimeSurfaceIncidentSummary.status, loopRuntimeContractOk ? '正常' : '异常') }}</strong>
          <small>{{ loopFirstText(loopRuntimeContractPrimaryRoute.action, loopRuntimeContractStatus.primary_action, loopRuntimeSurfaceIncidentSummary.primary_action, loopRuntimeSurfaceReadiness.action, loopRuntimeContractOk ? 'all clear' : 'inspect contract') }} -> {{ loopFirstText(loopRuntimeContractPrimaryRoute.surface, loopRuntimeContractStatus.primary_target_surface, 'self_evolution_loop_runtime') }}</small>
          <small v-if="loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0])">target employee · {{ loopFirstText(loopRuntimeContractPrimaryRoute.employee_id, loopArray(loopRuntimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
          <small>全局={{ loopRuntimeContractStatus.global_ok === false ? '异常' : '正常' }} · 所有模块={{ loopRuntimeContractStatus.all_surfaces_ok === false ? '异常' : '正常' }}</small>
          <small>view={{ loopFirstText(loopRuntimeContractPrimaryRoute.view, 'runtime') }} · label={{ loopFirstText(loopRuntimeContractPrimaryRoute.label, loopRuntimePrimaryRouteLabel) }}</small>
          <small>{{ loopRuntimeContractPrimaryRoute.requires_admin ? '仅管理员' : '操作员' }} · {{ loopRuntimeContractPrimaryRoute.executable ? '可执行' : '仅导航' }} · {{ loopFirstText(loopRuntimeContractPrimaryRoute.detail, '按后端路由跳转') }}</small>
          <router-link :to="loopRuntimePrimaryRouteLocation">{{ loopRuntimePrimaryRouteLabel }}</router-link>
        </div>
        <div
          v-for="item in loopRuntimeTruthCards"
          :key="item.key"
          class="ews-loop-truth-card"
          :class="`ews-loop-truth-card--${item.tone}`"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.sub }}</small>
        </div>
      </div>

      <div v-if="loopRuntimeSurfaceIncidents.length" class="ews-loop-incident-list" aria-label="员工空间 contract incidents">
        <div
          v-for="incident in loopRuntimeSurfaceIncidents"
          :key="loopFirstText(incident.id, incident.action, incident.surface)"
          class="ews-loop-incident"
          :class="`ews-loop-incident--${loopFirstText(incident.severity, 'bad')}`"
        >
          <span>{{ loopFirstText(incident.surface, 'employee_space') }} · {{ loopFirstText(incident.severity, 'bad') }}</span>
          <strong>{{ loopFirstText(incident.title, 'Surface contract incident') }}</strong>
          <small>{{ loopFirstText(incident.action, 'inspect_runtime_contract') }} -> {{ loopFirstText(incident.target_surface, 'self_evolution_loop_runtime') }}</small>
          <small>target view · {{ loopFirstText(incident.target_view, loopRuntimeContractPrimaryRoute.view, 'runtime') }}</small>
          <small>{{ incident.requires_admin ? '仅管理员' : '操作员' }} · {{ incident.executable ? '可执行' : '仅导航' }} · {{ loopFirstText(incident.id, '状态:员工空间') }}</small>
          <small>{{ loopFirstText(incident.source, 'contract_validation') }} · {{ loopFirstText(incident.schema_version, loopRuntimeSchemaVersion) }} · {{ loopFirstText(incident.created_at, 'time unknown') }}</small>
          <em>{{ loopArray(incident.missing).map((item) => loopString(item)).filter(Boolean).slice(0, 5).join(' / ') || loopFirstText(incident.detail, 'missing dependencies') }}</em>
          <router-link :to="loopRuntimePrimaryRouteLocation">{{ loopRuntimePrimaryRouteLabel }}</router-link>
        </div>
      </div>

      <div class="ews-loop-freshness-strip" aria-label="Loop 数据新鲜度">
        <div
          v-for="item in loopRuntimeFreshnessCards"
          :key="item.key"
          class="ews-loop-freshness-card"
          :class="`ews-loop-freshness-card--${item.tone}`"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.sub }}</small>
        </div>
      </div>

      <div class="ews-loop-console-head">
        <div>
          <span class="ews-loop-workers-k">自进化桥接</span>
          <strong>自维护 Loop 正在把后端员工调度映射到工位</strong>
        </div>
        <div class="ews-loop-console-actions">
          <button type="button" class="ews-loop-console-status" @click="refreshLoopRuntime">
            {{ loopStatusLabel }}
          </button>
          <router-link :to="dutyRosterLoopLocation" class="ews-loop-console-link">完整 Loop</router-link>
          <router-link :to="dutyRosterDepartmentLocation" class="ews-loop-console-link">编制图谱</router-link>
        </div>
      </div>

      <div class="ews-loop-cards" role="list" aria-label="自维护 loop 摘要">
        <div
          v-for="card in loopRuntimeCards"
          :key="card.key"
          class="ews-loop-card"
          :class="`ews-loop-card--${card.tone}`"
          role="listitem"
        >
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>

      <div class="ews-loop-next-actions" aria-label="员工空间下一步建议">
        <router-link
          v-for="action in loopWorkspaceActionCards"
          :key="action.key"
          :to="action.to"
          class="ews-loop-next-action"
          :class="`ews-loop-next-action--${action.tone}`"
        >
          <span>{{ action.label }}</span>
          <strong>{{ action.title }}</strong>
          <small>{{ action.detail }}</small>
          <em>{{ action.cta }} →</em>
        </router-link>
      </div>

      <div
        v-if="loopFocusedWorkerTaskCard"
        class="ews-loop-focus-card"
        :class="`ews-loop-focus-card--${loopFocusedWorkerTaskCard.tone}`"
        aria-label="当前聚焦员工 loop 状态"
      >
        <span>关注员工</span>
        <strong>{{ loopFocusedWorkerTaskCard.id }} · {{ loopFocusedWorkerTaskCard.role }}</strong>
        <small>{{ loopFocusedWorkerTaskCard.department }} · {{ loopFocusedWorkerTaskCard.rosterLabel }} · {{ loopFocusedWorkerTaskCard.dutyLabel }}</small>
        <em>{{ loopFocusedWorkerTaskCard.eventCount }} steps · {{ loopFocusedWorkerTaskCard.latestStatus }}</em>
        <router-link :to="dutyRosterEmployeeLocation(loopFocusedWorkerTaskCard.id)">回编制图谱定位治理状态</router-link>
      </div>
      <div
        v-else-if="loopFocusedEmployeeId"
        class="ews-loop-focus-card ews-loop-focus-card--warn"
        aria-label="当前聚焦员工没有 loop 工单"
      >
        <span>关注员工</span>
        <strong>{{ loopFocusedEmployeeId }}</strong>
        <small>该员工当前没有 runtime/ledger 工单回写；页面不伪造任务。</small>
        <em>如果它应该参与 loop，请检查后端 participants 或 run_timelines 是否写 employee_id。</em>
        <router-link :to="dutyRosterEmployeeLocation(loopFocusedEmployeeId)">回编制图谱查编制状态</router-link>
      </div>

      <div class="ews-loop-pipeline" role="list" aria-label="自进化 loop 流水线">
        <div
          v-for="stage in loopPipelineStages"
          :key="stage.key"
          class="ews-loop-stage"
          :class="`ews-loop-stage--${stage.tone}`"
          role="listitem"
        >
          <span>{{ stage.label }}</span>
          <strong>{{ stage.count || (stage.tone === 'idle' ? '待命' : '进行中') }}</strong>
          <small>{{ stage.latest || stage.hint }}</small>
          <em v-if="stage.workers.length">{{ stage.workers.slice(0, 3).join(' / ') }}</em>
        </div>
      </div>

      <div v-if="loopActiveGateCards.length" class="ews-loop-gate-board" role="list" aria-label="当前 loop 门禁">
        <div
          v-for="gate in loopActiveGateCards"
          :key="gate.key"
          class="ews-loop-gate"
          :class="`ews-loop-gate--${gate.tone}`"
          role="listitem"
        >
          <span>{{ gate.label }}</span>
          <strong>{{ gate.value }}</strong>
          <small>{{ gate.sub }}</small>
        </div>
      </div>

      <div class="ews-loop-workers-list" :class="{ 'ews-loop-workers-list--empty': !loopParticipantIds.length }">
        <router-link
          v-for="id in loopParticipantIds"
          :key="id"
          :to="dutyRosterEmployeeLocation(id)"
          class="ews-loop-worker-chip ews-loop-worker-chip--link"
        >
          {{ loopParticipantDisplay(id) }}
        </router-link>
        <p v-if="!loopParticipantIds.length" class="ews-loop-workers-empty">
          当前 ledger 未暴露参与员工，等待后端 employee_id / actor 回写。
        </p>
      </div>

      <div v-if="loopWorkerTaskCards.length" class="ews-loop-task-board" aria-label="上岗员工 loop 任务工作台">
        <router-link
          v-for="worker in loopWorkerTaskCards"
          :key="worker.id"
          :to="dutyRosterEmployeeLocation(worker.id)"
          class="ews-loop-task-card"
          :class="`ews-loop-task-card--${worker.tone}`"
        >
          <span>{{ worker.role }}</span>
          <strong>{{ worker.id }}</strong>
          <small>{{ worker.department }} · {{ worker.rosterLabel }} · {{ worker.dutyLabel }}</small>
          <em>{{ worker.eventCount }} steps · {{ worker.latestStatus }}</em>
          <b v-if="worker.latestLabel">{{ worker.latestLabel }}</b>
        </router-link>
      </div>

      <div v-if="loopWorkOrderCards.length" class="ews-loop-work-orders" aria-label="本轮员工工作单">
        <router-link
          v-for="order in loopWorkOrderCards"
          :key="order.key"
          :to="order.to"
          class="ews-loop-work-order"
          :class="`ews-loop-work-order--${order.tone}`"
        >
          <span>{{ order.stage }}</span>
          <strong>{{ order.title }}</strong>
          <small>{{ order.status }} · {{ order.stepCount }} steps</small>
          <em v-if="order.workers.length">{{ order.workers.slice(0, 4).join(' / ') }}</em>
          <b>{{ order.runId }}</b>
        </router-link>
      </div>
      <div v-else class="ews-loop-work-orders-empty" aria-label="本轮没有员工工作单">
        <span>循环工单</span>
        <strong>没有记录工单</strong>
        <small>当前运行时间线没有可聚合的员工任务；等待后端写入运行 ID / 员工 ID / 步骤。</small>
      </div>

      <div class="ews-loop-separation-matrix" aria-label="员工身份隔离矩阵">
        <div
          v-for="item in loopEmployeeSeparationMatrix"
          :key="item.key"
          class="ews-loop-separation-cell"
          :class="`ews-loop-separation-cell--${item.tone}`"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
          <small>{{ item.sub }}</small>
        </div>
      </div>

      <div v-if="loopRoleGroups.length" class="ews-loop-role-board" aria-label="自进化 loop 角色分组">
        <div v-for="group in loopRoleGroups" :key="group.key" class="ews-loop-role-group">
          <span>{{ group.label }}</span>
          <strong>{{ group.workers.length }}</strong>
          <small>{{ group.workers.slice(0, 3).join(' / ') }}</small>
        </div>
      </div>

      <div class="ews-loop-isolation" aria-label="员工隔离状态">
        <div
          v-for="card in loopIsolationCards"
          :key="card.key"
          class="ews-loop-isolation-card"
          :class="`ews-loop-isolation-card--${card.tone}`"
        >
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>

      <div class="ews-loop-diagnosis" :class="`ews-loop-diagnosis--${loopDiagnosis.tone}`">
        <div>
          <span>诊断</span>
          <strong>{{ loopDiagnosis.title }}</strong>
          <p>{{ loopDiagnosis.detail }}</p>
          <div class="ews-loop-governance-bridge" :class="`ews-loop-governance-bridge--${loopGovernanceBridge.tone}`">
            <span>{{ loopGovernanceBridge.label }}</span>
            <strong>{{ loopGovernanceBridge.title }}</strong>
            <small>{{ loopGovernanceBridge.detail }}</small>
            <small class="ews-loop-governance-action">
              {{ loopGovernanceBridge.actionLabel }} · {{ loopGovernanceBridge.actionStatus }} · {{ loopGovernanceBridge.actionRequiresAdmin ? '仅管理员' : (loopGovernanceBridge.actionExecutable ? '可执行' : '仅查看') }}
            </small>
            <small v-if="loopGovernanceAuditLast.action" class="ews-loop-governance-audit">
              最近治理：{{ loopGovernanceAuditLast.action }} · {{ loopGovernanceAuditLast.status || (loopGovernanceAuditLast.ok === false ? 'failed' : 'success') }}<template v-if="loopGovernanceAuditLastSummary"> · {{ loopGovernanceAuditLastSummary }}</template><template v-if="loopGovernanceAuditLastTargets.length"> · {{ loopGovernanceAuditLastTargets.slice(0, 4).join(' / ') }}</template>
            </small>
            <small v-if="loopGovernanceAuditSummary.recent_count != null" class="ews-loop-governance-health">
              治理健康：{{ loopGovernanceAuditSummary.health || 'ok' }} · {{ loopGovernanceAuditSummary.success_count ?? 0 }} ok · {{ loopGovernanceAuditSummary.failure_count ?? 0 }} failed · 连续失败 {{ loopGovernanceAuditSummary.consecutive_failures ?? 0 }}
            </small>
            <small v-if="loopActiveGates.blocking_count != null" class="ews-loop-governance-gates">
              当前检查：{{ loopActiveGates.ok === false ? '异常' : '正常' }} · {{ loopActiveGates.blocking_count ?? 0 }} 阻断中<template v-if="loopActiveGateBlockingKeys.length"> · {{ loopActiveGateBlockingKeys.join(' / ') }}</template>
            </small>
            <small v-if="loopBridgeBlockedEmployeeIds.length" class="ews-loop-governance-isolation">
              隔离非编制：{{ loopBridgeBlockedEmployeeIds.slice(0, 5).join(' / ') }}
            </small>
            <router-link :to="dutyRosterGovernanceLocation">{{ loopGovernanceBridge.cta }}</router-link>
          </div>
          <div class="ews-loop-diagnosis-links">
            <router-link :to="dutyRosterLoopLocation">打开完整 Loop</router-link>
            <router-link :to="dutyRosterDepartmentLocation">查看编制覆盖</router-link>
          </div>
        </div>
        <ul>
          <li v-for="action in loopDiagnosis.actions" :key="action">{{ action }}</li>
        </ul>
      </div>

      <div v-if="routeFocusedEmployeeId && !routeFocusedEmployeeInWorkspace" class="ews-route-focus-warning">
        <strong>当前定位员工不在员工空间工位里</strong>
        <span>{{ routeFocusedEmployeeId }} 属于编制/管理图谱上下文，但没有出现在企业 Mod 栈工位集合；这说明它不是当前工作空间的上岗工位。</span>
        <router-link :to="dutyRosterEmployeeLocation(routeFocusedEmployeeId)">回编制图谱定位</router-link>
      </div>
    </div>

    <div class="ews-stats" role="list" aria-label="员工工位概要">
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">编制工位</p>
        <p class="ews-stat-v">{{ visualizedEmployeeCount }}</p>
        <p class="ews-stat-sub">编制主索引 + {{ workspaceStatSub }}</p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">已托管</p>
        <p class="ews-stat-v ews-stat-v--ok">{{ enabledCount }}</p>
        <p class="ews-stat-sub">副窗「一键托管」开</p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">工作中</p>
        <p class="ews-stat-v ews-stat-v--busy">{{ busyCount }}</p>
        <p class="ews-stat-sub">最近活跃 · 视觉态忙</p>
      </div>
      <div class="ews-stat" role="listitem">
        <p class="ews-stat-k">待命</p>
        <p class="ews-stat-v ews-stat-v--idle">{{ idleEnabledCount }}</p>
        <p class="ews-stat-sub">已托管但暂无忙态</p>
      </div>
    </div>

    <div
      id="ews-workflow-monitor"
      class="ews-monitor"
      role="region"
      aria-labelledby="ews-monitor-h"
      tabindex="-1"
    >
      <div class="ews-monitor-head">
        <div>
          <h4 id="ews-monitor-h" class="ews-monitor-title">工位实况</h4>
          <p class="ews-monitor-desc">
            实时工位状态来自副窗「一键托管」开关与任务面板快照；左侧点工位卡片、右侧员工列表均可切换选中并与开关联动。
          </p>
        </div>
      </div>

      <div class="ews-layout">
        <div class="ews-grid" role="list" aria-label="工位卡片列表">
          <div v-if="!workspaceDesks.length" class="ews-empty" role="listitem">
            <p class="ews-empty-title">
              {{ isAdminConsole ? '平台编制工位待同步' : '企业 Mod 工位待同步' }}
            </p>
            <p class="ews-empty-desc">
              编制员工已经由图谱对齐为 {{ rosterCount }} 岗；这里等待副窗托管或{{
                isAdminConsole ? '平台编制员工' : '企业 Mod 员工'
              }}注册后显示实时工位卡片。
            </p>
            <router-link :to="{ name: 'workflow-visualization' }" class="ews-empty-link">
              查看流程可视化
            </router-link>
          </div>
          <div
            v-for="row in workspaceDesks"
            :key="row.empId"
            class="ews-desk"
            :class="{
              'ews-desk--off': !row.enabled,
              'ews-desk--busy': isBusy(row),
              'ews-desk--loop': isLoopParticipant(row.empId),
              'ews-desk--selected': row.empId === selectedEmpId,
            }"
            role="listitem"
          >
            <button
              type="button"
              class="ews-desk-hit"
              :aria-current="row.empId === selectedEmpId ? 'true' : undefined"
              :aria-label="ariaLabel(row)"
              @click="selectDesk(row.empId)"
            >
              <span class="ews-desk-art" aria-hidden="true">
                <YuangongStation
                  :enabled="row.enabled"
                  :busy="isBusy(row)"
                  :ariaLabel="ariaLabel(row)"
                />
                <span
                  v-if="row.enabled"
                  class="ews-desk-rpg"
                  :class="{ 'ews-desk-rpg--busy': isBusy(row) }"
                  aria-hidden="true"
                >
                  <span class="ews-desk-rpg-row">
                    <span class="ews-desk-rpg-icon" aria-hidden="true">📄</span>
                    <span class="ews-desk-rpg-num">{{ processedShort(row) }}</span>
                  </span>
                  <span class="ews-desk-rpg-row">
                    <span class="ews-desk-rpg-icon" aria-hidden="true">⏱</span>
                    <span class="ews-desk-rpg-num">{{ workShort(row) }}</span>
                  </span>
                </span>
                <span
                  v-if="isBusy(row)"
                  class="ews-desk-pill ews-desk-pill--busy"
                >忙</span>
                <span
                  v-else-if="row.enabled"
                  class="ews-desk-pill ews-desk-pill--idle"
                >待命</span>
                <span v-else class="ews-desk-pill ews-desk-pill--off">未启</span>
              </span>

              <span class="ews-desk-meta">
                <span class="ews-desk-name" :title="row.panelTitle">{{ row.shortName }}</span>
                <span class="ews-desk-status">{{ statusLine(row) }}</span>
                <span v-if="isLoopParticipant(row.empId)" class="ews-desk-loop-role">
                  {{ loopParticipantRoleLabels[row.empId] || 'Self-evolution Loop' }}
                </span>
                <span
                  class="ews-desk-loop-state"
                  :class="`ews-desk-loop-state--${deskLoopState(row).tone}`"
                >
                  {{ deskLoopState(row).label }}
                </span>
                <span class="ews-desk-progress" aria-hidden="true">
                  <span
                    class="ews-desk-progress-bar"
                    :class="{ 'ews-desk-progress-bar--busy': isBusy(row) }"
                    :style="{ width: progressWidth(row) }"
                  />
                </span>
              </span>
            </button>

            <button
              type="button"
              class="ews-desk-toggle"
              :class="{ 'ews-desk-toggle--on': row.enabled }"
              role="switch"
              :aria-checked="row.enabled"
              :aria-label="(row.enabled ? '关闭' : '开启') + '副窗托管：' + row.shortName"
              @click="toggleDesk(row.empId, $event)"
            >
              <span class="ews-desk-toggle-track" aria-hidden="true">
                <span class="ews-desk-toggle-thumb" />
              </span>
              <span class="ews-desk-toggle-label">{{ row.enabled ? '已开' : '已关' }}</span>
            </button>
          </div>
        </div>

        <div class="ews-side">
          <div v-if="selectedDesk && selectedDeskLoopState" class="ews-selected-loop">
            <span>选中工位 Loop 上下文</span>
            <strong>{{ selectedDesk.shortName }}</strong>
            <p>{{ selectedDeskLoopState.detail }}</p>
            <div class="ews-selected-loop-actions">
              <router-link :to="dutyRosterEmployeeLocation(selectedDesk.empId)">去编制图谱定位</router-link>
              <router-link :to="dutyRosterLoopLocation">看完整 Loop</router-link>
            </div>
          </div>

          <WorkflowEmployeeInspector
            v-model:selected-emp-id="selectedEmpId"
            :desks="workspaceDesks"
            hide-workspace-link
          />
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap');

.ews-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

.ews {
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin-top: 0;
}

/* —— 入口横幅 —— */
.ews-entry {
  position: relative;
  display: block;
  border-radius: 12px;
  overflow: hidden;
  min-height: 180px;
  border: 1px solid #e5e7eb;
  background: #0f172a;
  text-decoration: none;
  color: inherit;
  isolation: isolate;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.ews-entry:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.18);
}

.ews-entry:focus {
  outline: none;
}

.ews-entry:focus-visible {
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.45);
}

.ews-entry-bg {
  position: absolute;
  inset: 0;
  z-index: 0;
}

.ews-entry-bg-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center bottom;
  image-rendering: pixelated;
  image-rendering: crisp-edges;
  display: block;
}

.ews-entry-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(90deg, rgba(15, 23, 42, 0.78) 0%, rgba(15, 23, 42, 0.32) 45%, rgba(15, 23, 42, 0.05) 100%),
    linear-gradient(180deg, rgba(15, 23, 42, 0.05) 0%, rgba(15, 23, 42, 0.55) 100%);
}

.ews-entry-ui {
  position: relative;
  z-index: 1;
  min-height: 180px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  gap: 10px;
  padding: 20px 24px;
  max-width: 32rem;
}

.ews-entry-kicker {
  margin: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 10px;
  line-height: 1.5;
  letter-spacing: 0.08em;
  color: #93c5fd;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);
}

.ews-entry-lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);
}

.ews-entry-cta {
  margin-top: 4px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  background: rgba(37, 99, 235, 0.92);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35);
}

.ews-entry-cta-arrow {
  font-size: 14px;
  transition: transform 0.2s ease;
}

.ews-entry:hover .ews-entry-cta-arrow {
  transform: translateX(3px);
}

.ews-empty-link {
  flex: 0 0 auto;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  padding: 8px 10px;
  text-decoration: none;
}

.ews-empty-link:hover {
  background: #dbeafe;
}

/* —— 概要数据条 —— */
.ews-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
}

.ews-stat {
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ews-stat-k {
  margin: 0;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  letter-spacing: 0.04em;
}

.ews-stat-v {
  margin: 0;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 22px;
  line-height: 1.3;
  color: #111827;
  font-variant-numeric: tabular-nums;
}

.ews-stat-v--ok {
  color: #059669;
}

.ews-stat-v--busy {
  color: #2563eb;
}

.ews-stat-v--idle {
  color: #7c3aed;
}

.ews-stat-sub {
  margin: 0;
  font-size: 11px;
  line-height: 1.45;
  color: #9ca3af;
}

/* —— 工位实况 —— */
.ews-monitor {
  padding: 14px 14px 16px;
  border-radius: 12px;
  border: 1px solid #e5e7eb;
  background: linear-gradient(180deg, #f9fafb 0%, #fff 50%);
  outline: none;
}

.ews-monitor-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.ews-monitor-title {
  margin: 0 0 4px;
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}

.ews-monitor-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: #6b7280;
  max-width: 56rem;
}

.ews-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
  gap: 14px;
  align-items: start;
}

@media (max-width: 880px) {
  .ews-layout {
    grid-template-columns: 1fr;
  }
}

.ews-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}

.ews-empty {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 180px;
  border: 1px dashed #bfdbfe;
  border-radius: 12px;
  background: #eff6ff;
  padding: 18px;
  justify-content: center;
}

.ews-empty-title {
  margin: 0;
  color: #1e3a8a;
  font-size: 14px;
  font-weight: 800;
}

.ews-empty-desc {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.ews-empty-link {
  align-self: flex-start;
  background: #fff;
}

.ews-desk {
  position: relative;
  display: flex;
  flex-direction: column;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fff;
  overflow: hidden;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}

.ews-desk:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.1);
  border-color: #cbd5e1;
}

.ews-desk--off {
  background: #f9fafb;
}

.ews-desk--off .ews-desk-art {
  filter: grayscale(0.35);
  opacity: 0.85;
}

.ews-desk--busy {
  border-color: #93c5fd;
  background: linear-gradient(180deg, #f5faff 0%, #ffffff 60%);
}

.ews-desk--selected {
  border-color: #2563eb;
  box-shadow: 0 0 0 1px #93c5fd inset, 0 8px 24px rgba(37, 99, 235, 0.18);
}

.ews-desk-hit {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 10px;
  padding: 10px 12px 10px;
  margin: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
}

.ews-desk-hit:focus {
  outline: none;
}

.ews-desk-hit:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
  border-radius: 10px;
}

.ews-desk-art {
  position: relative;
  width: 100%;
  aspect-ratio: 4 / 3;
  border-radius: 10px;
  overflow: hidden;
  background:
    radial-gradient(ellipse at 50% 90%, rgba(37, 99, 235, 0.08) 0%, transparent 65%),
    linear-gradient(180deg, #eef2ff 0%, #ffffff 75%);
  display: block;
  border: 1px solid #e5e7eb;
}

.ews-desk-art :deep(.yuangong-stack) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.ews-desk-art :deep(.yuangong-desk) {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center bottom;
  max-width: none;
  max-height: none;
}

.ews-desk-art :deep(.yuangong-staff) {
  position: absolute;
  inset: 0;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  object-position: center bottom;
  max-width: none;
  max-height: none;
}

/* —— RPG 风格量化数据：员工头顶悬浮的「已处理 / 在岗工时」 —— */
.ews-desk-rpg {
  position: absolute;
  top: 6px;
  left: 6px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 4px 6px;
  border-radius: 4px;
  background: rgba(11, 17, 32, 0.78);
  box-shadow: inset 0 0 0 1px rgba(56, 189, 248, 0.45), 0 1px 0 rgba(0, 0, 0, 0.45);
  color: #f1f5f9;
  font-family: 'Press Start 2P', ui-monospace, monospace;
  font-size: 8px;
  line-height: 1.3;
  letter-spacing: 0.03em;
  pointer-events: none;
  image-rendering: pixelated;
}

.ews-desk-rpg--busy {
  box-shadow:
    inset 0 0 0 1px rgba(96, 165, 250, 0.85),
    0 0 0 2px rgba(96, 165, 250, 0.18),
    0 1px 0 rgba(0, 0, 0, 0.45);
}

.ews-desk-rpg-row {
  display: flex;
  align-items: center;
  gap: 4px;
}

.ews-desk-rpg-icon {
  font-size: 10px;
  line-height: 1;
}

.ews-desk-rpg-num {
  color: #7dd3fc;
  font-variant-numeric: tabular-nums;
}

.ews-desk-pill {
  position: absolute;
  top: 6px;
  right: 6px;
  z-index: 2;
  padding: 3px 7px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #fff;
  background: rgba(15, 23, 42, 0.55);
  text-shadow: 0 1px 1px rgba(0, 0, 0, 0.4);
}

.ews-desk-pill--busy {
  background: linear-gradient(180deg, #2563eb 0%, #1d4ed8 100%);
}

.ews-desk-pill--idle {
  background: linear-gradient(180deg, #7c3aed 0%, #6d28d9 100%);
}

.ews-desk-pill--off {
  background: rgba(107, 114, 128, 0.85);
}

.ews-desk-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ews-desk-name {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #111827;
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ews-desk-status {
  display: -webkit-box;
  font-size: 12px;
  line-height: 1.45;
  color: #6b7280;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 2.9em;
}

.ews-desk-progress {
  display: block;
  width: 100%;
  height: 5px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
  margin-top: 2px;
}

.ews-desk-progress-bar {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #cbd5e1 0%, #94a3b8 100%);
  transition: width 0.25s ease;
}

.ews-desk-progress-bar--busy {
  background: linear-gradient(90deg, #60a5fa 0%, #2563eb 100%);
}

.ews-desk-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  align-self: flex-start;
  margin: 0 12px 12px;
  padding: 4px 10px 4px 4px;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #f9fafb;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  cursor: pointer;
  user-select: none;
  text-align: left;
}

.ews-desk-toggle:focus {
  outline: none;
}

.ews-desk-toggle:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}

.ews-desk-toggle--on {
  background: #eff6ff;
  border-color: #93c5fd;
  color: #1d4ed8;
}

.ews-desk-toggle-track {
  position: relative;
  width: 26px;
  height: 14px;
  border-radius: 999px;
  background: #cbd5e1;
  display: inline-block;
  transition: background 0.2s ease;
}

.ews-desk-toggle--on .ews-desk-toggle-track {
  background: #2563eb;
}

.ews-desk-toggle-thumb {
  position: absolute;
  top: 1px;
  left: 1px;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
  transition: transform 0.2s ease;
}

.ews-desk-toggle--on .ews-desk-toggle-thumb {
  transform: translateX(12px);
}

.ews-desk-toggle-label {
  font-variant-numeric: tabular-nums;
}

/* —— 自进化 Loop 控制台：让后端员工调度在工位页可见 —— */
.ews-loop-console {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 13px 14px;
  border: 1px solid #dbe3ef;
  border-left: 4px solid #0f766e;
  border-radius: 12px;
  background:
    radial-gradient(circle at 8% 0%, rgba(20, 184, 166, 0.13), transparent 34%),
    linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}

.ews-loop-console-head,
.ews-loop-workers-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.ews-loop-console-head {
  justify-content: space-between;
}

.ews-loop-console-head > div {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.ews-loop-workers-k {
  color: #0f766e;
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.ews-loop-console-head strong {
  color: #0f172a;
  font-size: 14px;
}

.ews-loop-console-status {
  flex: 0 0 auto;
  border: 1px solid rgba(15, 118, 110, 0.22);
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 900;
  padding: 6px 10px;
}

.ews-loop-console-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ews-loop-console-link {
  flex: 0 0 auto;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.18);
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-cards {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.78);
}

.ews-loop-card--run {
  background: #ecfeff;
  border-color: rgba(20, 184, 166, 0.20);
}

.ews-loop-card--ok {
  background: #f0fdf4;
}

.ews-loop-card--warn {
  background: #fffbeb;
}

.ews-loop-card--bad {
  background: #fef2f2;
}

.ews-loop-card span,
.ews-loop-card small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 16px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-worker-chip {
  max-width: 220px;
  overflow: hidden;
  padding: 6px 9px;
  border-radius: 999px;
  background: #ccfbf1;
  color: #134e4a;
  font-size: 12px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-worker-chip--link {
  text-decoration: none;
}

.ews-loop-worker-chip--link:hover {
  background: #99f6e4;
}

.ews-loop-workers-list--empty {
  align-items: flex-start;
}

.ews-loop-role-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-role-group {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  align-items: center;
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  border: 1px dashed rgba(15, 118, 110, 0.20);
  background: rgba(240, 253, 250, 0.70);
}

.ews-loop-role-group span,
.ews-loop-role-group small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-role-group span {
  color: #0f766e;
  font-weight: 900;
}

.ews-loop-role-group strong {
  color: #0f172a;
  font-size: 14px;
}

.ews-loop-role-group small {
  grid-column: 1 / -1;
}

.ews-loop-isolation {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-isolation-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.70);
}

.ews-loop-isolation-card--run {
  border-color: rgba(20, 184, 166, 0.18);
  background: #ecfeff;
}

.ews-loop-isolation-card--ok {
  background: #f0fdf4;
}

.ews-loop-isolation-card--warn {
  background: #fffbeb;
}

.ews-loop-isolation-card--bad {
  background: #fef2f2;
}

.ews-loop-isolation-card span,
.ews-loop-isolation-card small {
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-isolation-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-console,
.ews-loop-console > * {
  --loop-compact-card-min: 145px;
  --loop-detail-card-min: 220px;
  min-width: 0;
}

.ews-loop-cockpit {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, 160px) minmax(120px, 160px);
  gap: 10px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.18), transparent 32%),
    radial-gradient(circle at 100% 0%, rgba(14, 165, 233, 0.14), transparent 34%),
    linear-gradient(135deg, rgba(248, 250, 252, 0.94), rgba(255, 255, 255, 0.82));
}

.ews-loop-cockpit-copy {
  min-width: 0;
}

.ews-loop-cockpit-copy span,
.ews-loop-cockpit-meter span {
  display: block;
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-cockpit-copy strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 17px;
  font-weight: 950;
  letter-spacing: -0.02em;
}

.ews-loop-cockpit-copy p {
  max-width: 760px;
  margin: 6px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.55;
}

.ews-loop-cockpit-meter {
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 14px;
  background: rgba(236, 254, 255, 0.82);
}

.ews-loop-cockpit-meter--gate {
  border-color: rgba(99, 102, 241, 0.18);
  background: rgba(238, 242, 255, 0.82);
}

.ews-loop-cockpit-meter strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 22px;
  font-weight: 950;
  letter-spacing: -0.04em;
}

.ews-loop-cockpit-meter small {
  display: block;
  margin-top: 3px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
}

.ews-loop-role-map {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 8% 20%, rgba(20, 184, 166, 0.14), transparent 26%),
    radial-gradient(circle at 92% 10%, rgba(14, 165, 233, 0.12), transparent 30%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.04), rgba(255, 255, 255, 0.84));
}

.ews-loop-role-map-node {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
}

.ews-loop-role-map-node--active {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.92), rgba(240, 253, 250, 0.76));
}

.ews-loop-role-map-node--route {
  border-color: rgba(14, 165, 233, 0.38);
  box-shadow: 0 0 0 2px rgba(14, 165, 233, 0.1), 0 14px 32px rgba(14, 165, 233, 0.1);
}

.ews-loop-role-map-node span,
.ews-loop-role-map-node strong,
.ews-loop-role-map-node small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-role-map-node span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-role-map-node strong {
  margin-top: 4px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 950;
}

.ews-loop-role-map-node small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.35;
}

.ews-loop-role-map-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  color: rgba(15, 118, 110, 0.78);
  font-size: 18px;
  font-weight: 950;
}

.ews-loop-directive {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.7fr) max-content;
  gap: 10px;
  align-items: center;
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 18px;
  background:
    radial-gradient(circle at 0% 0%, rgba(45, 212, 191, 0.22), transparent 30%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(15, 118, 110, 0.84));
  color: #f8fafc;
  box-shadow: 0 18px 42px rgba(15, 23, 42, 0.16);
}

.ews-loop-directive--ok {
  background:
    radial-gradient(circle at 0% 0%, rgba(16, 185, 129, 0.24), transparent 30%),
    linear-gradient(135deg, rgba(6, 78, 59, 0.94), rgba(15, 118, 110, 0.86));
}

.ews-loop-directive--warn {
  background:
    radial-gradient(circle at 0% 0%, rgba(251, 191, 36, 0.22), transparent 30%),
    linear-gradient(135deg, rgba(120, 53, 15, 0.94), rgba(180, 83, 9, 0.84));
}

.ews-loop-directive--bad {
  background:
    radial-gradient(circle at 0% 0%, rgba(248, 113, 113, 0.24), transparent 30%),
    linear-gradient(135deg, rgba(127, 29, 29, 0.96), rgba(185, 28, 28, 0.84));
}

.ews-loop-directive-copy,
.ews-loop-directive-meta {
  min-width: 0;
}

.ews-loop-directive-copy span,
.ews-loop-directive-meta span {
  display: block;
  color: rgba(240, 253, 250, 0.78);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-directive-copy strong,
.ews-loop-directive-meta strong {
  display: block;
  margin-top: 4px;
  color: #ffffff;
  font-size: 15px;
  font-weight: 950;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-directive-copy small,
.ews-loop-directive-meta small {
  display: block;
  margin-top: 4px;
  color: rgba(241, 245, 249, 0.78);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.45;
}

.ews-loop-directive-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: end;
  min-width: 0;
  max-width: 100%;
  min-height: 32px;
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  color: #ffffff;
  font-size: 12px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-directive-link:hover {
  background: rgba(255, 255, 255, 0.22);
}

.ews-loop-section-head {
  display: grid;
  grid-template-columns: minmax(0, 0.32fr) minmax(0, 0.68fr);
  gap: 6px 10px;
  align-items: baseline;
  min-width: 0;
  padding: 2px 2px 0;
}

.ews-loop-section-head span,
.ews-loop-section-head strong,
.ews-loop-section-head small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-section-head span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-section-head strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-section-head small {
  grid-column: 1 / -1;
  color: #64748b;
  font-size: 11px;
  font-weight: 800;
  white-space: normal;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.ews-loop-section-legend {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.ews-loop-section-dot {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 3px 7px;
  border-radius: 999px;
  color: #475569;
  font-size: 10px;
  font-weight: 950;
  line-height: 1;
  white-space: nowrap;
}

.ews-loop-section-dot::before {
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 999px;
  background: currentColor;
  content: '';
}

.ews-loop-section-dot--ok {
  background: rgba(16, 185, 129, 0.1);
  color: #047857;
}

.ews-loop-section-dot--bad {
  background: rgba(239, 68, 68, 0.1);
  color: #b91c1c;
}

.ews-loop-section-dot--warn {
  background: rgba(245, 158, 11, 0.12);
  color: #92400e;
}

.ews-loop-surface-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-surface-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.84);
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.05);
  isolation: isolate;
}

.ews-loop-surface-card--ok {
  border-color: rgba(16, 185, 129, 0.22);
  background: linear-gradient(135deg, rgba(236, 253, 245, 0.92), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.96), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card--bad {
  border-color: rgba(239, 68, 68, 0.24);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.98), rgba(255, 255, 255, 0.84));
}

.ews-loop-surface-card span,
.ews-loop-surface-card strong,
.ews-loop-surface-card small,
.ews-loop-surface-card em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-surface-card span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.ews-loop-surface-card strong {
  margin-top: 4px;
  color: #0f172a;
  font-size: 16px;
  font-weight: 950;
}

.ews-loop-surface-card small,
.ews-loop-surface-card em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.ews-loop-surface-card a,
.ews-loop-surface-wait {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 8px;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.1);
  color: #0f766e;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-surface-card a:hover {
  background: rgba(15, 118, 110, 0.16);
}

.ews-loop-surface-route-note {
  color: #94a3b8;
}

.ews-loop-surface-source-note {
  color: #94a3b8;
  font-size: 10px;
}

.ews-loop-surface-wait {
  background: rgba(100, 116, 139, 0.1);
  color: #64748b;
  cursor: default;
}

.ews-loop-surface-card a:focus-visible,
.ews-loop-directive-link:focus-visible,
.ews-loop-truth-card a:focus-visible,
.ews-loop-incident a:focus-visible {
  outline: 2px solid rgba(14, 165, 233, 0.72);
  outline-offset: 2px;
}

.ews-loop-directive-copy small,
.ews-loop-surface-card em {
  display: -webkit-box;
  overflow: hidden;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

@media (max-width: 1180px) {
  .ews-loop-cockpit {
    grid-template-columns: 1fr;
  }

  .ews-loop-cockpit-copy p {
    max-width: none;
  }

  .ews-loop-role-map {
    grid-template-columns: 1fr;
  }

  .ews-loop-role-map-arrow {
    min-height: 18px;
    transform: rotate(90deg);
  }

  .ews-loop-directive {
    grid-template-columns: 1fr;
  }

  .ews-loop-directive-link {
    justify-self: start;
  }

  .ews-loop-section-head {
    grid-template-columns: 1fr;
  }

  .ews-loop-surface-grid {
    grid-template-columns: 1fr;
  }

  .ews-loop-truth-card--primary {
    grid-column: auto;
  }

  .ews-loop-freshness-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.ews-loop-truth-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-truth-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.9);
}

.ews-loop-truth-card span,
.ews-loop-truth-card strong,
.ews-loop-truth-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-truth-card span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-truth-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-truth-card small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-truth-card a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-truth-card--run {
  border-color: rgba(14, 165, 233, 0.22);
  background: rgba(240, 249, 255, 0.9);
}

.ews-loop-truth-card--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-truth-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-truth-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(254, 242, 242, 0.9);
}

.ews-loop-truth-card--primary {
  grid-column: span 2;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.16), transparent 34%),
    rgba(255, 255, 255, 0.94);
}

.ews-loop-incident-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-detail-card-min), 1fr));
  gap: 8px;
  min-width: 0;
}

.ews-loop-incident {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 14px;
  background:
    radial-gradient(circle at 0% 0%, rgba(239, 68, 68, 0.12), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-incident--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background:
    radial-gradient(circle at 0% 0%, rgba(245, 158, 11, 0.12), transparent 34%),
    rgba(255, 251, 235, 0.9);
}

.ews-loop-incident span,
.ews-loop-incident strong,
.ews-loop-incident small,
.ews-loop-incident em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-incident span {
  color: #991b1b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-incident strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-incident small,
.ews-loop-incident em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-incident a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-freshness-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  min-width: 0;
  gap: 8px;
}

.ews-loop-freshness-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.88);
}

.ews-loop-freshness-card span,
.ews-loop-freshness-card strong,
.ews-loop-freshness-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-freshness-card span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-freshness-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-freshness-card small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-freshness-card--run {
  border-color: rgba(14, 165, 233, 0.22);
  background: rgba(240, 249, 255, 0.9);
}

.ews-loop-freshness-card--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-freshness-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-next-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-next-action {
  display: block;
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  color: inherit;
  text-decoration: none;
}

.ews-loop-next-action span,
.ews-loop-next-action strong,
.ews-loop-next-action small,
.ews-loop-next-action em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-next-action span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-next-action strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-next-action small,
.ews-loop-next-action em {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-next-action em {
  color: #0f766e;
  font-weight: 950;
}

.ews-loop-next-action--run {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.92), rgba(255, 255, 255, 0.88));
}

.ews-loop-next-action--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-next-action--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.92), rgba(255, 255, 255, 0.88));
}

.ews-loop-next-action--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.94), rgba(255, 255, 255, 0.88));
}

.ews-loop-focus-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  padding: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 15px;
  background:
    radial-gradient(circle at 0% 0%, rgba(14, 165, 233, 0.12), transparent 30%),
    rgba(255, 255, 255, 0.9);
}

.ews-loop-focus-card span,
.ews-loop-focus-card strong,
.ews-loop-focus-card small,
.ews-loop-focus-card em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-focus-card span {
  color: #0369a1;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-focus-card strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-focus-card small,
.ews-loop-focus-card em {
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-focus-card a {
  grid-column: 2;
  grid-row: 1 / span 4;
  padding: 7px 10px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  white-space: nowrap;
}

.ews-loop-focus-card--run {
  border-color: rgba(14, 165, 233, 0.22);
}

.ews-loop-focus-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 0% 0%, rgba(239, 68, 68, 0.12), transparent 30%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-focus-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background:
    radial-gradient(circle at 0% 0%, rgba(245, 158, 11, 0.12), transparent 30%),
    rgba(255, 251, 235, 0.9);
}

.ews-loop-pipeline,
.ews-loop-gate-board {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-gate-board {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.ews-loop-stage,
.ews-loop-gate {
  position: relative;
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background: rgba(248, 250, 252, 0.88);
}

.ews-loop-stage::before {
  content: "";
  position: absolute;
  top: 13px;
  right: -18px;
  width: 42px;
  height: 2px;
  background: linear-gradient(90deg, rgba(20, 184, 166, 0.6), rgba(59, 130, 246, 0));
}

.ews-loop-stage:last-child::before {
  display: none;
}

.ews-loop-stage span,
.ews-loop-gate span {
  display: block;
  color: #64748b;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-stage strong,
.ews-loop-gate strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  font-weight: 950;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-stage small,
.ews-loop-gate small,
.ews-loop-stage em {
  display: block;
  margin-top: 4px;
  overflow: hidden;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-stage--run,
.ews-loop-gate--ok {
  border-color: rgba(20, 184, 166, 0.2);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.95), rgba(240, 253, 244, 0.92));
}

.ews-loop-stage--bad,
.ews-loop-gate--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.95), rgba(255, 247, 237, 0.92));
}

.ews-loop-stage--idle {
  opacity: 0.72;
}

.ews-loop-task-board {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-task-card {
  display: block;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    radial-gradient(circle at 12% 0%, rgba(20, 184, 166, 0.14), transparent 34%),
    rgba(255, 255, 255, 0.88);
  color: inherit;
  text-decoration: none;
}

.ews-loop-task-card span,
.ews-loop-task-card strong,
.ews-loop-task-card small,
.ews-loop-task-card em,
.ews-loop-task-card b {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-task-card span {
  color: #0f766e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-task-card strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-task-card small,
.ews-loop-task-card em,
.ews-loop-task-card b {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-task-card b {
  color: #334155;
  font-weight: 900;
}

.ews-loop-task-card--run {
  border-color: rgba(20, 184, 166, 0.24);
  box-shadow: 0 10px 24px rgba(20, 184, 166, 0.08);
}

.ews-loop-task-card--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 12% 0%, rgba(239, 68, 68, 0.14), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-task-card--idle {
  opacity: 0.76;
}

.ews-loop-work-orders {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-work-order {
  display: block;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    radial-gradient(circle at 100% 0%, rgba(14, 165, 233, 0.12), transparent 34%),
    rgba(248, 250, 252, 0.9);
  color: inherit;
  text-decoration: none;
}

.ews-loop-work-order span,
.ews-loop-work-order strong,
.ews-loop-work-order small,
.ews-loop-work-order em,
.ews-loop-work-order b {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-work-order span {
  color: #0369a1;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-work-order strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 950;
}

.ews-loop-work-order small,
.ews-loop-work-order em,
.ews-loop-work-order b {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.ews-loop-work-order b {
  color: #334155;
  font-weight: 850;
}

.ews-loop-work-order--run {
  border-color: rgba(14, 165, 233, 0.22);
}

.ews-loop-work-order--ok {
  border-color: rgba(34, 197, 94, 0.18);
  background:
    radial-gradient(circle at 100% 0%, rgba(34, 197, 94, 0.12), transparent 34%),
    rgba(240, 253, 244, 0.9);
}

.ews-loop-work-order--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background:
    radial-gradient(circle at 100% 0%, rgba(239, 68, 68, 0.14), transparent 34%),
    rgba(254, 242, 242, 0.9);
}

.ews-loop-work-orders-empty {
  padding: 11px;
  border: 1px dashed rgba(245, 158, 11, 0.38);
  border-radius: 14px;
  background: rgba(255, 251, 235, 0.88);
}

.ews-loop-work-orders-empty span,
.ews-loop-work-orders-empty strong,
.ews-loop-work-orders-empty small {
  display: block;
}

.ews-loop-work-orders-empty span {
  color: #92400e;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-work-orders-empty strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 950;
}

.ews-loop-work-orders-empty small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.4;
}

.ews-loop-separation-matrix {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ews-loop-separation-cell {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 13px;
  background:
    linear-gradient(135deg, rgba(15, 23, 42, 0.03), rgba(20, 184, 166, 0.05)),
    rgba(255, 255, 255, 0.9);
}

.ews-loop-separation-cell span,
.ews-loop-separation-cell strong,
.ews-loop-separation-cell small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-loop-separation-cell span {
  color: #64748b;
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ews-loop-separation-cell strong {
  margin-top: 3px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 950;
}

.ews-loop-separation-cell small {
  margin-top: 4px;
  color: #64748b;
  font-size: 11px;
  line-height: 1.35;
}

.ews-loop-separation-cell--run {
  border-color: rgba(20, 184, 166, 0.24);
  background: linear-gradient(135deg, rgba(236, 254, 255, 0.95), rgba(255, 255, 255, 0.9));
}

.ews-loop-separation-cell--ok {
  border-color: rgba(34, 197, 94, 0.18);
}

.ews-loop-separation-cell--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: linear-gradient(135deg, rgba(255, 251, 235, 0.95), rgba(255, 255, 255, 0.9));
}

.ews-loop-separation-cell--bad {
  border-color: rgba(239, 68, 68, 0.2);
  background: linear-gradient(135deg, rgba(254, 242, 242, 0.95), rgba(255, 255, 255, 0.9));
}

@media (max-width: 760px) {
  .ews-loop-cockpit {
    grid-template-columns: minmax(0, 1fr);
  }

  .ews-loop-focus-card {
    grid-template-columns: minmax(0, 1fr);
  }

  .ews-loop-focus-card a {
    grid-column: 1;
    grid-row: auto;
    width: fit-content;
  }

  .ews-loop-truth-strip,
  .ews-loop-freshness-strip,
  .ews-loop-next-actions,
  .ews-loop-pipeline,
  .ews-loop-gate-board,
  .ews-loop-task-board,
  .ews-loop-work-orders,
  .ews-loop-separation-matrix {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .ews-loop-truth-strip,
  .ews-loop-freshness-strip,
  .ews-loop-next-actions,
  .ews-loop-pipeline,
  .ews-loop-gate-board,
  .ews-loop-task-board,
  .ews-loop-work-orders,
  .ews-loop-separation-matrix {
    grid-template-columns: minmax(0, 1fr);
  }
}

.ews-loop-diagnosis {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(180px, 280px);
  gap: 10px;
  align-items: stretch;
  padding: 10px 11px;
  border-radius: 11px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.72);
}

.ews-loop-diagnosis--run {
  border-color: rgba(20, 184, 166, 0.22);
  background: #ecfeff;
}

.ews-loop-diagnosis--ok {
  background: #f0fdf4;
}

.ews-loop-diagnosis--warn {
  background: #fffbeb;
}

.ews-loop-diagnosis--bad {
  background: #fef2f2;
}

.ews-loop-diagnosis div {
  min-width: 0;
}

.ews-loop-diagnosis span {
  display: block;
  margin-bottom: 2px;
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.05em;
}

.ews-loop-diagnosis strong {
  display: block;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.ews-loop-diagnosis p {
  margin: 4px 0 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.ews-loop-diagnosis-links {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.ews-loop-governance-bridge {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 3px 8px;
  align-items: center;
  margin-top: 9px;
  padding: 8px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.82);
}

.ews-loop-governance-bridge--run {
  border-color: rgba(20, 184, 166, 0.22);
  background: rgba(236, 254, 255, 0.9);
}

.ews-loop-governance-bridge--ok {
  border-color: rgba(34, 197, 94, 0.18);
  background: rgba(240, 253, 244, 0.9);
}

.ews-loop-governance-bridge--warn {
  border-color: rgba(245, 158, 11, 0.22);
  background: rgba(255, 251, 235, 0.9);
}

.ews-loop-governance-bridge--bad {
  border-color: rgba(239, 68, 68, 0.18);
  background: rgba(254, 242, 242, 0.9);
}

.ews-loop-governance-bridge span,
.ews-loop-governance-bridge strong,
.ews-loop-governance-bridge small {
  min-width: 0;
}

.ews-loop-governance-bridge span {
  grid-column: 1;
  margin: 0;
  color: #0f766e;
}

.ews-loop-governance-bridge strong {
  grid-column: 1;
  font-size: 12px;
}

.ews-loop-governance-bridge small {
  grid-column: 1 / -1;
  color: #64748b;
  font-size: 11px;
  line-height: 1.45;
}

.ews-loop-governance-bridge .ews-loop-governance-isolation {
  color: #b91c1c;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-action {
  color: #0f766e;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-audit {
  color: #0369a1;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-health {
  color: #854d0e;
  font-weight: 900;
}

.ews-loop-governance-bridge .ews-loop-governance-gates {
  color: #4338ca;
  font-weight: 900;
}

.ews-loop-governance-bridge a {
  grid-column: 2;
  grid-row: 1 / span 2;
  padding: 6px 9px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
  white-space: nowrap;
}

.ews-loop-diagnosis-links a {
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.07);
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-diagnosis ul {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.ews-loop-diagnosis li {
  overflow: hidden;
  padding: 4px 7px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.06);
  color: #334155;
  font-size: 11px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-route-focus-warning {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 4px 10px;
  align-items: center;
  padding: 10px 11px;
  border: 1px solid rgba(245, 158, 11, 0.28);
  border-radius: 11px;
  background: #fffbeb;
}

.ews-route-focus-warning strong {
  color: #92400e;
  font-size: 13px;
  font-weight: 900;
}

.ews-route-focus-warning span {
  grid-column: 1 / -1;
  color: #78350f;
  font-size: 12px;
  line-height: 1.45;
}

.ews-route-focus-warning a {
  grid-row: 1;
  grid-column: 2;
  padding: 5px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #92400e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-loop-workers-empty {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}

.ews-desk-loop-role {
  overflow: hidden;
  max-width: 100%;
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #ccfbf1;
  color: #115e59;
  font-size: 10px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-desk-loop-state {
  overflow: hidden;
  max-width: 100%;
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  font-size: 10px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ews-desk-loop-state--run {
  background: #dcfce7;
  color: #166534;
}

.ews-desk-loop-state--idle {
  background: #eff6ff;
  color: #1d4ed8;
}

.ews-desk-loop-state--warn {
  background: #fffbeb;
  color: #92400e;
}

.ews-desk-loop-state--off {
  background: #f1f5f9;
  color: #64748b;
}

.ews-side {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.ews-selected-loop {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 12px;
  border: 1px solid rgba(20, 184, 166, 0.18);
  border-radius: 12px;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 36%),
    #ffffff;
}

.ews-selected-loop span {
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

.ews-selected-loop strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 900;
}

.ews-selected-loop p {
  margin: 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.ews-selected-loop-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
}

.ews-selected-loop-actions a {
  padding: 5px 8px;
  border-radius: 999px;
  background: #f0fdfa;
  color: #0f766e;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.ews-desk--loop {
  position: relative;
  border-color: #14b8a6;
  box-shadow: 0 0 0 2px rgba(20, 184, 166, 0.18), 0 10px 28px rgba(15, 118, 110, 0.13);
}

.ews-desk--loop::after {
  content: "LOOP";
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 2;
  padding: 3px 6px;
  border-radius: 999px;
  background: #0f766e;
  color: #ecfeff;
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.04em;
}

@media (max-width: 1040px) {
  .ews-loop-cards,
  .ews-loop-role-board,
  .ews-loop-isolation {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 560px) {
  .ews-loop-console-head {
    align-items: flex-start;
  }

  .ews-loop-cards,
  .ews-loop-role-board,
  .ews-loop-isolation {
    grid-template-columns: 1fr;
  }

  .ews-loop-diagnosis {
    grid-template-columns: 1fr;
  }
}
</style>
