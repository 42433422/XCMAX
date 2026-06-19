<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { VueFlow, useVueFlow, type Node, type Edge } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import { computeAutoLayout, computeGridLayout } from '@/composables/useAutoLayout'
import { useMarketAdminGraphAuth } from '@/composables/useMarketAdminGraphAuth'
import api from '@/api/xcmaxMarketProxy'
import type { LlmProviderStatus } from '@/domain/llm/types'
import { providerRowHasUsableKey } from '@/domain/llm/providerCredential'
import {
  YUANGON_AREAS,
  ALL_PLANNED_YUANGON_PKG_IDS,
  YUANGON_PKG_ROLE_LABELS,
  SIX_LINE_DEPARTMENTS,
  DEPARTMENT_ORDER,
  DEPARTMENT_COLORS,
  CRAFT_SUBZONE_ID,
} from '@/domain/yuangonDutyRoster'
import { publishButlerTask } from '@/utils/butlerTaskBus'
import {
  BUTLER_PROFILE,
  BUTLER_VIRTUAL_AREA_ID,
  BUTLER_VIRTUAL_AREA_LABEL,
  BUTLER_VIRTUAL_AREA_COLOR,
  BUTLER_VIRTUAL_EMPLOYEE_ID,
  butlerCapabilityView,
  describeHandler,
  extractEmployeeCapabilityView,
  type EmployeeCapabilityView,
  type EmployeeSkillView,
} from '@/domain/butlerEmployeeProfile'
import MessageBody from '@/components/chat/MessageBody.vue'
import SelfEvolutionLoopRuntimePanel from '@/components/workflow/SelfEvolutionLoopRuntimePanel.vue'
import {
  type ClientWorkshop,
  clientWorkshopNodeId,
  getClientWorkshop,
  linkedRosterEmployeeIds,
  listClientWorkshops,
  parseClientWorkshopNodeId,
  resolveClientWorkshopRoute,
} from '@/domain/clientWorkshops'

import { createEmptyEmployeeConfigV2 } from '@/domain/employeeConfigV2'

import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

const props = withDefaults(defineProps<{ open: boolean; variant?: 'modal' | 'page' | 'embedded' }>(), {
  variant: 'modal',
})
const emit = defineEmits<{ (e: 'close'): void }>()

const router = useRouter()
const route = useRoute()
const isPage = computed(() => props.variant === 'page')
const isEmbedded = computed(() => props.variant === 'embedded')
const isInlineLayout = computed(() => isPage.value || isEmbedded.value)
const flowBgPatternColor = computed(() =>
  isInlineLayout.value ? 'rgba(15, 23, 42, 0.06)' : 'rgba(255,255,255,0.04)',
)
const miniMapMaskColor = computed(() =>
  isInlineLayout.value ? 'rgba(237, 243, 250, 0.85)' : 'rgba(0,0,0,0.45)',
)
const { currentMode } = useMarketAdminGraphAuth()

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
type EmpRow   = { id: string; name?: string; source?: 'catalog' | 'v1_catalog' | 'virtual'; industry?: string }
type HealthSt = { total: number; success: number; rate: number; lastExecution?: string | null }
type HealthLv = 'healthy' | 'warn' | 'idle' | 'unknown'
type GapState = 'deployed' | 'missing' | 'untracked'
type ViewMode = 'hub' | 'department' | 'legacy-area' | 'client' | 'loop'
type GraphViewMode = Exclude<ViewMode, 'loop'>
const DEFAULT_GRAPH_VIEW_MODE: GraphViewMode = 'department'
const GRAPH_VIEW_TOKENS = new Set([
  'department',
  'dept',
  '六部门',
  'hub',
  'center',
  '中心',
  '中心图',
  'legacy-area',
  'area',
  '物理',
  '物理分区',
  'client',
  'workshop',
  '车间',
  '客户端车间',
])

function normalizeViewToken(raw: unknown): string {
  return String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase()
}

function isGraphViewToken(raw: unknown): boolean {
  return GRAPH_VIEW_TOKENS.has(normalizeViewToken(raw))
}

function parseViewModeFromQuery(raw: unknown): GraphViewMode {
  const v = normalizeViewToken(raw)
  if (v === 'department' || v === 'dept' || v === '六部门') return 'department'
  if (v === 'hub' || v === 'center' || v === '中心' || v === '中心图') return 'hub'
  if (v === 'legacy-area' || v === 'area' || v === '物理' || v === '物理分区') return 'legacy-area'
  if (v === 'client' || v === 'workshop' || v === '车间' || v === '客户端车间') return 'client'
  return DEFAULT_GRAPH_VIEW_MODE
}

function clampDutyRosterGraphViewQuery(raw: unknown): void {
  const nextQuery = { ...route.query }
  if (raw == null || String(Array.isArray(raw) ? raw[0] : raw).trim() === '') {
    if (route.query.view === DEFAULT_GRAPH_VIEW_MODE) return
    nextQuery.view = DEFAULT_GRAPH_VIEW_MODE
    void router.replace({ query: nextQuery })
    return
  }
  const viewText = normalizeViewToken(raw)
  if (!isGraphViewToken(viewText)) {
    delete nextQuery.view
    void router.replace({ query: nextQuery })
    return
  }
}

function readDutyRosterViewFromRoute() {
  viewMode.value = parseViewModeFromQuery(route.query.view)
  clampDutyRosterGraphViewQuery(route.query.view)
}

// Phase 4 types
type LlmProviderSt = { provider: string; label: string; has_platform_key: boolean; has_user_override: boolean }
type EmpLlmCfg = {
  provider: string        // e.g. "deepseek"
  model: string           // e.g. "deepseek-chat"
  handlers: string[]      // e.g. ["llm_md", "echo"]
  needsLlm: boolean       // false when handlers is echo-only
  activated: boolean      // true when provider has any key
  keySource: 'platform' | 'byok' | 'none' | 'auto'
}
type LlmActLv = 'activated' | 'no_key' | 'echo_only' | 'unknown'

type ExecRow = {
  id: number
  user_id: number
  task: string
  status: string
  duration_ms: number
  llm_tokens: number
  error: string
  created_at: string | null
}

type CapRiskDetail = {
  handler: string
  reason?: string
  command_id?: string
  requires_approval?: boolean
}

type EmpCapability = {
  employee_id: string
  name: string
  source: string
  deployed: boolean
  executable: boolean
  reasons: string[]
  handlers: string[]
  declared_dependencies: string[]
  llm: {
    provider: string
    model: string
    needs_llm: boolean
    activated: boolean
    key_source: string
  }
  risk: {
    high_risk: boolean
    requires_confirmation: boolean
    details: CapRiskDetail[]
  }
  recent_execution: {
    id: number
    status: string
    task: string
    duration_ms: number
    llm_tokens: number
    error: string
    created_at: string | null
  } | null
  recent_ops_audits: Array<{
    id: number
    handler: string
    command_id: string
    exit_code: number | null
    dry_run: boolean
    approval_required: boolean
    created_at: string | null
  }>
}

type RunNodeStatus = 'idle' | 'pending' | 'running' | 'success' | 'failed' | 'skipped'

type DutyGraphRunNode = {
  id: number
  employee_id: string
  order_index: number
  depends_on: string[]
  status: RunNodeStatus
  started_at: string | null
  completed_at: string | null
  duration_ms: number
  llm_tokens: number
  metric_id: number | null
  summary: string
  error: string
  result: Record<string, unknown>
}

type DutyGraphRun = {
  id: number
  target_employee_id: string
  task: string
  input_data: Record<string, unknown>
  include_dependencies: boolean
  max_concurrency: number
  allow_high_risk_real_run: boolean
  status: string
  total_nodes: number
  success_count: number
  failed_count: number
  skipped_count: number
  error: string
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  nodes: DutyGraphRunNode[]
}

const EXEC_METRICS_PAGE = 30

// 编制矩阵见 ../../domain/yuangonDutyRoster（与 duty_roster.py 对齐）
const ALL_PLANNED_IDS = ALL_PLANNED_YUANGON_PKG_IDS

const CRAFT_PIPELINE_ORDER = [
  'intent-analyst',
  'employee-planner',
  'artifact-generator',
  'quality-validator',
  'miniapp-builder',
  'script-binder',
  'workflow-automator',
  'pack-registrar',
  'sandbox-tester',
  'code-validator',
  'self-checker',
  'host-checker',
  'hex-quality-assessor',
]

function craftEmployeeDependsOn(employeeId: string): string | undefined {
  const idx = CRAFT_PIPELINE_ORDER.indexOf(employeeId)
  return idx > 0 ? CRAFT_PIPELINE_ORDER[idx - 1] : undefined
}

// Area colours (for node borders / group backgrounds)
const AREA_COLORS: Record<string, string> = {
  'site-and-marketing': '#0ea5e9',
  'server-and-ops':     '#f59e0b',
  'modstore-backend':   '#a78bfa',
  'modstore-frontend':  '#34d399',
  'platform-core':      '#fb923c',
  'quality-and-docs':   '#60a5fa',
  [BUTLER_VIRTUAL_AREA_ID]: BUTLER_VIRTUAL_AREA_COLOR,
}

/** 数字管家：前端虚拟员工，与 ``YUANGON_AREAS`` 同等渲染但不走后端 */
const VIRTUAL_AREAS: Record<string, { label: string; ids: string[] }> = {
  [BUTLER_VIRTUAL_AREA_ID]: { label: BUTLER_VIRTUAL_AREA_LABEL, ids: [BUTLER_VIRTUAL_EMPLOYEE_ID] },
}

/** 渲染用区域字典（编制矩阵 + 虚拟管家） */
const ALL_AREAS: Record<string, { label: string; ids: string[] }> = {
  ...YUANGON_AREAS,
  ...VIRTUAL_AREAS,
}

const VIRTUAL_EMPLOYEE_IDS = new Set<string>([BUTLER_VIRTUAL_EMPLOYEE_ID])

function isVirtualEmployee(id: string): boolean {
  return VIRTUAL_EMPLOYEE_IDS.has(id)
}

/** 编制内已安装本地 employee_pack（可拉 manifest / 执行）；不含缺岗与虚拟管家 */
function isDeployedDutyRosterRow(e: EmpRow): boolean {
  return (
    !isVirtualEmployee(e.id)
    && e.source === 'catalog'
    && !missingLocalPackIds.value.has(e.id)
  )
}

/** 值班图节点仅允许编制矩阵 + 数字管家（防止 employees 被污染或旧缓存仍带全库列表） */
function isDutyGraphMember(e: EmpRow): boolean {
  return isVirtualEmployee(e.id) || ALL_PLANNED_IDS.has(e.id)
}

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
const employees  = ref<EmpRow[]>([])
/** 编制内但未安装到本机 mods/_employees 的 pkg_id（与 missing_employees/catalog 缺岗区分） */
const missingLocalPackIds = ref<Set<string>>(new Set())
const healthMap  = ref<Record<string, HealthSt>>({})
const depsMap    = ref<Record<string, string[]>>({})
const loading    = ref(false)
const loadingP2  = ref(false)
const error      = ref('')
/** 编制数据已本地降级展示时的非阻断提示（如 market-admin 健康检查失败） */
const loadWarning = ref('')

// Phase 4 state
const llmStatusMap = ref<Record<string, LlmProviderSt>>({})   // provider → status
/** BYOK 解密依赖服务端 Fernet；与 Workbench /wallet 一致 */
const llmFernetConfigured = ref(false)
/** true：/api/llm/status 失败，勿将「映射为空」误判为全员无密钥 */
const llmStatusFailed = ref(false)
const empLlmMap    = ref<Record<string, EmpLlmCfg>>({})       // emp id → LLM config

// Phase 3 state
const viewMode       = ref<ViewMode>(parseViewModeFromQuery(route.query.view))
const showGapPanel   = ref(false)
const gapFocusHint   = ref('')
const autoRefresh    = ref(false)
const countdown      = ref(30)
const capabilityMap  = ref<Record<string, EmpCapability>>({})
const capLoading     = ref(false)
const runNodeStatusMap = ref<Record<string, RunNodeStatus>>({})
const loopRuntimeStatus = ref<Record<string, any> | null>(null)
let loopRuntimeTimer: number | null = null
const showStatsDetail = ref(false)
const showMoreActions = ref(false)
const detailCollapsed = ref<Record<string, boolean>>({})
/** 「能做什么 · 怎么做」面板的展示模型；与真实员工 manifest 抽取同一来源 */
const empCapabilityViewMap = ref<Record<string, EmployeeCapabilityView>>({})

// ─── 无密钥单点修复 ── /api/admin/duty-graph/no-key-employees + 单包改 auto ───
type NoKeyRow = {
  pkg_id: string
  name: string
  current_provider: string
  current_model: string
  key_source: string
  suggested_action: 'align_to_auto' | 'add_account_key'
  reasons: string[]
}
type NoKeyResponse = {
  items: NoKeyRow[]
  count: number
  fernet_configured: boolean
  any_provider_has_key: boolean
}
const showNoKeyPanel = ref(false)
const noKeyLoading = ref(false)
const noKeyError = ref('')
const noKeyData = ref<NoKeyResponse | null>(null)
const noKeyBusyRow = ref<Record<string, boolean>>({})

function dgLoopRecord(v: unknown): Record<string, any> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, any> : {}
}

function dgLoopArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function dgLoopString(v: unknown): string {
  return String(v ?? '').trim()
}

function dgLoopFirstText(...values: unknown[]): string {
  for (const value of values) {
    const text = dgLoopString(value)
    if (text) return text
  }
  return ''
}

function dgLoopNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

async function refreshLoopRuntimeStatus() {
  try {
    loopRuntimeStatus.value = await api.selfMaintenanceRuntimeStatus(80) as Record<string, any>
  } catch {
    loopRuntimeStatus.value = null
  }
}

function collectDutyLoopEmployeeIds(value: unknown, out: Set<string>) {
  if (value == null) return
  if (typeof value === 'string') {
    const matches = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
    for (const id of matches) {
      if (ALL_PLANNED_IDS.has(id)) out.add(id)
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectDutyLoopEmployeeIds(item, out)
    return
  }
  if (typeof value !== 'object') return
  const row = value as Record<string, unknown>
  const direct = dgLoopString(row.employee_id || row.employeeId || row.emp_id || row.empId || row.actor || row.assignee)
  if (direct && ALL_PLANNED_IDS.has(direct)) out.add(direct)
  for (const child of Object.values(row)) collectDutyLoopEmployeeIds(child, out)
}

const loopParticipantIdSet = computed(() => {
  const ids = new Set<string>()
  const payload = loopRuntimeStatus.value || {}
  for (const item of dgLoopArray(dgLoopRecord(payload).participants)) {
    const id = dgLoopString(dgLoopRecord(item).employee_id || dgLoopRecord(item).id)
    if (id && ALL_PLANNED_IDS.has(id)) ids.add(id)
  }
  collectDutyLoopEmployeeIds(dgLoopRecord(payload).evidence, ids)
  collectDutyLoopEmployeeIds(dgLoopRecord(payload).memory, ids)
  return ids
})

const loopParticipantById = computed(() => {
  const out: Record<string, Record<string, any>> = {}
  const payload = loopRuntimeStatus.value || {}
  for (const item of dgLoopArray(dgLoopRecord(payload).participants)) {
    const row = dgLoopRecord(item)
    const id = dgLoopString(row.employee_id || row.id)
    if (id) out[id] = row
  }
  return out
})

const loopParticipantIds = computed(() => Array.from(loopParticipantIdSet.value))
const loopUiBridgeRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.ui_bridge))
const loopGovernanceAuditRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.governance_audit))
const loopCurrentGovernanceGateRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.governance_gate))
const loopGovernanceAuditSummary = computed(() => dgLoopRecord(loopGovernanceAuditRecord.value.summary))
const loopGovernanceAuditLast = computed(() => dgLoopRecord(loopGovernanceAuditRecord.value.last))
const loopGovernanceAuditLastTargets = computed(() =>
  dgLoopArray(loopGovernanceAuditLast.value.target_employee_ids)
    .map((id) => dgLoopString(id))
    .filter(Boolean),
)
const loopGovernanceAuditLastSummary = computed(() => {
  const summary = dgLoopRecord(loopGovernanceAuditLast.value.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  return ''
})
const loopRuntimeSchemaVersion = computed(() => dgLoopFirstText(dgLoopRecord(loopRuntimeStatus.value).schema_version))
const loopRuntimeContractRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.contract))
const loopRuntimeContractValidationRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.contract_validation))
const loopRuntimeSurfaceReadinessCards = computed(() => {
  const readiness = dgLoopRecord(loopRuntimeContractValidationRecord.value.surface_readiness)
  const surfaces = [
    { key: 'employee_space', label: '员工空间', role: '执行入口' },
    { key: 'duty_roster_graph', label: '编制图谱', role: '治理覆盖' },
    { key: 'self_evolution_loop_runtime', label: 'Runtime', role: '链路审计' },
  ]
  return surfaces.map((surface) => {
    const item = dgLoopRecord(readiness[surface.key])
    const missing = dgLoopArray(item.missing).map((value) => dgLoopString(value)).filter(Boolean)
    const known = Object.keys(item).length > 0
    const ok = item.ok === true
    const severity = dgLoopFirstText(item.severity, ok ? 'ok' : known && missing.length ? 'bad' : 'warn')
    const blocked = known && ok === false
    return {
      key: surface.key,
      label: surface.label,
      role: surface.role,
      ok,
      known,
      blocked,
      stateLabel: ok ? 'ready' : blocked ? 'blocked' : 'unknown',
      ctaLabel: ok ? '查看链路' : blocked ? '处理断点' : '等待状态',
      tone: severity === 'bad' || blocked ? 'bad' : severity === 'warn' || !known ? 'warn' : 'ok',
      action: dgLoopFirstText(item.action, ok ? 'watch' : known ? 'inspect_runtime_contract' : 'waiting_runtime_contract'),
      detail: dgLoopFirstText(item.detail, missing.length ? `missing ${missing.slice(0, 3).join(' / ')}` : known ? 'contract ready' : '等待后端暴露该 surface readiness'),
      sourceLabel: known ? 'source · contract_validation.surface_readiness' : 'waiting · runtime surface readiness missing',
      missing,
      target: dgLoopFirstText(item.target_surface, surface.key),
      view: dgLoopFirstText(item.target_view, 'runtime'),
    }
  })
})
const loopRuntimeContractRequiredFields = computed(() =>
  dgLoopArray(loopRuntimeContractRecord.value.required_top_level).map((item) => dgLoopString(item)).filter(Boolean),
)
const loopRuntimeContractMissingFields = computed(() => {
  const backendMissing = dgLoopArray(loopRuntimeContractValidationRecord.value.missing_fields)
    .map((item) => dgLoopString(item))
    .filter(Boolean)
  if (backendMissing.length || loopRuntimeContractValidationRecord.value.ok === false) return backendMissing
  const payload = dgLoopRecord(loopRuntimeStatus.value)
  return loopRuntimeContractRequiredFields.value.filter((field) => !(field in payload))
})
const loopRuntimeContractMissingNested = computed(() =>
  dgLoopArray(loopRuntimeContractValidationRecord.value.missing_nested)
    .map((item) => dgLoopString(item))
    .filter(Boolean),
)
const loopRuntimeSurfaceReadiness = computed(() =>
  dgLoopRecord(dgLoopRecord(loopRuntimeContractValidationRecord.value.surface_readiness).duty_roster_graph),
)
const loopRuntimeSurfaceReadinessOk = computed(() => loopRuntimeSurfaceReadiness.value.ok === true)
const loopRuntimeSurfaceMissing = computed(() =>
  dgLoopArray(loopRuntimeSurfaceReadiness.value.missing)
    .map((item) => dgLoopString(item))
    .filter(Boolean),
)
const loopRuntimeSurfaceIncidents = computed(() =>
  dgLoopArray(loopRuntimeContractValidationRecord.value.surface_incidents)
    .map((item) => dgLoopRecord(item))
    .filter((item) => dgLoopString(item.surface) === 'duty_roster_graph'),
)
const loopRuntimeSurfaceIncident = computed(() => loopRuntimeSurfaceIncidents.value[0] || {})
const loopRuntimeSurfaceIncidentSummary = computed(() =>
  dgLoopRecord(loopRuntimeContractValidationRecord.value.surface_incident_summary),
)
const loopRuntimeContractStatus = computed(() => {
  const topLevel = dgLoopRecord(loopRuntimeStatus.value?.contract_status)
  return Object.keys(topLevel).length
    ? topLevel
    : dgLoopRecord(loopRuntimeContractValidationRecord.value.contract_status)
})
const loopRuntimeContractPrimaryRoute = computed(() =>
  dgLoopRecord(loopRuntimeContractStatus.value.primary_route),
)
const loopRuntimePrimaryRouteLocation = computed(() => {
  const surface = dgLoopString(loopRuntimeContractPrimaryRoute.value.surface)
  const view = parseViewModeFromQuery(loopRuntimeContractPrimaryRoute.value.view)
  const employeeId = dgLoopFirstText(
    loopRuntimeContractPrimaryRoute.value.employee_id,
    dgLoopArray(loopRuntimeContractPrimaryRoute.value.target_employee_ids)[0],
    loopBridgePrimaryEmployeeId.value,
  )
  if (surface === 'employee_space') return employeeSpaceLocation(employeeId || selectedEmp.value?.id)
  if (router.hasRoute('duty-roster-graph')) {
    return {
      name: 'duty-roster-graph',
      query: employeeId ? { view, employee: employeeId } : { view },
    }
  }
  return { name: 'workflow-visualization', query: { view } }
})
const loopRuntimePrimaryRouteLabel = computed(() => {
  const label = dgLoopString(loopRuntimeContractPrimaryRoute.value.label)
  if (label) return label
  const surface = dgLoopString(loopRuntimeContractPrimaryRoute.value.surface)
  if (surface === 'employee_space') return '打开员工空间'
  if (surface === 'duty_roster_graph') return '打开治理面'
  return '打开完整 Loop'
})
const loopRuntimeContractOk = computed(() =>
  loopRuntimeSchemaVersion.value === 'self_maintenance_runtime.v1'
  && loopRuntimeContractRequiredFields.value.length > 0
  && loopRuntimeContractMissingFields.value.length === 0
  && loopRuntimeSurfaceReadinessOk.value
)
const loopDutyRosterBridgeRecord = computed(() => dgLoopRecord(loopUiBridgeRecord.value.duty_roster_graph))
const loopGovernanceActionRecord = computed(() => dgLoopRecord(loopUiBridgeRecord.value.governance_action))
const loopGovernanceAllowedSurfaces = computed(() =>
  dgLoopArray(loopGovernanceActionRecord.value.allowed_surfaces)
    .map((item) => dgLoopString(item))
    .filter(Boolean),
)
const loopGovernanceActionAllowedInDutyGraph = computed(() =>
  loopGovernanceAllowedSurfaces.value.includes('duty_roster_graph'),
)
const loopBridgePrimaryEmployeeId = computed(() =>
  dgLoopFirstText(
    loopUiBridgeRecord.value.primary_employee_id,
    dgLoopArray(loopUiBridgeRecord.value.target_employee_ids)[0],
  ),
)
const loopBridgeIsolationIds = computed(() =>
  dgLoopArray(loopUiBridgeRecord.value.blocked_employee_ids)
    .map((id) => dgLoopString(id))
    .filter(Boolean),
)
const loopRosterAlignment = computed(() => dgLoopRecord(loopRuntimeStatus.value?.roster_alignment))
const loopRosterGateRecord = computed(() => dgLoopRecord(loopRosterAlignment.value.gate))
const loopRosterRemediationRecord = computed(() => dgLoopRecord(loopRosterAlignment.value.remediation))
const loopRawParticipantIds = computed(() => {
  const ids = new Set<string>()
  const payload = loopRuntimeStatus.value || {}
  for (const item of dgLoopArray(dgLoopRecord(payload).participants)) {
    const id = dgLoopString(dgLoopRecord(item).employee_id || dgLoopRecord(item).id)
    if (id) ids.add(id)
  }
  for (const timeline of dgLoopArray(dgLoopRecord(payload).run_timelines)) {
    for (const item of dgLoopArray(dgLoopRecord(timeline).items)) {
      const id = dgLoopString(dgLoopRecord(item).employee_id)
      if (id) ids.add(id)
    }
  }
  return Array.from(ids)
})
const loopOutOfRosterParticipantIds = computed(() => {
  const backendIds = dgLoopArray(loopRosterAlignment.value.out_of_roster_ids).map((id) => dgLoopString(id)).filter(Boolean)
  if (backendIds.length || loopRosterAlignment.value.out_of_roster_count != null) return backendIds
  return loopRawParticipantIds.value.filter((id) => !ALL_PLANNED_IDS.has(id))
})
const loopOutOfRosterCount = computed(() =>
  dgLoopNumber(loopRosterAlignment.value.out_of_roster_count) ?? loopOutOfRosterParticipantIds.value.length,
)
const loopNotDeployedCount = computed(() =>
  dgLoopNumber(loopRosterAlignment.value.not_deployed_count) ?? 0,
)
const loopGateRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.current_gate))
const loopEvidenceRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.evidence))
const loopMergeDecisionRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.merge_decision))
const loopMetricsRecord = computed(() => dgLoopRecord(loopRuntimeStatus.value?.evolution_metrics_summary))
const loopOpenRunCount = computed(() => dgLoopArray(loopEvidenceRecord.value.open_run_ids).length)
const loopRemediationBusy = ref(false)
const loopRemediationError = ref('')
const loopRemediationResult = ref<Record<string, any> | null>(null)
const loopGovernanceReviewBusy = ref(false)
const loopGovernanceReviewError = ref('')
const loopGovernanceReviewResult = ref<Record<string, any> | null>(null)
const loopCanReviewGovernanceAudit = computed(() =>
  !loopGovernanceReviewBusy.value
  && loopGovernanceActionRecord.value.requires_admin === true
  && loopGovernanceActionAllowedInDutyGraph.value
  && (
    loopGovernanceAuditSummary.value.health === 'bad'
    || loopUiBridgeRecord.value.state === 'governance_degraded'
  ),
)
const loopRemediationResultSummary = computed(() => {
  const result = loopRemediationResult.value
  if (!result) return ''
  const summary = dgLoopRecord(result.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  const stdout = dgLoopString(result.stdout_tail)
  const stderr = dgLoopString(result.stderr_tail)
  const doneMatch = stdout.match(/done:\s*onboarded=(\d+),\s*skipped=(\d+),\s*failed=(\d+)/i)
  if (doneMatch) {
    return `onboarded ${doneMatch[1]} · skipped ${doneMatch[2]} · failed ${doneMatch[3]}`
  }
  const stdoutTail = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-2)
    .join(' · ')
  if (stdoutTail) return stdoutTail.slice(0, 220)
  const stderrTail = stderr
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(-1)
    .join(' · ')
  return stderrTail.slice(0, 220)
})
const loopRemediationTargetIds = computed(() =>
  dgLoopArray(loopRosterRemediationRecord.value.target_employee_ids)
    .map((id) => dgLoopString(id))
    .filter(Boolean),
)
const loopCanRunDutyRegistration = computed(() => {
  const action = dgLoopString(loopRosterRemediationRecord.value.action)
  const governanceAction = dgLoopString(loopGovernanceActionRecord.value.id)
  return (
    !loopRemediationBusy.value
    && loopRemediationTargetIds.value.length > 0
    && (
      (
        governanceAction === 'register_duty_employees'
        && loopGovernanceActionRecord.value.executable !== false
        && loopGovernanceActionAllowedInDutyGraph.value
      )
      || loopRosterGateRecord.value.action === 'hold'
      || action === 'register_duty_employees'
      || action.includes('register')
    )
  )
})

const loopGovernanceControlCards = computed(() => {
  const actionId = dgLoopString(loopGovernanceActionRecord.value.id)
  const actionLabel = dgLoopFirstText(loopGovernanceActionRecord.value.label, actionId, '观察 Loop')
  const auditHealth = dgLoopFirstText(loopGovernanceAuditSummary.value.health, 'ok')
  const gateBlocking = loopRosterGateRecord.value.blocking === true || loopCurrentGovernanceGateRecord.value.blocking === true
  return [
    {
      key: 'boundary',
      label: '治理边界',
      value: dgLoopFirstText(loopDutyRosterBridgeRecord.value.role, '编制图谱'),
      sub: dgLoopFirstText(loopDutyRosterBridgeRecord.value.detail, '高风险动作只在编制图谱执行'),
      tone: 'run',
    },
    {
      key: 'roster-gate',
      label: '上岗准入',
      value: gateBlocking ? '阻断' : '放行',
      sub: dgLoopFirstText(loopRosterGateRecord.value.reason, loopCurrentGovernanceGateRecord.value.reason, 'roster policy clear'),
      tone: gateBlocking ? 'bad' : 'ok',
    },
    {
      key: 'action',
      label: '授权动作',
      value: actionLabel,
      sub: `${loopGovernanceActionRecord.value.requires_admin === true ? 'admin-only' : 'operator'} · ${loopGovernanceActionAllowedInDutyGraph.value ? 'allowed here' : 'not on this surface'} · ${loopGovernanceActionRecord.value.executable === false ? 'view-only' : 'executable'}`,
      tone: loopGovernanceActionAllowedInDutyGraph.value ? 'run' : 'warn',
    },
    {
      key: 'audit',
      label: '治理审计',
      value: auditHealth,
      sub: `${loopGovernanceAuditSummary.value.success_count ?? 0} ok · ${loopGovernanceAuditSummary.value.failure_count ?? 0} failed · consecutive ${loopGovernanceAuditSummary.value.consecutive_failures ?? 0}`,
      tone: auditHealth === 'bad' ? 'bad' : auditHealth === 'warn' ? 'warn' : 'ok',
    },
  ]
})

const loopGovernanceActionPathCards = computed(() => {
  const targetIds = loopRemediationTargetIds.value.length
    ? loopRemediationTargetIds.value
    : loopBridgeIsolationIds.value
  const handoffPath = dgLoopFirstText(loopUiBridgeRecord.value.handoff_path, loopDutyRosterBridgeRecord.value.path, 'employee_space -> duty_roster_graph')
  return [
    {
      key: 'handoff',
      label: '页面职责',
      value: '员工看现场 / 编制管准入',
      sub: handoffPath,
      tone: 'run',
    },
    {
      key: 'targets',
      label: '目标员工',
      value: `${targetIds.length}`,
      sub: targetIds.length ? targetIds.slice(0, 5).join(' / ') : dgLoopFirstText(loopBridgePrimaryEmployeeId, '当前无目标员工'),
      tone: targetIds.length ? 'warn' : 'ok',
    },
    {
      key: 'surface',
      label: '允许面',
      value: loopGovernanceActionAllowedInDutyGraph.value ? '本页可执行' : '本页只观察',
      sub: loopGovernanceAllowedSurfaces.value.join(' / ') || '未声明 allowed_surfaces',
      tone: loopGovernanceActionAllowedInDutyGraph.value ? 'run' : 'warn',
    },
    {
      key: 'next',
      label: '下一步',
      value: dgLoopFirstText(loopUiBridgeRecord.value.primary_action, loopGovernanceActionRecord.value.id, 'watch_loop'),
      sub: dgLoopArray(loopUiBridgeRecord.value.next_actions).map((item) => dgLoopString(item)).filter(Boolean).slice(0, 3).join(' / ') || '等待 runtime 刷新',
      tone: loopCurrentGovernanceGateRecord.value.blocking === true ? 'bad' : 'ok',
    },
  ]
})

const loopGovernanceIsolationMatrix = computed(() => {
  const planned = dgLoopNumber(loopRosterAlignment.value.planned_count) ?? ALL_PLANNED_IDS.size
  const inRoster = dgLoopNumber(loopRosterAlignment.value.in_roster_count) ?? loopParticipantIds.value.length
  const inDeployed = dgLoopNumber(loopRosterAlignment.value.in_deployed_count) ?? inRoster
  const notDeployed = loopNotDeployedCount.value
  const outOfRoster = loopOutOfRosterCount.value
  const idleRoster = Math.max(0, planned - inRoster)
  return [
    {
      key: 'on-duty',
      label: '上岗员工',
      value: `${inDeployed}`,
      sub: '允许参与自维护 loop 的编制员工',
      tone: inDeployed > 0 ? 'run' : 'warn',
    },
    {
      key: 'idle-roster',
      label: '未参与编制',
      value: `${idleRoster}`,
      sub: idleRoster ? '编制内但本轮未进入 loop' : '本轮编制覆盖完整',
      tone: idleRoster ? 'warn' : 'ok',
    },
    {
      key: 'not-deployed',
      label: '待补登记',
      value: `${notDeployed}`,
      sub: loopRemediationTargetIds.value.length
        ? loopRemediationTargetIds.value.slice(0, 5).join(' / ')
        : '没有待补登记员工',
      tone: notDeployed ? 'bad' : 'ok',
    },
    {
      key: 'isolated',
      label: '商店/非编制隔离',
      value: `${outOfRoster}`,
      sub: loopOutOfRosterParticipantIds.value.length
        ? loopOutOfRosterParticipantIds.value.slice(0, 5).join(' / ')
        : '未发现越界员工',
      tone: outOfRoster ? 'bad' : 'ok',
    },
  ]
})

const loopGovernanceChecklist = computed(() => {
  const rosterBlocked = loopRosterGateRecord.value.blocking === true || loopRosterGateRecord.value.action === 'hold'
  const governanceBlocked = loopCurrentGovernanceGateRecord.value.blocking === true
  const primaryEmployeeId = loopBridgePrimaryEmployeeId.value
  return [
    {
      key: 'runtime',
      label: 'Runtime',
      title: loopRuntimeStatus.value
        ? loopRuntimeContractOk.value ? '已接入 self-maintenance runtime' : 'runtime contract 不匹配'
        : 'runtime 未连接',
      detail: loopRuntimeStatus.value
        ? loopRuntimeContractOk.value
          ? `${loopParticipantIds.value.length} employees · ${loopOpenRunCount.value} open runs`
          : `schema=${loopRuntimeSchemaVersion.value || 'unknown'}，需要 self_maintenance_runtime.v1`
        : '需要后端 /ops/self-maintenance/status 返回状态',
      tone: loopRuntimeStatus.value && loopRuntimeContractOk.value ? 'ok' : 'bad',
      action: 'loop',
      actionLabel: '看完整 Loop',
    },
    {
      key: 'roster',
      label: '上岗准入',
      title: rosterBlocked ? '准入阻断，需要处理员工身份' : '准入放行',
      detail: loopRemediationTargetIds.value.length
        ? `目标：${loopRemediationTargetIds.value.slice(0, 5).join(' / ')}`
        : dgLoopFirstText(loopRosterGateRecord.value.reason, '没有待补登记目标'),
      tone: rosterBlocked ? 'bad' : 'ok',
      action: loopCanRunDutyRegistration.value ? 'register' : primaryEmployeeId ? 'focus' : 'loop',
      actionLabel: loopCanRunDutyRegistration.value ? '补登记' : primaryEmployeeId ? '定位员工' : '看 Loop',
    },
    {
      key: 'isolation',
      label: '隔离检查',
      title: loopBridgeIsolationIds.value.length || loopOutOfRosterCount.value ? '发现非编制/商店员工' : '隔离边界清晰',
      detail: loopBridgeIsolationIds.value.length
        ? loopBridgeIsolationIds.value.slice(0, 6).join(' / ')
        : loopOutOfRosterParticipantIds.value.length
          ? loopOutOfRosterParticipantIds.value.slice(0, 6).join(' / ')
          : '未发现越界参与者',
      tone: loopBridgeIsolationIds.value.length || loopOutOfRosterCount.value ? 'bad' : 'ok',
      action: primaryEmployeeId ? 'focus' : 'loop',
      actionLabel: primaryEmployeeId ? '定位目标' : '看 Loop',
    },
    {
      key: 'audit',
      label: '治理审计',
      title: governanceBlocked ? '审计阻断，需要人工复核' : '审计健康',
      detail: `${loopGovernanceAuditSummary.value.success_count ?? 0} ok · ${loopGovernanceAuditSummary.value.failure_count ?? 0} failed · consecutive ${loopGovernanceAuditSummary.value.consecutive_failures ?? 0}`,
      tone: governanceBlocked ? 'bad' : 'ok',
      action: loopCanReviewGovernanceAudit.value ? 'review' : 'loop',
      actionLabel: loopCanReviewGovernanceAudit.value ? '复核审计' : '看门禁',
    },
  ]
})

const loopGovernanceTodoQueue = computed(() => {
  const rows: Array<{
    key: string
    label: string
    title: string
    detail: string
    tone: string
    action: string
    actionLabel: string
    incidentId?: string
    route?: string
  }> = []
  if (!loopRuntimeStatus.value || !loopRuntimeContractOk.value) {
    rows.push({
      key: 'runtime',
      label: 'runtime',
      title: loopRuntimeStatus.value ? 'runtime contract 不匹配' : '连接 self-maintenance runtime',
      detail: loopRuntimeStatus.value
        ? loopRuntimeContractMissingFields.value.length
          ? `schema=${loopRuntimeSchemaVersion.value || 'unknown'}，缺字段=${loopRuntimeContractMissingFields.value.slice(0, 5).join(' / ')}`
          : loopRuntimeSurfaceMissing.value.length
          ? `${dgLoopFirstText(loopRuntimeSurfaceIncident.value.action, loopRuntimeSurfaceReadiness.value.action, 'repair')} · ${loopRuntimeSurfaceMissing.value.slice(0, 5).join(' / ')}`
          : `schema=${loopRuntimeSchemaVersion.value || 'unknown'}，前端只信 self_maintenance_runtime.v1`
        : '没有状态就无法判断员工、门禁和治理动作',
      tone: 'bad',
      action: 'loop',
      actionLabel: '看 Loop',
    })
  }
  if (loopRuntimeSurfaceIncidents.value.length) {
    const incidentAction = dgLoopString(loopRuntimeSurfaceIncident.value.action)
    const incidentExecutable = loopRuntimeSurfaceIncident.value.executable === true
    rows.push({
      key: 'surface-contract',
      label: dgLoopFirstText(loopRuntimeSurfaceIncident.value.surface, 'surface'),
      title: dgLoopFirstText(loopRuntimeSurfaceIncident.value.title, '当前治理面 contract 事故'),
      detail: dgLoopFirstText(
        loopRuntimeSurfaceIncident.value.detail,
        loopRuntimeSurfaceMissing.value.length
          ? `缺依赖=${loopRuntimeSurfaceMissing.value.slice(0, 6).join(' / ')}`
          : '后端 surface_incidents 要求处理',
      ),
      tone: dgLoopFirstText(loopRuntimeSurfaceIncident.value.severity, 'bad'),
      incidentId: dgLoopFirstText(loopRuntimeSurfaceIncident.value.id, 'contract:duty_roster_graph'),
      route: `${dgLoopFirstText(loopRuntimeSurfaceIncident.value.action, 'inspect_runtime_contract')} -> ${dgLoopFirstText(loopRuntimeSurfaceIncident.value.target_surface, 'self_evolution_loop_runtime')}`,
      action: incidentAction === 'inspect_governance_audit' && incidentExecutable && loopCanReviewGovernanceAudit.value
        ? 'review'
        : loopBridgePrimaryEmployeeId.value ? 'focus' : 'loop',
      actionLabel: incidentAction === 'inspect_governance_audit' && incidentExecutable && loopCanReviewGovernanceAudit.value
        ? '复核审计'
        : loopBridgePrimaryEmployeeId.value ? '定位目标' : '看 Loop',
    })
  }
  if (loopCanRunDutyRegistration.value || loopNotDeployedCount.value) {
    rows.push({
      key: 'register-duty',
      label: '上岗准入',
      title: `补登记 ${loopRemediationTargetIds.value.length || loopNotDeployedCount.value} 个员工`,
      detail: loopRemediationTargetIds.value.slice(0, 6).join(' / ') || '编制内但未登记上岗',
      tone: 'bad',
      action: loopCanRunDutyRegistration.value ? 'register' : 'loop',
      actionLabel: loopCanRunDutyRegistration.value ? '补登记' : '看准入',
    })
  }
  if (loopBridgeIsolationIds.value.length || loopOutOfRosterCount.value) {
    rows.push({
      key: 'isolate',
      label: '隔离',
      title: '确认商店/非编制员工没有进入上岗 loop',
      detail: (loopBridgeIsolationIds.value.length ? loopBridgeIsolationIds.value : loopOutOfRosterParticipantIds.value).slice(0, 6).join(' / '),
      tone: 'bad',
      action: loopBridgePrimaryEmployeeId.value ? 'focus' : 'loop',
      actionLabel: loopBridgePrimaryEmployeeId.value ? '定位目标' : '看隔离',
    })
  }
  if (loopCanReviewGovernanceAudit.value || loopCurrentGovernanceGateRecord.value.blocking === true) {
    rows.push({
      key: 'audit',
      label: '审计',
      title: '人工复核治理审计',
      detail: dgLoopFirstText(loopCurrentGovernanceGateRecord.value.reason, 'governance audit needs review'),
      tone: 'bad',
      action: loopCanReviewGovernanceAudit.value ? 'review' : 'loop',
      actionLabel: loopCanReviewGovernanceAudit.value ? '复核审计' : '看审计',
    })
  }
  if (!rows.length) {
    rows.push({
      key: 'clear',
      label: '清单',
      title: '当前没有治理阻断',
      detail: '这是 runtime 计算后的空队列，不是隐藏待办',
      tone: 'ok',
      action: 'loop',
      actionLabel: '看完整 Loop',
    })
  }
  return rows
})

const loopGovernanceFreshnessCards = computed(() => {
  const payload = dgLoopRecord(loopRuntimeStatus.value)
  const generatedAt = dgLoopFirstText(payload.generated_at, payload.created_at, payload.snapshot_at)
  const updatedAt = dgLoopFirstText(payload.updated_at, payload.refreshed_at, payload.last_seen_at, payload.last_run_at)
  const auditAt = dgLoopFirstText(loopGovernanceAuditLast.value.created_at, loopGovernanceAuditLast.value.at, loopGovernanceAuditLast.value.ts)
  return [
    {
      key: 'snapshot',
      label: 'Snapshot time',
      value: generatedAt || 'timestamp missing',
      sub: generatedAt ? '后端 runtime 快照时间' : '未返回快照时间，不按实时处理',
      tone: generatedAt ? 'ok' : 'warn',
    },
    {
      key: 'refresh',
      label: 'Runtime update',
      value: updatedAt || 'unknown',
      sub: updatedAt ? '后端声明的最近更新时间' : '未拿到 updated/refreshed/last_seen 字段',
      tone: updatedAt ? 'ok' : 'warn',
    },
    {
      key: 'audit',
      label: 'Latest audit event',
      value: auditAt || 'no audit time',
      sub: auditAt ? '最近治理审计事件时间' : '治理审计没有时间戳或还没有事件',
      tone: auditAt ? 'run' : 'warn',
    },
  ]
})
const loopMissingEvidenceCount = computed(() =>
  dgLoopNumber(
    loopEvidenceRecord.value.missing_count
      ?? loopEvidenceRecord.value.missingEvidenceCount
      ?? loopEvidenceRecord.value.gap_count
      ?? loopGateRecord.value.missing_count,
  ),
)
const loopStatusLabel = computed(() => {
  if (!loopRuntimeStatus.value) return '待连接'
  if (!loopRuntimeContractOk.value) return 'Contract 异常'
  if (loopOpenRunCount.value > 0) return '运行中'
  if (loopGateRecord.value.should_run === true) return '达到阈值'
  const reason = dgLoopString(loopGateRecord.value.reason)
  return reason === 'cooldown' ? '冷却中' : '待命'
})
const loopParticipantPreview = computed(() =>
  loopParticipantIds.value.slice(0, 10).map((id) => ({
    id,
    label: dgLoopFirstText(
      loopParticipantById.value[id]?.role_label,
      loopParticipantById.value[id]?.role,
      YUANGON_PKG_ROLE_LABELS[id],
      id,
    ),
  })),
)
const loopDepartmentCoverage = computed(() => {
  const backendCoverage = dgLoopArray(loopRosterAlignment.value.department_coverage)
    .map((item) => dgLoopRecord(item))
    .filter((item) => dgLoopString(item.key) && dgLoopNumber(item.count) !== null)
    .map((item) => ({
      key: dgLoopString(item.key),
      label: dgLoopFirstText(item.label, item.key),
      count: dgLoopNumber(item.count) ?? 0,
      total: dgLoopNumber(item.total) ?? 0,
      ids: dgLoopArray(item.ids).map((id) => dgLoopString(id)).filter(Boolean).slice(0, 5),
    }))
  if (backendCoverage.length || loopRosterAlignment.value.department_coverage != null) return backendCoverage
  const participantIds = loopParticipantIdSet.value
  const used = new Set<string>()
  const rows: Array<{ key: string; label: string; count: number; total: number; ids: string[] }> = []
  const deptMap = SIX_LINE_DEPARTMENTS as Record<string, any>
  for (const deptId of DEPARTMENT_ORDER) {
    const dept = dgLoopRecord(deptMap[deptId])
    const directIds = dgLoopArray(dept.ids ?? dept.employee_ids ?? dept.employeeIds ?? dept.members ?? dept.employees)
    const subzoneIds = Object.values(dgLoopRecord(dept.subzones))
      .flatMap((subzone) => dgLoopArray(dgLoopRecord(subzone).ids))
    const ids = [...directIds, ...subzoneIds]
      .map((x) => dgLoopString(x))
      .filter((id) => !!id && ALL_PLANNED_IDS.has(id))
    if (!ids.length) continue
    for (const id of ids) used.add(id)
    const hits = ids.filter((id) => participantIds.has(id))
    if (!hits.length) continue
    rows.push({
      key: deptId,
      label: dgLoopFirstText(dept.label, dept.name, deptId),
      count: hits.length,
      total: ids.length,
      ids: hits.slice(0, 5),
    })
  }
  const ungrouped = loopParticipantIds.value.filter((id) => !used.has(id))
  if (ungrouped.length) {
    rows.push({
      key: 'ungrouped',
      label: '未归组',
      count: ungrouped.length,
      total: ungrouped.length,
      ids: ungrouped.slice(0, 5),
    })
  }
  return rows
})
const loopCommandCards = computed(() => {
  const missing = loopMissingEvidenceCount.value
  const mergeAction = dgLoopFirstText(loopMergeDecisionRecord.value.action, loopMergeDecisionRecord.value.verdict, '等待决策')
  const riskText = dgLoopFirstText(
    loopMergeDecisionRecord.value.safety_score_v3,
    loopMergeDecisionRecord.value.safety_score_v2,
    loopMergeDecisionRecord.value.risk_score_v1,
    '未评分',
  )
  return [
    {
      key: 'workers',
      label: '调度员工',
      value: `${loopParticipantIds.value.length}`,
      sub: '编制图谱已高亮参与者',
      tone: loopParticipantIds.value.length > 0 ? 'run' : 'warn',
    },
    {
      key: 'evidence',
      label: '缺证门禁',
      value: missing == null ? (loopGateRecord.value.should_run === true ? '触发' : '待命') : `${missing}`,
      sub: dgLoopFirstText(loopGateRecord.value.reason, loopGateRecord.value.trigger_reason, 'threshold gate'),
      tone: loopGateRecord.value.should_run === true ? 'run' : 'ok',
    },
    {
      key: 'merge',
      label: '合并规则',
      value: mergeAction,
      sub: `risk/safety ${riskText}`,
      tone: String(mergeAction).toLowerCase().includes('block') ? 'bad' : 'ok',
    },
    {
      key: 'metrics',
      label: '进化指标',
      value: loopMetricsRecord.value.pause === true ? '暂停' : '放行',
      sub: dgLoopFirstText(loopMetricsRecord.value.reason, `history ${loopMetricsRecord.value.history_count ?? 0}`),
      tone: loopMetricsRecord.value.pause === true ? 'bad' : 'ok',
    },
  ]
})
const loopRosterSeparationCards = computed(() => {
  const onDutyCount = employees.value.filter(isDeployedDutyRosterRow).length
  const catalogOnlyCount = employees.value.filter((row) => row.source === 'v1_catalog').length
  const plannedCount = dgLoopNumber(loopRosterAlignment.value.planned_count) ?? ALL_PLANNED_IDS.size
  const alignedInRosterCount = dgLoopNumber(loopRosterAlignment.value.in_roster_count) ?? loopParticipantIds.value.length
  const alignedInDeployedCount = dgLoopNumber(loopRosterAlignment.value.in_deployed_count) ?? alignedInRosterCount
  return [
    {
      key: 'planned',
      label: '编制岗位',
      value: `${plannedCount}`,
      sub: '组织图谱 SSOT',
      tone: 'ok',
    },
    {
      key: 'onduty',
      label: '已上岗',
      value: `${onDutyCount}`,
      sub: `缺岗 ${Math.max(0, ALL_PLANNED_IDS.size - onDutyCount)}`,
      tone: onDutyCount >= ALL_PLANNED_IDS.size ? 'ok' : 'warn',
    },
    {
      key: 'catalog',
      label: '目录/商店隔离',
      value: `${catalogOnlyCount}`,
      sub: '目录员工不等于上岗员工',
      tone: catalogOnlyCount > 0 ? 'warn' : 'ok',
    },
    {
      key: 'blocked',
      label: 'Loop 非编制',
      value: `${loopOutOfRosterCount.value}`,
      sub: loopOutOfRosterCount.value
        ? loopOutOfRosterParticipantIds.value.slice(0, 3).join(' / ')
          || dgLoopFirstText(loopRosterGateRecord.value.reason, '非编制参与者已由后端隔离')
        : dgLoopFirstText(loopRosterGateRecord.value.action, '未混入'),
      tone: loopOutOfRosterCount.value ? 'bad' : 'ok',
    },
    {
      key: 'aligned',
      label: 'Loop 上岗命中',
      value: `${alignedInDeployedCount}`,
      sub: `编制命中 ${alignedInRosterCount}`,
      tone: alignedInDeployedCount > 0 ? 'run' : 'warn',
    },
    {
      key: 'not-deployed',
      label: 'Loop 未上岗',
      value: `${loopNotDeployedCount.value}`,
      sub: dgLoopFirstText(loopRosterAlignment.value.source, 'frontend fallback'),
      tone: loopNotDeployedCount.value > 0 ? 'bad' : 'ok',
    },
  ]
})
const loopAdminDiagnosis = computed(() => {
  if (!loopRuntimeStatus.value) {
    return {
      tone: 'warn',
      title: '自进化 runtime 未连接',
      detail: '管理端未拿到 self-maintenance 状态，当前图谱只能展示静态编制和员工健康态。',
      actions: ['检查 MODstore 后端', '检查 ops/self-maintenance/status'],
    }
  }
  const bridgeTitle = dgLoopFirstText(loopDutyRosterBridgeRecord.value.title, loopUiBridgeRecord.value.title)
  if (bridgeTitle) {
    const actions = dgLoopArray(loopUiBridgeRecord.value.next_actions)
      .map((action) => dgLoopString(action))
      .filter(Boolean)
    return {
      tone: dgLoopFirstText(loopUiBridgeRecord.value.tone, 'ok'),
      title: bridgeTitle,
      detail: dgLoopFirstText(loopDutyRosterBridgeRecord.value.detail, loopUiBridgeRecord.value.detail),
      actions: actions.length ? actions : ['查看编制准入', '进入自进化 Loop'],
    }
  }
  if (loopRosterGateRecord.value.action === 'hold' || loopNotDeployedCount.value) {
    const targets = dgLoopArray(loopRosterRemediationRecord.value.target_employee_ids).map((id) => dgLoopString(id)).filter(Boolean)
    return {
      tone: 'bad',
      title: dgLoopFirstText(loopRosterRemediationRecord.value.title, '编制员工未登记上岗'),
      detail: `${dgLoopFirstText(loopRosterRemediationRecord.value.detail, '编制内但未登记上岗，需要补登记后才允许自维护自动放行。')}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
      actions: [dgLoopFirstText(loopRosterRemediationRecord.value.action, 'register_duty_employees'), '确认上岗员工和商店员工隔离'],
    }
  }
  if (loopRosterGateRecord.value.blocking === true || loopOutOfRosterCount.value) {
    const targets = dgLoopArray(loopRosterRemediationRecord.value.target_employee_ids).map((id) => dgLoopString(id)).filter(Boolean)
    return {
      tone: 'bad',
      title: dgLoopFirstText(loopRosterRemediationRecord.value.title, 'Loop 混入非编制员工'),
      detail: `${dgLoopFirstText(loopRosterRemediationRecord.value.detail, `后端 gate=${dgLoopFirstText(loopRosterGateRecord.value.action, 'isolate')}，原因：${dgLoopFirstText(loopRosterGateRecord.value.reason, 'out_of_roster_participants_detected')}。`)}${targets.length ? ` 目标：${targets.slice(0, 4).join(' / ')}` : ''}`,
      actions: [dgLoopFirstText(loopRosterRemediationRecord.value.action, 'isolate_out_of_roster_participants'), '按 gate 策略隔离非编制员工'],
    }
  }
  if (!loopParticipantIds.value.length) {
    return {
      tone: 'warn',
      title: '本轮无编制员工参与证据',
      detail: '可能是缺证阈值未触发，也可能是 runtime 没有回写 employee_id。',
      actions: ['查看缺证门禁', '检查 ledger employee_id/actor'],
    }
  }
  if (!loopDepartmentCoverage.value.length) {
    return {
      tone: 'warn',
      title: '参与者未落到六部门',
      detail: 'Loop 参与者命中了编制基线，但没有命中六部门 subzones，需检查编制映射。',
      actions: ['检查 SIX_LINE_DEPARTMENTS.subzones', '检查员工 ID 是否迁移'],
    }
  }
  return {
    tone: loopOpenRunCount.value > 0 ? 'run' : 'ok',
    title: '编制与 Loop 已对齐',
    detail: `${loopParticipantIds.value.length} 个编制员工参与，覆盖 ${loopDepartmentCoverage.value.length} 个部门分组。`,
    actions: ['点击员工定位节点', '进入自进化 Loop 看完整时间线'],
  }
})

const selectedLoopParticipant = computed(() => {
  const id = selectedEmp.value?.id
  return id ? loopParticipantById.value[id] || null : null
})

function loopParticipantList(row: Record<string, any> | null, key: string): string {
  if (!row) return '—'
  const list = dgLoopArray(row[key]).map((x) => dgLoopString(x)).filter(Boolean)
  return list.length ? list.join(' / ') : '—'
}

const selectedLoopTimelineSummary = computed(() => {
  const participant = selectedLoopParticipant.value
  if (!participant) return null
  const runIds = dgLoopArray(participant.run_ids).map((x) => dgLoopString(x)).filter(Boolean)
  if (!runIds.length) return null
  const timelines = dgLoopArray(dgLoopRecord(loopRuntimeStatus.value).run_timelines)
    .map((x) => dgLoopRecord(x))
  const matched = timelines.find((t) => runIds.includes(dgLoopString(t.run_id)))
  if (!matched) return null
  const items = dgLoopArray(matched.items).map((x) => dgLoopRecord(x))
  const last = items[items.length - 1] || {}
  return {
    runId: dgLoopString(matched.run_id),
    count: items.length,
    lastLabel: dgLoopString(last.label || last.step || last.phase),
    lastStatus: dgLoopString(last.status || last.reason),
  }
})

const selectedLoopContext = computed(() => {
  const emp = selectedEmp.value
  if (!emp) return null
  if (selectedLoopParticipant.value) {
    return {
      tone: 'run',
      title: '本轮参与自进化 Loop',
      detail: `${emp.id} 已被 runtime 标记为参与员工，角色：${dgLoopFirstText(selectedLoopParticipant.value.role_label, selectedLoopParticipant.value.role, '员工')}。`,
    }
  }
  if (!loopRuntimeStatus.value) {
    return {
      tone: 'warn',
      title: 'Loop runtime 未连接',
      detail: '当前只能看到编制和员工健康信息，无法判断该员工是否参与本轮自维护。',
    }
  }
  if (!ALL_PLANNED_IDS.has(emp.id)) {
    return {
      tone: 'bad',
      title: '非编制员工',
      detail: '该员工不在编制基线内，不会被当作上岗员工参与自进化 Loop 高亮。',
    }
  }
  if (!isDeployedDutyRosterRow(emp)) {
    return {
      tone: 'warn',
      title: '编制内但未上岗',
      detail: '该员工属于编制基线，但当前不是已登记上岗 employee_pack，不能作为真实执行工位参与本轮调度。',
    }
  }
  if (!loopParticipantIds.value.length) {
    return {
      tone: 'idle',
      title: '等待 Loop 派发',
      detail: '当前 runtime 没有暴露编制员工参与证据，可能还没有达到缺证阈值或 ledger 未回写 employee_id。',
    }
  }
  return {
    tone: 'idle',
    title: '未参与本轮 Loop',
    detail: '本轮自维护已有其他编制员工参与，该员工没有出现在 runtime participants 或 run timeline 中。',
  }
})

function nodeEmployeeId(data: unknown): string {
  const d = dgLoopRecord(data)
  const emp = dgLoopRecord(d.emp || d.employee || d.row)
  return dgLoopString(
    d.employee_id || d.employeeId || d.emp_id || d.empId || d.id || emp.id || emp.employee_id,
  )
}

function nodeLoopActive(data: unknown): boolean {
  const id = nodeEmployeeId(data)
  return !!id && loopParticipantIdSet.value.has(id)
}

function focusLoopParticipant(id: string) {
  const trimmed = dgLoopString(id)
  if (!trimmed) return
  viewMode.value = 'hub'
  nextTick(() => focusEmployee(trimmed))
}

function employeeSpaceLocation(employeeId?: string | null) {
  const id = dgLoopString(employeeId)
  return id
    ? { name: 'workflow-employee-space', query: { employee: id } }
    : { name: 'workflow-employee-space' }
}

async function runLoopDutyRegistration() {
  if (!loopCanRunDutyRegistration.value) return
  loopRemediationBusy.value = true
  loopRemediationError.value = ''
  loopRemediationResult.value = null
  try {
    const result = await api.adminYuangonOnboardRun({
      pkg_ids: loopRemediationTargetIds.value,
      force: true,
    }) as Record<string, any>
    loopRemediationResult.value = result
    if (result.ok !== false) {
      await load()
    }
    await refreshLoopRuntimeStatus()
  } catch (err: any) {
    loopRemediationError.value = String(err?.message || err?.detail || err || '补登记失败')
  } finally {
    loopRemediationBusy.value = false
  }
}

async function reviewLoopGovernanceAudit() {
  if (!loopCanReviewGovernanceAudit.value) return
  loopGovernanceReviewBusy.value = true
  loopGovernanceReviewError.value = ''
  loopGovernanceReviewResult.value = null
  try {
    const result = await api.selfMaintenanceGovernanceReview({
      note: 'admin-console duty roster graph reviewed governance audit',
    }) as Record<string, any>
    loopGovernanceReviewResult.value = result
    await refreshLoopRuntimeStatus()
  } catch (err: any) {
    loopGovernanceReviewError.value = String(err?.message || err?.detail || err || '治理审计复核失败')
  } finally {
    loopGovernanceReviewBusy.value = false
  }
}

onMounted(() => {
  void refreshLoopRuntimeStatus()
  loopRuntimeTimer = window.setInterval(() => {
    void refreshLoopRuntimeStatus()
  }, 30000)
})

onUnmounted(() => {
  if (loopRuntimeTimer != null) window.clearInterval(loopRuntimeTimer)
  loopRuntimeTimer = null
})

function closeOtherPanels(except?: string) {
  if (except !== 'gap') showGapPanel.value = false
  if (except !== 'run') showRunPanel.value = false
  if (except !== 'allhands') showAllHandsPanel.value = false
  if (except !== 'nokey') showNoKeyPanel.value = false
}

function togglePanel(panel: 'gap' | 'run' | 'allhands' | 'nokey') {
  const refs: Record<string, { value: boolean }> = {
    gap: showGapPanel,
    run: showRunPanel,
    allhands: showAllHandsPanel,
    nokey: showNoKeyPanel,
  }
  const isOpen = refs[panel].value
  closeOtherPanels(panel)
  refs[panel].value = !isOpen
  if (panel === 'nokey' && showNoKeyPanel.value) void loadNoKeyEmployees()
}

async function openNoKeyPanel() {
  togglePanel('nokey')
}

function isDetailOpen(key: string): boolean {
  return detailCollapsed.value[key] !== true
}

function toggleDetail(key: string) {
  detailCollapsed.value = { ...detailCollapsed.value, [key]: !detailCollapsed.value[key] }
}

async function loadNoKeyEmployees() {
  noKeyLoading.value = true
  noKeyError.value = ''
  try {
    const r = (await api.adminListNoKeyEmployees()) as NoKeyResponse
    noKeyData.value = r
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyLoading.value = false
  }
}

async function alignSingleEmployeeToAuto(row: NoKeyRow) {
  if (noKeyBusyRow.value[row.pkg_id]) return
  noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: true }
  try {
    await api.adminAlignSingleEmployeeLlmToAuto(row.pkg_id, false)
    await loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
    await loadCapabilities(employees.value.filter(isDeployedDutyRosterRow))
    await loadNoKeyEmployees()
  } catch (e: unknown) {
    noKeyError.value = e instanceof Error ? e.message : String(e)
  } finally {
    noKeyBusyRow.value = { ...noKeyBusyRow.value, [row.pkg_id]: false }
  }
}

function gotoAddKey() {
  router.push({ name: 'account', hash: '#api-keys' })
}

// ─── 全员汇报（员工大会）── /api/agent/butler/all-hands-report ────────────────
type AllHandsEmployeeRow = {
  employee_id: string
  name: string
  area: string
  status: string
  report_markdown: string
  cognition_error: string
  warnings: string[]
  manifest_signals: {
    name: string
    persona: string
    expertise: string[]
    handlers: string[]
    depends_on: string[]
    skills: { name: string; brief: string; kind: string }[]
    workflow_id: number
  }
  recent_failures: {
    id: number
    task: string
    status: string
    error: string
    duration_ms: number
    llm_tokens: number
    created_at: string | null
  }[]
  research_sources: { title: string; url: string }[]
  duration_ms?: number
  llm_tokens?: number
}
type AllHandsSynthesizedAnswer = {
  question: string
  markdown: string
  cited_employees: string[]
  generated_at: string
  model: string
  error?: string
}
type AllHandsReport = {
  ok: boolean
  error?: string
  started_at: string
  completed_at: string
  employees: AllHandsEmployeeRow[]
  summary: {
    total?: number
    ok?: number
    error?: number
    with_research?: boolean
    bench_provider?: string
    bench_model?: string
    user_question?: string
    synthesized?: boolean
  }
  synthesized_answer?: AllHandsSynthesizedAnswer | null
}
type AllHandsProgress = {
  stage: string
  total: number
  completed: number
  ok: number
  error: number
  percent: number
  current_employee_id: string
  current_employee_name: string
  current_employee_status: string
  updated_at: string
}
type AllHandsSessionSnapshot = {
  status: string
  error?: string | null
  artifact?: Record<string, unknown> | null
  planning_record?: {
    progress?: Partial<AllHandsProgress> | null
  } | null
}
type MeetingMinutesBlock = {
  text?: string
  generated_at?: string
  model?: string
  error?: string
}
type MeetingMinutesEmailMeta = {
  recipients_count?: number
  any_delivered?: boolean
  per_to?: { to: string; delivered: boolean; mode: string }[]
  skipped_reason?: string
}
const showAllHandsPanel = ref(false)
const allHandsBusy = ref(false)
const allHandsError = ref('')
const allHandsReport = ref<AllHandsReport | null>(null)
const allHandsWithResearch = ref(true)
const allHandsExpanded = ref<Record<string, boolean>>({})
const allHandsPlainOpen = ref<Record<string, boolean>>({})
const allHandsPlainText = ref<Record<string, string>>({})
const allHandsPlainLoading = ref<Record<string, boolean>>({})
/** 递增以使关闭面板或新汇报时丢弃过期的「说人话」请求结果，避免串写或二次请求只剩推理链 */
const allHandsPlainReqGen = ref<Record<string, number>>({})
const allHandsMeetingMinutes = ref<MeetingMinutesBlock | null>(null)
const allHandsMeetingMinutesEmail = ref<MeetingMinutesEmailMeta | null>(null)

/** 去掉推理模型常在正文里夹带的思维链片段（避免「说人话」区域展示思考过程） */
function stripEmbeddedReasoningTrace(s: string): string {
  const tagPairs: Array<{ o: string; c: string }> = [
    { o: 'think', c: 'think' },
    { o: 'thinking', c: 'thinking' },
    { o: 'redacted' + '_' + 'thinking', c: 'redacted' + '_' + 'thinking' },
  ]
  let out = s
  for (let p = 0; p < 12; p++) {
    let next = out
    for (const { o, c } of tagPairs) {
      const re = new RegExp('<' + o + '\\b[^>]*>[\\s\\S]*?</' + c + '>', 'gi')
      next = next.replace(re, '')
    }
    next = next.replace(/\n{3,}/g, '\n\n').trim()
    if (next === out) break
    out = next
  }
  return out
}
const allHandsSessionId = ref('')
/** 「员工大会问答」用户问题；非空时切换到 Q&A 模板 + 综合答复 */
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

async function openAllHandsPanel() {
  togglePanel('allhands')
  if (!showAllHandsPanel.value) return
  if (allHandsReport.value || allHandsBusy.value) return
  await runAllHands()
}

function applyAllHandsReport(report: AllHandsReport) {
  allHandsReport.value = report
  if (!report.ok) {
    allHandsError.value = report.error || '全员汇报失败'
    return
  }
  const next: Record<string, boolean> = {}
  for (const row of report.employees) next[row.employee_id] = true
  allHandsExpanded.value = next
}

function parseAllHandsReportFromArtifact(artifact: Record<string, unknown> | null | undefined): AllHandsReport | null {
  if (!artifact || typeof artifact !== 'object') return null
  const raw = (artifact as Record<string, unknown>).all_hands_report
  if (!raw || typeof raw !== 'object') return null
  const report = raw as AllHandsReport
  if (!Array.isArray((report as any).employees)) return null
  return report
}

function resetAllHandsProgress(total = 0) {
  const t = Math.max(0, Number(total) || 0)
  allHandsProgress.value = {
    stage: 'prepare',
    total: t,
    completed: 0,
    ok: 0,
    error: 0,
    percent: 0,
    current_employee_id: '',
    current_employee_name: '',
    current_employee_status: '',
    updated_at: '',
  }
}

function applyAllHandsProgress(raw: Partial<AllHandsProgress> | null | undefined) {
  if (!raw || typeof raw !== 'object') return
  const prev = allHandsProgress.value
  const total = Math.max(0, Number(raw.total ?? prev.total) || 0)
  const completedRaw = Math.max(0, Number(raw.completed ?? prev.completed) || 0)
  const completed = total > 0 ? Math.min(completedRaw, total) : completedRaw
  const ok = Math.max(0, Number(raw.ok ?? prev.ok) || 0)
  const error = Math.max(0, Number(raw.error ?? prev.error) || 0)
  const percentRaw = Number(raw.percent)
  const percent = Number.isFinite(percentRaw)
    ? Math.max(0, Math.min(100, Math.round(percentRaw)))
    : (total > 0 ? Math.round((completed / total) * 100) : 0)
  allHandsProgress.value = {
    stage: String(raw.stage ?? prev.stage ?? 'collect'),
    total,
    completed,
    ok,
    error,
    percent,
    current_employee_id: String(raw.current_employee_id ?? prev.current_employee_id ?? ''),
    current_employee_name: String(raw.current_employee_name ?? prev.current_employee_name ?? ''),
    current_employee_status: String(raw.current_employee_status ?? prev.current_employee_status ?? ''),
    updated_at: String(raw.updated_at ?? prev.updated_at ?? ''),
  }
}

async function copyAllHandsMeetingMinutes() {
  const t = (allHandsMeetingMinutes.value?.text || '').trim()
  if (!t) return
  try {
    await navigator.clipboard.writeText(t)
  } catch {
    /* ignore */
  }
}

function downloadAllHandsMeetingMinutes() {
  const t = (allHandsMeetingMinutes.value?.text || '').trim()
  if (!t) return
  const blob = new Blob([t], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `员工大会会议摘要-${new Date().toISOString().slice(0, 10)}.txt`
  a.click()
  URL.revokeObjectURL(url)
}

function stopAllHandsPolling() {
  if (allHandsPollTimer) {
    clearTimeout(allHandsPollTimer)
    allHandsPollTimer = 0
  }
}

async function pollAllHandsSession(sessionId: string) {
  stopAllHandsPolling()
  try {
    const sess = (await api.workbenchGetSession(sessionId)) as AllHandsSessionSnapshot
    applyAllHandsProgress(sess?.planning_record?.progress ?? null)
    if (sess.status === 'done') {
      allHandsBusy.value = false
      const report = parseAllHandsReportFromArtifact(sess.artifact ?? null)
      if (!report) {
        allHandsError.value = '全员汇报完成，但未返回有效报告内容'
        allHandsMeetingMinutes.value = null
        allHandsMeetingMinutesEmail.value = null
        return
      }
      applyAllHandsProgress({
        stage: 'completed',
        total: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        completed: Number(report.summary?.total ?? report.employees?.length ?? 0) || 0,
        ok: Number(report.summary?.ok ?? 0) || 0,
        error: Number(report.summary?.error ?? 0) || 0,
        percent: 100,
      })
      applyAllHandsReport(report)
      const art = sess.artifact
      if (art && typeof art === 'object') {
        const mmRaw = (art as Record<string, unknown>).meeting_minutes
        allHandsMeetingMinutes.value =
          mmRaw && typeof mmRaw === 'object' ? (mmRaw as MeetingMinutesBlock) : null
        const emRaw = (art as Record<string, unknown>).meeting_minutes_email
        allHandsMeetingMinutesEmail.value =
          emRaw && typeof emRaw === 'object' ? (emRaw as MeetingMinutesEmailMeta) : null
      } else {
        allHandsMeetingMinutes.value = null
        allHandsMeetingMinutesEmail.value = null
      }
      return
    }
    if (sess.status === 'error') {
      allHandsBusy.value = false
      allHandsError.value = String(sess.error || '全员汇报失败')
      return
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    if (/会话不存在|404/.test(msg)) {
      allHandsBusy.value = false
      allHandsError.value = `全员汇报会话已失效：${msg}`
      return
    }
  }
  if (!allHandsBusy.value || allHandsSessionId.value !== sessionId) return
  allHandsPollTimer = window.setTimeout(() => {
    void pollAllHandsSession(sessionId)
  }, 2000)
}

async function runAllHands(opts: { withQuestion?: boolean } = {}) {
  if (allHandsBusy.value) return
  stopAllHandsPolling()
  allHandsBusy.value = true
  allHandsError.value = ''
  allHandsSessionId.value = ''
  allHandsReport.value = null
  allHandsPlainOpen.value = {}
  allHandsPlainText.value = {}
  allHandsPlainLoading.value = {}
  allHandsPlainReqGen.value = {}
  allHandsMeetingMinutes.value = null
  allHandsMeetingMinutesEmail.value = null
  try {
    const realIds = employees.value.filter(isDeployedDutyRosterRow).map((e) => e.id)
    const cap = Math.max(1, realIds.length || 8)
    resetAllHandsProgress(cap)
    const useQuestion = opts.withQuestion === true && allHandsQuestion.value.trim().length > 0
    const payload: Record<string, unknown> = {
      employee_ids: realIds,
      with_research: useQuestion ? false : allHandsWithResearch.value,
      max_employees: cap,
      concurrency: 2,
    }
    if (useQuestion) {
      payload.user_question = allHandsQuestion.value.trim()
      payload.synthesize = true
    }
    const started = (await api.butlerAllHandsReportStartSession(payload as never)) as { session_id?: string; status?: string }
    const sid = String(started?.session_id || '').trim()
    if (!sid) throw new Error('启动全员汇报失败：后端未返回 session_id')
    allHandsSessionId.value = sid
    void pollAllHandsSession(sid)
  } catch (e: unknown) {
    allHandsBusy.value = false
    allHandsError.value = e instanceof Error ? e.message : String(e)
  }
}

async function askAllHandsQuestion() {
  if (!allHandsQuestion.value.trim()) {
    allHandsError.value = '请先输入要向员工大会提的问题'
    return
  }
  await runAllHands({ withQuestion: true })
}

function toggleAllHandsRow(id: string) {
  allHandsExpanded.value = {
    ...allHandsExpanded.value,
    [id]: !allHandsExpanded.value[id],
  }
}

async function requestPlainLang(row: AllHandsEmployeeRow) {
  const id = row.employee_id
  // toggle off if already open and loaded
  if (allHandsPlainOpen.value[id]) {
    allHandsPlainOpen.value = { ...allHandsPlainOpen.value, [id]: false }
    allHandsPlainReqGen.value = { ...allHandsPlainReqGen.value, [id]: (allHandsPlainReqGen.value[id] ?? 0) + 1 }
    return
  }
  allHandsPlainOpen.value = { ...allHandsPlainOpen.value, [id]: true }
  const cachedRaw = allHandsPlainText.value[id]
  const cached = stripEmbeddedReasoningTrace(typeof cachedRaw === 'string' ? cachedRaw : '')
  if (cached.length > 0) {
    if (cached !== cachedRaw) {
      allHandsPlainText.value = { ...allHandsPlainText.value, [id]: cached }
    }
    return
  }
  const gen = (allHandsPlainReqGen.value[id] ?? 0) + 1
  allHandsPlainReqGen.value = { ...allHandsPlainReqGen.value, [id]: gen }
  allHandsPlainLoading.value = { ...allHandsPlainLoading.value, [id]: true }
  try {
    const defaultLlm = (await api.llmResolveChatDefault()) as { provider: string; model: string } | null
    const provider = defaultLlm?.provider ?? 'openai'
    const model = defaultLlm?.model ?? 'gpt-4o-mini'

    const reportSnippet = row.report_markdown ? row.report_markdown.slice(0, 500) : '（无）'
    const userContent = [
      `员工名称：${row.name}（${row.employee_id}）`,
      `汇报状态：${row.status}`,
      `认知错误：${row.cognition_error || '无'}`,
      `警告条数：${row.warnings.length}，内容：${row.warnings.join('；') || '无'}`,
      `近期失败条数：${row.recent_failures.length}`,
      `调研来源条数：${row.research_sources.length}`,
      `汇报摘要（前500字）：${reportSnippet}`,
    ].join('\n')

    const messages = [
      {
        role: 'system',
        content:
          '你是一个说大白话的助手，帮老板（称呼对方为"爸爸"）看懂 AI 员工全员汇报的状态。' +
          '用口语化中文解释：这个员工的汇报有什么问题、缺哪些素材、为什么写不出来，或者一切正常是什么意思。' +
          '不要用技术术语，不要绕弯，直接说人话；禁止输出思维链、推理步骤、<think> 等标记或括号内的内心独白。' +
          '开头和结尾都要叫"爸爸"。回复控制在200字以内。',
      },
      { role: 'user', content: userContent },
    ]

    const res = (await api.llmChat(provider, model, messages, 1024)) as {
      content?: string
      choices?: { message?: { content?: string } }[]
    }
    if (allHandsPlainReqGen.value[id] !== gen) return
    const raw =
      String(res?.content ?? res?.choices?.[0]?.message?.content ?? '').trim() ||
      '爸爸，AI 没返回内容，可能是模型暂时不可用，稍后再试一下。'
    let text = stripEmbeddedReasoningTrace(raw)
    if (!text) {
      text =
        '爸爸，模型只返回了推理过程没有正文，可以把默认模型换成非推理款或稍后再试。'
    }
    allHandsPlainText.value = { ...allHandsPlainText.value, [id]: text }
  } catch (e) {
    if (allHandsPlainReqGen.value[id] !== gen) return
    allHandsPlainText.value = {
      ...allHandsPlainText.value,
      [id]: `爸爸，调用 AI 翻译时出错了：${e instanceof Error ? e.message : String(e)}`,
    }
  } finally {
    if (allHandsPlainReqGen.value[id] === gen) {
      allHandsPlainLoading.value = { ...allHandsPlainLoading.value, [id]: false }
    }
  }
}

function focusEmployee(id: string) {
  const trimmed = String(id || '').trim()
  if (!trimmed) return
  gapFocusHint.value = ''
  const emp = employees.value.find((e) => e.id === trimmed)
  if (!emp) {
    showGapPanel.value = true
    gapFocusHint.value = `未找到员工「${trimmed}」`
    selectedEmp.value = null
    return
  }
  if (emp.source === 'v1_catalog') {
    showGapPanel.value = true
    gapFocusHint.value = `岗位「${emp.name || emp.id}」尚未上架 Catalog，请在桌面服务器后台补登记`
    selectedEmp.value = null
    return
  }
  selectedEmp.value = emp
  runTargetId.value = emp.id
  showDispatch.value = false
  taskResult.value = null
  taskError.value = null
  syncEmployeeRouteQuery(emp.id)
  nextTick(() => {
    void fitView({ nodes: [trimmed], padding: 0.35, duration: 400 }).catch(() => {
      void fitView({ padding: 0.12, duration: 300 })
    })
  })
}

function focusAllHandsEmployee(id: string) {
  focusEmployee(id)
}

function syncEmployeeRouteQuery(employeeId?: string | null) {
  if (!isPage.value) return
  const nextQuery = { ...route.query }
  const id = String(employeeId || '').trim()
  if (id) nextQuery.employee = id
  else delete nextQuery.employee
  void router.replace({ query: nextQuery })
}

async function applyEmployeeQueryFromRoute() {
  const raw = route.query.employee
  const id = typeof raw === 'string'
    ? raw.trim()
    : Array.isArray(raw)
      ? String(raw[0] || '').trim()
      : ''
  if (!id || loading.value || !employees.value.length) return
  focusEmployee(id)
}

function publishFollowUpToButler(row: AllHandsEmployeeRow) {
  // 把单个员工的汇报作为 brief 推到数字管家事件总线，让管家做后续动作
  publishButlerTask({
    source: 'admin-duty-graph:all-hands',
    employeeId: row.employee_id,
    employeeName: row.name,
    brief:
      `请基于以下「员工大会」汇报，识别需要立即跟进的事项并给出执行计划：\n\n` +
      (row.report_markdown || '（无 Markdown 报告）'),
    inputData: {
      manifest_signals: row.manifest_signals,
      recent_failures: row.recent_failures,
      research_sources: row.research_sources,
    },
    includeDependencies: true,
    allowHighRisk: false,
    maxConcurrency: 2,
  })
}

const allHandsAreaPalette: Record<string, string> = AREA_COLORS
let   countdownTimer = 0
let   refreshTimer   = 0
let   runPollTimer   = 0
let   allHandsPollTimer = 0

// Graph run state
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

// ─────────────────────────────────────────────────────────────────────────────
// VueFlow
// ─────────────────────────────────────────────────────────────────────────────
const { fitView } = useVueFlow('admin-duty-graph')
const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])

const CENTER_ID = '__center__'
const CLIENT_CENTER_ID = '__client_center__'
const NODE_W    = 220
const NODE_H    = 64
const DEPT_OUTER_COLS = 3
const DEPT_INNER_COLS = 3
const DEPT_GROUP_GAP_X = 44
const DEPT_GROUP_GAP_Y = 40
const WORKSHOP_NODE_W = 200
const WORKSHOP_NODE_H = 56

// ─────────────────────────────────────────────────────────────────────────────
// Health helpers
// ─────────────────────────────────────────────────────────────────────────────
const HEALTH_COLOR: Record<HealthLv, string> = {
  healthy: '#4ade80', warn: '#f59e0b', idle: '#6b7280', unknown: '#374151',
}
const HEALTH_LABEL: Record<HealthLv, string> = {
  healthy: '健康', warn: '告警', idle: '无记录', unknown: '—',
}

const RUN_STATUS_COLOR: Record<RunNodeStatus, string> = {
  idle: '#374151',
  pending: '#64748b',
  running: '#3b82f6',
  success: '#22c55e',
  failed: '#ef4444',
  skipped: '#f59e0b',
}
const RUN_STATUS_LABEL: Record<RunNodeStatus, string> = {
  idle: '未运行',
  pending: '等待',
  running: '运行中',
  success: '成功',
  failed: '失败',
  skipped: '跳过',
}

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

// ─────────────────────────────────────────────────────────────────────────────
// Phase 4: LLM activation helpers
// ─────────────────────────────────────────────────────────────────────────────
const LLM_ACT_COLOR: Record<LlmActLv, string> = {
  activated: '#818cf8',   // purple – LLM connected
  no_key:    '#ef4444',   // red    – key missing
  echo_only: '#6b7280',   // gray   – no LLM needed
  unknown:   '#374151',   // dark   – not yet loaded
}
const LLM_ACT_LABEL: Record<LlmActLv, string> = {
  activated: 'LLM 已激活',
  no_key:    'LLM 无密钥',
  echo_only: '仅回显',
  unknown:   '加载中',
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

// ─────────────────────────────────────────────────────────────────────────────
// Build hub-mode graph (Phase 1 / 2 layout)
// ─────────────────────────────────────────────────────────────────────────────
function buildHubGraph(emps: EmpRow[]) {
  const rosterEmps = emps.filter(isDutyGraphMember)
  const idSet = new Set(rosterEmps.map((e) => e.id))

  const rawNodes: Node[] = [
    {
      id: CENTER_ID,
      type: 'input',
      label: 'MODstore 在岗',
      position: { x: 0, y: 0 },
      style: {
        background: 'var(--color-primary, #6366f1)', color: '#fff',
        fontWeight: '700', border: 'none', borderRadius: '10px',
        padding: '10px 20px', minWidth: '140px', textAlign: 'center',
      },
    },
    ...rosterEmps.map((e) => {
      const hl  = healthLevel(e.id)
      const al  = llmActLevel(e.id)
      const rs  = runStatusLevel(e.id)
      const aColor = empAreaColor(e.id)
      return {
        id: e.id,
        label: e.name || e.id,
        position: { x: 0, y: 0 },
        data: {
          ...e,
          healthLevel: hl,
          healthColor: HEALTH_COLOR[hl],
          areaColor: aColor,
          llmActLevel: al,
          llmActColor: LLM_ACT_COLOR[al],
          runStatus: rs,
          runStatusColor: RUN_STATUS_COLOR[rs],
          capLevel: capabilityLevel(e.id),
          capColor: capabilityColor(e.id),
        },
        style: {
          background: e.source === 'v1_catalog' ? 'var(--color-bg-elevated,#1e1e2e)' : 'var(--color-bg-card,#252535)',
          color: 'var(--color-text-primary,#e0e0e0)',
          border: `1.5px solid ${e.source === 'v1_catalog' ? '#f59e0b88' : aColor + '88'}`,
          borderRadius: '8px', padding: '8px 14px', minWidth: `${NODE_W}px`, fontSize: '0.82rem',
        },
      } satisfies Node
    }),
  ]

  const rawEdges: Edge[] = [
    ...rosterEmps.map((e) => ({
      id: `hub-${e.id}`,
      source: CENTER_ID,
      target: e.id,
      style: { stroke: 'var(--color-border-subtle,#555)', strokeWidth: 1.5 },
    })),
    ...buildDepEdges(idSet),
  ]

  applyLayout(rawNodes, rawEdges)
}

// Build department-mode graph（与物理分区同款：开放大栏 + 区内卡片）
function deptNodeId(deptId: string, empId: string): string {
  return `${deptId}::${empId}`
}

function flattenDeptMemberIds(deptId: string): string[] {
  const dept = SIX_LINE_DEPARTMENTS[deptId]
  const seen = new Set<string>()
  const out: string[] = []
  for (const sub of Object.values(dept.subzones)) {
    for (const id of sub.ids) {
      if (seen.has(id)) continue
      seen.add(id)
      out.push(id)
    }
  }
  return out
}

function buildDepartmentGraph(emps: EmpRow[]) {
  const rosterEmps = emps.filter(isDutyGraphMember)
  const deployedIds = new Set(rosterEmps.map((e) => e.id))
  const allRows = buildRosterEmployeeRows(new Set([...ALL_PLANNED_IDS].filter((id) => !deployedIds.has(id))))
  const catalogIds = new Set(rosterEmps.map((e) => e.id))
  const rawNodes: Node[] = []
  const rawEdges: Edge[] = []

  for (const deptId of DEPARTMENT_ORDER) {
    const dept = SIX_LINE_DEPARTMENTS[deptId]
    const color = DEPARTMENT_COLORS[deptId] ?? '#6366f1'
    const memberIds = flattenDeptMemberIds(deptId)
    if (!memberIds.length) continue

    const deptGid = `dept-${deptId}`
    rawNodes.push({
      id: deptGid,
      type: 'group',
      label: dept.label,
      position: { x: 0, y: 0 },
      style: {
        background: color + '14',
        border: `1px solid ${color}55`,
        borderRadius: '12px',
        padding: '0',
        color,
        fontWeight: '700',
        fontSize: '0.78rem',
      },
    })

    for (const empId of memberIds) {
      const emp = rosterEmps.find((e) => e.id === empId) || allRows.find((e) => e.id === empId)
      const deployed = catalogIds.has(empId) && !missingLocalPackIds.value.has(empId)
      const hl = healthLevel(empId)
      const al = llmActLevel(empId)
      const rs = runStatusLevel(empId)
      rawNodes.push({
        id: deptNodeId(deptId, empId),
        label: emp?.name || YUANGON_PKG_ROLE_LABELS[empId] || empId,
        parentNode: deptGid,
        extent: 'parent',
        position: { x: 0, y: 0 },
        data: {
          id: empId,
          name: emp?.name,
          source: emp?.source,
          deployed,
          healthLevel: hl,
          healthColor: HEALTH_COLOR[hl],
          areaColor: color,
          llmActLevel: al,
          llmActColor: LLM_ACT_COLOR[al],
          runStatus: rs,
          runStatusColor: RUN_STATUS_COLOR[rs],
          capLevel: capabilityLevel(empId),
          capColor: capabilityColor(empId),
        },
        style: {
          background: deployed ? 'var(--color-bg-card,#ffffff)' : 'rgba(251,191,36,0.10)',
          color: 'var(--color-text-primary,#172033)',
          border: deployed ? `1px solid ${color}55` : '1px dashed #d97706',
          borderRadius: '10px',
          padding: '8px 12px',
          width: `${NODE_W}px`,
          minWidth: `${NODE_W}px`,
          maxWidth: `${NODE_W}px`,
          fontSize: '0.78rem',
          boxSizing: 'border-box',
        },
      })
    }

    const craftSet = new Set(memberIds.filter((id) => CRAFT_PIPELINE_ORDER.includes(id)))
    if (craftSet.size >= 2) {
      rawEdges.push(...buildCraftPipelineEdgesForDept(deptId, craftSet))
    }
    if (memberIds.length > 1) {
      for (let i = 1; i < memberIds.length; i++) {
        const prev = memberIds[i - 1]
        const curr = memberIds[i]
        if (craftSet.has(prev) && craftSet.has(curr)) continue
        rawEdges.push({
          id: `chain-${deptId}-${prev}-${curr}`,
          source: deptNodeId(deptId, prev),
          target: deptNodeId(deptId, curr),
          type: 'smoothstep',
          style: { stroke: '#94a3b8', strokeWidth: 1.5 },
        })
      }
    }
  }

  applyDepartmentLayout(rawNodes, rawEdges)
}

function applyDepartmentLayout(rawNodes: Node[], rawEdges: Edge[]) {
  const groupIds = DEPARTMENT_ORDER.map((id) => `dept-${id}`).filter((gid) =>
    rawNodes.some((n) => n.id === gid),
  )
  const boxSizes = new Map<string, { w: number; h: number }>()

  for (const gid of groupIds) {
    const children = rawNodes.filter((n) => n.parentNode === gid)
    const { positions, width, height } = computeGridLayout(
      children.map((c) => c.id),
      {
        cols: DEPT_INNER_COLS,
        cellWidth: NODE_W,
        cellHeight: NODE_H,
        gapX: 10,
        gapY: 10,
        paddingX: 12,
        paddingY: 30,
        paddingBottom: 12,
      },
    )
    for (const child of children) {
      const p = positions.get(child.id)
      if (p) child.position = p
    }
    const w = Math.max(width, 280)
    boxSizes.set(gid, { w, h: height })
    const group = rawNodes.find((n) => n.id === gid)
    if (group) {
      group.style = {
        ...(group.style as Record<string, string>),
        width: `${w}px`,
        height: `${height}px`,
        minWidth: `${w}px`,
      }
    }
  }

  const colWidths = [0, 1, 2].map((c) =>
    Math.max(
      280,
      ...groupIds.filter((_, i) => i % DEPT_OUTER_COLS === c).map((gid) => boxSizes.get(gid)!.w),
    ),
  )
  const rowHeights = [0, 1].map((r) =>
    Math.max(
      180,
      ...groupIds
        .filter((_, i) => Math.floor(i / DEPT_OUTER_COLS) === r)
        .map((gid) => boxSizes.get(gid)!.h),
    ),
  )

  groupIds.forEach((gid, idx) => {
    const col = idx % DEPT_OUTER_COLS
    const row = Math.floor(idx / DEPT_OUTER_COLS)
    let x = 0
    for (let c = 0; c < col; c++) x += colWidths[c] + DEPT_GROUP_GAP_X
    let y = 0
    for (let r = 0; r < row; r++) y += rowHeights[r] + DEPT_GROUP_GAP_Y
    const group = rawNodes.find((n) => n.id === gid)
    if (group) group.position = { x, y }
  })

  flowNodes.value = rawNodes
  flowEdges.value = rawEdges
}

// ─────────────────────────────────────────────────────────────────────────────
// Build area-mode graph (Phase 3-a) — legacy yuangon 分区，保留供回退
// ─────────────────────────────────────────────────────────────────────────────
function buildAreaGraph(emps: EmpRow[]) {
  const rosterEmps = emps.filter(isDutyGraphMember)
  const deployedIds = new Set(rosterEmps.map((e) => e.id))
  const rawNodes: Node[] = []
  const rawEdges: Edge[] = []

  // Group nodes per area —— 只渲染本区中已在岗的员工；缺岗员工放右侧清单
  for (const [areaId, { label, ids }] of Object.entries(ALL_AREAS)) {
    const color = AREA_COLORS[areaId] ?? '#6366f1'

    // 本区在岗员工 IDs（按 ALL_AREAS 顺序保留稳定排序）
    const liveIds = ids.filter((empId) => deployedIds.has(empId))
    if (liveIds.length === 0) {
      // 整个区都没人在岗，跳过该分组节点，避免空盒子
      continue
    }

    // Parent group node
    rawNodes.push({
      id: areaId,
      type: 'group',
      label,
      position: { x: 0, y: 0 },
      style: {
        background: color + '12',
        border: `1.5px solid ${color}55`,
        borderRadius: '12px',
        padding: '32px 16px 16px',
        minWidth: '260px',
        color: color,
        fontWeight: '700',
        fontSize: '0.8rem',
      },
    })

    // Employee nodes as children（仅在岗）
    for (const empId of liveIds) {
      const emp = rosterEmps.find((e) => e.id === empId)
      const deployed = true
      const hl = healthLevel(empId)

      const al = llmActLevel(empId)
      const rs = runStatusLevel(empId)
      rawNodes.push({
        id: empId,
        label: emp?.name || empId,
        parentNode: areaId,
        extent: 'parent',
        position: { x: 0, y: 0 },
        data: {
          id: empId,
          name: emp?.name,
          source: emp?.source,
          deployed,
          healthLevel: hl,
          healthColor: HEALTH_COLOR[hl],
          areaColor: color,
          llmActLevel: al,
          llmActColor: LLM_ACT_COLOR[al],
          runStatus: rs,
          runStatusColor: RUN_STATUS_COLOR[rs],
          capLevel: capabilityLevel(empId),
          capColor: capabilityColor(empId),
        },
        style: {
          background: !deployed
            ? 'rgba(239,68,68,0.08)'
            : emp?.source === 'v1_catalog'
              ? 'var(--color-bg-elevated,#1e1e2e)'
              : 'var(--color-bg-card,#252535)',
          color: deployed ? 'var(--color-text-primary,#e0e0e0)' : '#ef444488',
          border: !deployed
            ? '1.5px dashed #ef444444'
            : `1.5px solid ${color}66`,
          borderRadius: '7px',
          padding: '6px 12px',
          minWidth: '200px',
          fontSize: '0.8rem',
        },
      })
    }
  }

  // Untracked running employees (not in any yuangon area, and not the virtual butler)
  const untracked = rosterEmps.filter(
    (e) => !ALL_PLANNED_IDS.has(e.id) && !isVirtualEmployee(e.id),
  )
  if (untracked.length) {
    rawNodes.push({
      id: '__untracked__',
      type: 'group',
      label: '游离员工（未在编制内）',
      position: { x: 0, y: 0 },
      style: {
        background: 'rgba(99,102,241,0.08)',
        border: '1.5px dashed #6366f144',
        borderRadius: '12px',
        padding: '32px 16px 16px',
        minWidth: '260px',
        color: '#6366f1',
        fontWeight: '700',
        fontSize: '0.8rem',
      },
    })
    for (const emp of untracked) {
      const hl = healthLevel(emp.id)
      const rs = runStatusLevel(emp.id)
      rawNodes.push({
        id: emp.id,
        label: emp.name || emp.id,
        parentNode: '__untracked__',
        extent: 'parent',
        position: { x: 0, y: 0 },
        data: {
          ...emp,
          healthLevel: hl,
          healthColor: HEALTH_COLOR[hl],
          runStatus: rs,
          runStatusColor: RUN_STATUS_COLOR[rs],
          capLevel: capabilityLevel(emp.id),
          capColor: capabilityColor(emp.id),
        },
        style: {
          background: 'var(--color-bg-card,#252535)',
          color: 'var(--color-text-primary,#e0e0e0)',
          border: '1.5px solid #6366f155',
          borderRadius: '7px', padding: '6px 12px', minWidth: '200px', fontSize: '0.8rem',
        },
      })
    }
  }

  rawEdges.push(...buildDepEdges(deployedIds))
  applyAreaLayout(rawNodes, rawEdges)
}

function buildCraftPipelineEdgesForDept(deptId: string, idSet: Set<string>): Edge[] {
  const edges: Edge[] = []
  const craftOrder = CRAFT_PIPELINE_ORDER
  for (let i = 1; i < craftOrder.length; i++) {
    const prev = craftOrder[i - 1]
    const curr = craftOrder[i]
    if (idSet.has(prev) && idSet.has(curr)) {
      edges.push({
        id: `pipeline-${deptId}-${prev}-${curr}`,
        source: deptNodeId(deptId, prev),
        target: deptNodeId(deptId, curr),
        label: '管线',
        style: { stroke: '#4ade80', strokeWidth: 2 },
        labelStyle: { fill: '#4ade80', fontSize: '10px' },
        animated: true,
        markerEnd: { type: 'arrowclosed', color: '#4ade80' } as any,
      })
    }
  }
  return edges
}

function buildDepEdges(idSet: Set<string>): Edge[] {
  const edges: Edge[] = []
  for (const [srcId, deps] of Object.entries(depsMap.value)) {
    if (!idSet.has(srcId)) continue
    if (!ALL_PLANNED_IDS.has(srcId) && !isVirtualEmployee(srcId)) continue
    for (const depId of deps) {
      if (!idSet.has(depId)) continue
      if (!ALL_PLANNED_IDS.has(depId) && !isVirtualEmployee(depId)) continue
      edges.push({
        id: `dep-${srcId}-${depId}`,
        source: srcId, target: depId,
        label: '依赖',
        style: { stroke: '#818cf8', strokeWidth: 1.5, strokeDasharray: '5,3' },
        labelStyle: { fill: '#818cf8', fontSize: '10px' },
        animated: true,
        markerEnd: { type: 'arrowclosed', color: '#818cf8' } as any,
      })
    }
  }

  const craftOrder = CRAFT_PIPELINE_ORDER
  for (let i = 1; i < craftOrder.length; i++) {
    const prev = craftOrder[i - 1]
    const curr = craftOrder[i]
    if (idSet.has(prev) && idSet.has(curr)) {
      edges.push({
        id: `pipeline-${prev}-${curr}`,
        source: prev, target: curr,
        label: '管线',
        style: { stroke: '#4ade80', strokeWidth: 2 },
        labelStyle: { fill: '#4ade80', fontSize: '10px' },
        animated: true,
        markerEnd: { type: 'arrowclosed', color: '#4ade80' } as any,
      })
    }
  }

  return edges
}

function applyLayout(rawNodes: Node[], rawEdges: Edge[]) {
  const posMap = computeAutoLayout(rawNodes, rawEdges, {
    direction: 'LR', nodeWidth: NODE_W, nodeHeight: NODE_H, rankSep: 140, nodeSep: 32,
  })
  for (const n of rawNodes) {
    const p = posMap.get(n.id); if (p) n.position = p
  }
  flowNodes.value = rawNodes
  flowEdges.value = rawEdges
}

function applyAreaLayout(rawNodes: Node[], rawEdges: Edge[]) {
  // Layout groups first with TB direction
  const groupNodes = rawNodes.filter((n) => !n.parentNode)
  const posMap = computeAutoLayout(groupNodes, [], {
    direction: 'LR', nodeWidth: 320, nodeHeight: 280, rankSep: 60, nodeSep: 40,
  })
  for (const n of groupNodes) {
    const p = posMap.get(n.id); if (p) n.position = p
  }
  // Layout children within each group with TB direction
  const groups = new Set(rawNodes.filter((n) => n.type === 'group').map((n) => n.id))
  for (const gid of groups) {
    const children = rawNodes.filter((n) => n.parentNode === gid)
    let cy = 0
    for (const c of children) {
      c.position = { x: 16, y: cy }
      cy += NODE_H + 12
    }
  }
  flowNodes.value = rawNodes
  flowEdges.value = rawEdges
}

// ─────────────────────────────────────────────────────────────────────────────
// 客户端车间图（仅管理端；不向用户端暴露）
// ─────────────────────────────────────────────────────────────────────────────
function buildClientWorkshopGraph() {
  const workshops = listClientWorkshops({ includeDisabled: true })
  const rawNodes: Node[] = [
    {
      id: CLIENT_CENTER_ID,
      type: 'input',
      label: 'MODstore · 客户端车间',
      position: { x: 0, y: 0 },
      style: {
        background: 'var(--color-primary, #6366f1)',
        color: '#fff',
        fontWeight: '700',
        border: 'none',
        borderRadius: '10px',
        padding: '10px 18px',
        minWidth: '160px',
        textAlign: 'center',
      },
    },
    ...workshops.map((w) => {
      const borderColor = w.kind === 'gear' ? '#818cf8' : '#38bdf8'
      return {
        id: clientWorkshopNodeId(w.id),
        label: w.label,
        position: { x: 0, y: 0 },
        data: {
          isWorkshop: true,
          workshop: w,
          workshopId: w.id,
        },
        style: {
          background: w.enabled ? 'var(--color-bg-card,#252535)' : 'rgba(55,65,81,0.35)',
          color: w.enabled ? 'var(--color-text-primary,#e0e0e0)' : '#9ca3af',
          border: `1.5px solid ${borderColor}${w.enabled ? 'aa' : '44'}`,
          borderRadius: '10px',
          padding: '8px 14px',
          minWidth: `${WORKSHOP_NODE_W}px`,
          fontSize: '0.85rem',
          fontWeight: '600',
          opacity: w.enabled ? 1 : 0.55,
        },
      } satisfies Node
    }),
  ]

  const rawEdges: Edge[] = workshops.map((w) => ({
    id: `ws-edge-${w.id}`,
    source: CLIENT_CENTER_ID,
    target: clientWorkshopNodeId(w.id),
    style: { stroke: '#64748b', strokeWidth: 1.5, strokeDasharray: '6,4' },
  }))

  const posMap = computeAutoLayout(rawNodes, rawEdges, {
    direction: 'LR',
    nodeWidth: WORKSHOP_NODE_W + 20,
    nodeHeight: WORKSHOP_NODE_H,
    rankSep: 100,
    nodeSep: 28,
  })
  for (const n of rawNodes) {
    const p = posMap.get(n.id)
    if (p) n.position = p
  }
  flowNodes.value = rawNodes
  flowEdges.value = rawEdges
}

// ─────────────────────────────────────────────────────────────────────────────
// 节点图：编制内且已在服务端上架 catalog；缺岗（v1_catalog 占位）不进 hub 辐射，
// 数字管家（virtual）进图。编制外 id 一律丢弃（与全库 listEmployees 脱钩）。
// ─────────────────────────────────────────────────────────────────────────────
const onDutyEmployees = computed<EmpRow[]>(() =>
  employees.value.filter((e) => e.source !== 'v1_catalog' && isDutyGraphMember(e)),
)

// ─────────────────────────────────────────────────────────────────────────────
// Reactivity: rebuild on data change
// ─────────────────────────────────────────────────────────────────────────────
watch([onDutyEmployees, healthMap, depsMap, viewMode, empLlmMap, capabilityMap, runNodeStatusMap, loopParticipantIdSet], () => {
  if (viewMode.value === 'loop') {
    flowNodes.value = []
    flowEdges.value = []
    return
  }
  if (viewMode.value === 'client') {
    buildClientWorkshopGraph()
  } else if (viewMode.value === 'department') {
    buildDepartmentGraph(onDutyEmployees.value)
  } else if (viewMode.value === 'legacy-area') {
    buildAreaGraph(onDutyEmployees.value)
  } else {
    buildHubGraph(onDutyEmployees.value)
  }
  const fitOpts =
    viewMode.value === 'department'
      ? { padding: 0.06, maxZoom: 0.85, duration: 300 }
      : { padding: 0.12, maxZoom: 1, duration: 300 }
  nextTick(() => fitView(fitOpts))
}, { deep: true })

watch(viewMode, (mode) => {
  if (mode === 'loop') {
    selectedEmp.value = null
    selectedWorkshop.value = null
    syncEmployeeRouteQuery(null)
  } else if (mode === 'client') {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
  } else {
    selectedWorkshop.value = null
  }
})

// ─────────────────────────────────────────────────────────────────────────────
// Phase 1: 编制内固定岗位 + 健康 staffing（不调用 listEmployees 全表）
// ─────────────────────────────────────────────────────────────────────────────
function buildRosterEmployeeRows(missingIds: Set<string>): EmpRow[] {
  const ids = [...ALL_PLANNED_IDS].sort((a, b) =>
    (YUANGON_PKG_ROLE_LABELS[a] ?? a).localeCompare(YUANGON_PKG_ROLE_LABELS[b] ?? b, 'zh-CN'),
  )
  return ids.map((id) => ({
    id,
    name: YUANGON_PKG_ROLE_LABELS[id] ?? id,
    source: missingIds.has(id) ? ('v1_catalog' as const) : ('catalog' as const),
  }))
}

async function load() {
  error.value = ''
  loadWarning.value = ''
  loading.value = true
  employees.value = []
  healthMap.value = {}
  depsMap.value = {}
  empLlmMap.value = {}
  capabilityMap.value = {}
  empCapabilityViewMap.value = {}
  llmStatusFailed.value = false
  // Phase 4: fetch LLM provider key status once (runs in parallel with staffing)
  const llmStatusPromise = api.llmStatus().then((res: unknown) => {
    const r = res as Record<string, unknown>
    llmStatusFailed.value = false
    llmFernetConfigured.value = Boolean(r?.fernet_configured)
    const providers = Array.isArray(r?.providers) ? (r.providers as Record<string, unknown>[]) : []
    const m: Record<string, LlmProviderSt> = {}
    for (const p of providers) {
      const pid = String(p.provider ?? '').trim()
      if (pid) m[pid] = {
        provider: pid,
        label: String(p.label ?? pid),
        has_platform_key: Boolean(p.has_platform_key),
        has_user_override: Boolean(p.has_user_override),
      }
    }
    llmStatusMap.value = m
  }).catch(() => {
    llmStatusFailed.value = true
    llmFernetConfigured.value = false
    llmStatusMap.value = {}
  })

  try {
    const health = (await api.adminDutyGraphHealth()) as Record<string, unknown>
    const staffing = health?.staffing as Record<string, unknown> | undefined
    const errStaff = typeof staffing?.error === 'string' ? staffing.error : ''
    if (errStaff) throw new Error(errStaff)
    const missingCatalogRaw = Array.isArray(staffing?.missing_employees)
      ? staffing!.missing_employees
      : []
    const missingCatalogIds = new Set(
      (missingCatalogRaw as unknown[]).map((x) => String(x ?? '').trim()).filter(Boolean),
    )
    const missingLocalRaw = Array.isArray(staffing?.missing_local_employee_packs)
      ? staffing!.missing_local_employee_packs
      : []
    missingLocalPackIds.value = new Set(
      (missingLocalRaw as unknown[]).map((x) => String(x ?? '').trim()).filter(Boolean),
    )
    employees.value = [...buildRosterEmployeeRows(missingCatalogIds), butlerEmployeeRow()]
    const localGap = missingLocalPackIds.value.size
    if (localGap > 0 && String(health?.source || '') === 'local') {
      loadWarning.value =
        `本机 mods/_employees 未安装 ${localGap} 个编制员工包（图谱仍展示）；可在运维闭环执行 install-local 或启动 MODstore :8788 后从 Catalog 安装。`
    }
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    // 健康检查失败仍展示本机编制矩阵（六部门视图可离线浏览）
    missingLocalPackIds.value = new Set()
    employees.value = [...buildRosterEmployeeRows(new Set()), butlerEmployeeRow()]
    loadWarning.value = msg
  } finally {
    loading.value = false
  }
  seedVirtualEmployees()
  await llmStatusPromise
  if (!runTargetId.value && employees.value.length) runTargetId.value = employees.value[0].id
  const backendEmps = employees.value.filter(isDeployedDutyRosterRow)
  void loadPhase2(backendEmps)
  void loadCapabilities(backendEmps)
  await nextTick()
  void applyEmployeeQueryFromRoute()
}

function butlerEmployeeRow(): EmpRow {
  return {
    id: BUTLER_PROFILE.id,
    name: BUTLER_PROFILE.name,
    source: 'virtual',
    industry: BUTLER_PROFILE.industry,
  }
}

/**
 * 给数字管家这种前端虚拟员工提供与真实员工同结构的元数据，
 * 这样后续 ``loadPhase2`` / ``loadCapabilities`` / 详情面板都不需要分支。
 */
function seedVirtualEmployees() {
  const view = butlerCapabilityView()
  empCapabilityViewMap.value = {
    ...empCapabilityViewMap.value,
    [BUTLER_PROFILE.id]: view,
  }
  empLlmMap.value = {
    ...empLlmMap.value,
    [BUTLER_PROFILE.id]: {
      provider: 'auto',
      model: 'auto',
      handlers: view.handlers,
      needsLlm: true,
      activated: anyProviderHasUsableKey() || llmStatusFailed.value,
      keySource: 'auto',
    },
  }
  healthMap.value = {
    ...healthMap.value,
    [BUTLER_PROFILE.id]: { total: 0, success: 0, rate: 0, lastExecution: null },
  }
  capabilityMap.value = {
    ...capabilityMap.value,
    [BUTLER_PROFILE.id]: {
      employee_id: BUTLER_PROFILE.id,
      name: BUTLER_PROFILE.name,
      source: 'virtual',
      deployed: true,
      executable: true,
      reasons: [],
      handlers: view.handlers,
      declared_dependencies: view.dependsOn,
      llm: { provider: 'auto', model: 'auto', needs_llm: true, activated: true, key_source: 'auto' },
      risk: {
        high_risk: true,
        requires_confirmation: true,
        details: [
          {
            handler: 'butler_orchestrate',
            reason: 'vibe-coding 改写 Mod / 工作流 / 员工包属高风险动作，须用户明确确认',
            requires_approval: true,
          },
        ],
      },
      recent_execution: null,
      recent_ops_audits: [],
    },
  }

  for (const cid of CRAFT_PIPELINE_ORDER) {
    const prev = craftEmployeeDependsOn(cid)
    if (!employees.value.some((e) => e.id === cid)) {
      employees.value.push({
        id: cid,
        name: YUANGON_PKG_ROLE_LABELS[cid] || cid,
        source: 'virtual',
        industry: '制作车间',
      })
    }
    healthMap.value = { ...healthMap.value, [cid]: { total: 0, success: 0, rate: 0, lastExecution: null } }
    if (prev) depsMap.value = { ...depsMap.value, [cid]: [prev] }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 2: health + deps (also used for auto-refresh)
// ─────────────────────────────────────────────────────────────────────────────
async function loadPhase2(emps: EmpRow[]) {
  if (!emps.length) return
  loadingP2.value = true
  const CONCUR = 6

  async function pool<T>(items: EmpRow[], fn: (e: EmpRow) => Promise<T>) {
    for (let i = 0; i < items.length; i += CONCUR) {
      await Promise.allSettled(items.slice(i, i + CONCUR).map(fn))
    }
  }

  await pool(emps, async (e) => {
    try {
      const s = await api.getEmployeeStatus(e.id) as Record<string, unknown>
      const st = (s?.execution_stats ?? {}) as Record<string, unknown>
      healthMap.value = {
        ...healthMap.value,
        [e.id]: {
          total:   Number(st.total_executions ?? 0),
          success: Number(st.success_count ?? 0),
          rate:    Number(st.success_rate ?? 0),
          lastExecution: typeof s.last_execution === 'string' ? s.last_execution : null,
        },
      }
    } catch { /* silent */ }
  })

  await pool(emps, async (e) => {
    try {
      const pack = await api.getEmployeeManifest(e.id) as Record<string, unknown>
      const mf = (pack?.manifest ?? pack) as Record<string, unknown>

      // ── depends_on ──────────────────────────────────────────────────────
      let deps: string[] = []
      if (Array.isArray(mf?.depends_on)) {
        deps = (mf.depends_on as unknown[]).map((d) => (typeof d === 'string' ? d.trim() : '')).filter(Boolean)
      } else {
        const v2d = mf?.employee_config_v2 as Record<string, unknown> | undefined
        const raw = (v2d?.collaboration as Record<string, unknown> | undefined)?.depends_on
        if (Array.isArray(raw)) deps = (raw as unknown[]).map((d) => (typeof d === 'string' ? d.trim() : '')).filter(Boolean)
      }
      if (deps.length) depsMap.value = { ...depsMap.value, [e.id]: deps }

      // ── Phase 4: extract LLM config from manifest ──────────────────────
      const v2 = mf?.employee_config_v2 as Record<string, unknown> | undefined
      const agentModel = (v2?.cognition as Record<string, unknown> | undefined)
        ?.agent as Record<string, unknown> | undefined
      const modelCfg = agentModel?.model as Record<string, unknown> | undefined
      const mfActions = mf?.actions as Record<string, unknown> | undefined
      const handlers = Array.isArray((v2?.actions as Record<string, unknown> | undefined)?.handlers)
        ? ((v2!.actions as Record<string, unknown>).handlers as string[])
        : (Array.isArray(mfActions?.handlers)
          ? (mfActions.handlers as unknown[]).map((h) => String(h ?? '')).filter(Boolean)
          : [])

      const provider   = String(modelCfg?.provider  ?? '').trim() || 'auto'
      const model      = String(modelCfg?.model_name ?? '').trim() || 'auto'
      const needsLlm   = handlers.some((h: string) => h !== 'echo' && h !== 'webhook')
      const isAutoLlm  = provider === 'auto' || model === 'auto'
      const provSt     = llmStatusMap.value[provider] as LlmProviderStatus | undefined
      const hasPlatKey = provSt?.has_platform_key ?? false
      const hasByokUsable =
        Boolean(provSt?.has_user_override) && llmFernetConfigured.value

      let credentialOk: boolean
      let keySource: EmpLlmCfg['keySource']
      if (isAutoLlm) {
        const anyOk = anyProviderHasUsableKey()
        credentialOk = anyOk
        keySource = anyOk ? 'auto' : 'none'
      } else {
        credentialOk = providerRowHasUsableKey(provSt, llmFernetConfigured.value)
        keySource = hasByokUsable ? 'byok' : hasPlatKey ? 'platform' : 'none'
      }

      const activated    = !needsLlm || credentialOk

      empLlmMap.value = {
        ...empLlmMap.value,
        [e.id]: { provider, model, handlers, needsLlm, activated, keySource },
      }

      // 「能做什么 · 怎么做」展示模型：直接复用 V2 manifest 字段
      empCapabilityViewMap.value = {
        ...empCapabilityViewMap.value,
        [e.id]: extractEmployeeCapabilityView(mf),
      }
    } catch { /* silent */ }
  })

  loadingP2.value = false
}

async function loadCapabilities(emps: EmpRow[]) {
  if (!emps.length) {
    capabilityMap.value = {}
    return
  }
  capLoading.value = true
  try {
    const payload = (await api.adminEmployeeExecutionCapabilities(
      emps.map((e) => e.id),
    )) as { items?: EmpCapability[] }
    const rows = Array.isArray(payload?.items) ? payload.items : []
    const next: Record<string, EmpCapability> = {}
    for (const row of rows) {
      const eid = String(row?.employee_id ?? '').trim()
      if (!eid) continue
      next[eid] = {
        employee_id: eid,
        name: String(row?.name ?? eid),
        source: String(row?.source ?? ''),
        deployed: Boolean(row?.deployed),
        executable: Boolean(row?.executable),
        reasons: Array.isArray(row?.reasons) ? row.reasons.map((x) => String(x ?? '')) : [],
        handlers: Array.isArray(row?.handlers) ? row.handlers.map((x) => String(x ?? '')) : [],
        declared_dependencies: Array.isArray(row?.declared_dependencies)
          ? row.declared_dependencies.map((x) => String(x ?? ''))
          : [],
        llm: {
          provider: String((row as any)?.llm?.provider ?? 'auto'),
          model: String((row as any)?.llm?.model ?? 'auto'),
          needs_llm: Boolean((row as any)?.llm?.needs_llm),
          activated: Boolean((row as any)?.llm?.activated),
          key_source: String((row as any)?.llm?.key_source ?? 'none'),
        },
        risk: {
          high_risk: Boolean((row as any)?.risk?.high_risk),
          requires_confirmation: Boolean((row as any)?.risk?.requires_confirmation),
          details: Array.isArray((row as any)?.risk?.details)
            ? ((row as any).risk.details as unknown[]).map((d) => ({
                handler: String((d as any)?.handler ?? ''),
                reason: String((d as any)?.reason ?? ''),
                command_id: String((d as any)?.command_id ?? ''),
                requires_approval: Boolean((d as any)?.requires_approval),
              }))
            : [],
        },
        recent_execution: (row as any)?.recent_execution
          ? {
              id: Number((row as any).recent_execution.id) || 0,
              status: String((row as any).recent_execution.status ?? ''),
              task: String((row as any).recent_execution.task ?? ''),
              duration_ms: Number((row as any).recent_execution.duration_ms) || 0,
              llm_tokens: Number((row as any).recent_execution.llm_tokens) || 0,
              error: String((row as any).recent_execution.error ?? ''),
              created_at: typeof (row as any).recent_execution.created_at === 'string'
                ? (row as any).recent_execution.created_at
                : null,
            }
          : null,
        recent_ops_audits: Array.isArray((row as any)?.recent_ops_audits)
          ? ((row as any).recent_ops_audits as unknown[]).map((a) => ({
              id: Number((a as any)?.id) || 0,
              handler: String((a as any)?.handler ?? ''),
              command_id: String((a as any)?.command_id ?? ''),
              exit_code: (a as any)?.exit_code == null ? null : Number((a as any).exit_code),
              dry_run: Boolean((a as any)?.dry_run),
              approval_required: Boolean((a as any)?.approval_required),
              created_at: typeof (a as any)?.created_at === 'string' ? (a as any).created_at : null,
            }))
          : [],
      }
    }
    capabilityMap.value = next
  } catch {
    capabilityMap.value = {}
  } finally {
    capLoading.value = false
  }
}

function parseJsonObjectInput(raw: string): Record<string, unknown> {
  const text = String(raw || '').trim()
  if (!text) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (err: unknown) {
    throw new Error(err instanceof Error ? err.message : 'input_data JSON 解析失败')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('input_data 必须是 JSON 对象')
  }
  return parsed as Record<string, unknown>
}

function applyRunNodeStatus(run: DutyGraphRun | null) {
  if (!run || !Array.isArray(run.nodes)) {
    runNodeStatusMap.value = {}
    return
  }
  const next: Record<string, RunNodeStatus> = {}
  for (const node of run.nodes) {
    const eid = String(node?.employee_id ?? '').trim()
    if (!eid) continue
    const raw = String(node?.status ?? '').trim() as RunNodeStatus
    next[eid] = (['pending', 'running', 'success', 'failed', 'skipped'] as RunNodeStatus[]).includes(raw)
      ? raw
      : 'idle'
  }
  runNodeStatusMap.value = next
}

function stopRunPolling() {
  if (runPollTimer) {
    clearTimeout(runPollTimer)
    runPollTimer = 0
  }
}

async function pollRunDetail(runId: number) {
  stopRunPolling()
  try {
    const run = (await api.adminDutyGraphRunDetail(runId)) as DutyGraphRun
    latestRun.value = run
    applyRunNodeStatus(run)
    if (run?.status === 'running' || run?.status === 'pending') {
      runPollTimer = window.setTimeout(() => {
        void pollRunDetail(runId)
      }, 2000)
    }
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
  }
}

async function startGraphRun() {
  if (runBusy.value) return
  const targetId = String(runTargetId.value || '').trim()
  if (!targetId) {
    runError.value = '请选择目标员工'
    return
  }
  if (!runTaskBrief.value.trim()) {
    runError.value = '请填写任务 brief'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(runInputJson.value)
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
    return
  }
  runBusy.value = true
  runError.value = ''
  try {
    const run = (await api.adminDutyGraphRunStart({
      target_employee_id: targetId,
      task: runTaskBrief.value.trim(),
      input_data: inputData,
      include_dependencies: runIncludeDependencies.value,
      max_concurrency: Number(runMaxConcurrency.value) || 2,
      allow_high_risk_real_run: runAllowHighRisk.value,
    })) as DutyGraphRun
    latestRun.value = run
    applyRunNodeStatus(run)
    if (run?.id && (run?.status === 'running' || run?.status === 'pending')) {
      void pollRunDetail(Number(run.id))
    }
    // 刷新局部数据，让执行次数/最近执行及时可见
    setTimeout(() => {
      void loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
      void loadCapabilities(employees.value.filter(isDeployedDutyRosterRow))
    }, 1200)
  } catch (err: unknown) {
    runError.value = err instanceof Error ? err.message : String(err)
  } finally {
    runBusy.value = false
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Phase 3-d: auto-refresh
// ─────────────────────────────────────────────────────────────────────────────
function startAutoRefresh() {
  stopAutoRefresh()
  countdown.value = 30
  countdownTimer = window.setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      countdown.value = 30
      void loadPhase2(employees.value.filter(isDeployedDutyRosterRow))
    }
  }, 1000)
  refreshTimer = 0 // not used separately; countdown drives refresh
}

function stopAutoRefresh() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = 0 }
  if (refreshTimer)   { clearInterval(refreshTimer);   refreshTimer   = 0 }
}

readDutyRosterViewFromRoute()

watch(
  () => route.query.view,
  () => { readDutyRosterViewFromRoute() },
)

watch(
  () => route.query.employee,
  () => { void applyEmployeeQueryFromRoute() },
)

watch(autoRefresh, (v) => {
  if (v) startAutoRefresh(); else stopAutoRefresh()
})

watch(
  () => [props.open, props.variant] as const,
  ([open, variant]) => {
    const active = variant === 'page' || variant === 'embedded' || open
    if (active) {
      void load()
    } else {
      stopAutoRefresh()
      stopRunPolling()
      stopAllHandsPolling()
      autoRefresh.value = false
      allHandsBusy.value = false
      allHandsSessionId.value = ''
      resetAllHandsProgress()
      selectedEmp.value = null
      showGapPanel.value = false
      latestRun.value = null
      runNodeStatusMap.value = {}
    }
  },
  { immediate: true },
)

watch(
  employees,
  (rows) => {
    if (!rows.length) {
      runTargetId.value = ''
      return
    }
    if (!rows.some((r) => r.id === runTargetId.value)) {
      runTargetId.value = rows[0].id
    }
  },
  { deep: true },
)

onUnmounted(() => {
  stopAutoRefresh()
  stopRunPolling()
  stopAllHandsPolling()
})

// ─────────────────────────────────────────────────────────────────────────────
// Phase 3-b: gap analysis
// ─────────────────────────────────────────────────────────────────────────────
const gapRows = computed(() => {
  const rows: Array<{ id: string; name: string; area: string; state: GapState }> = []

  for (const [area, { label, ids }] of Object.entries(ALL_AREAS)) {
    for (const id of ids) {
      const row = employees.value.find((e) => e.id === id)
      const name = row?.name || YUANGON_PKG_ROLE_LABELS[id] || id
      const deployed =
        isVirtualEmployee(id)
        || (row?.source === 'catalog' && !missingLocalPackIds.value.has(id))
      rows.push({
        id,
        name,
        area: label,
        state: deployed ? 'deployed' : 'missing',
      })
    }
  }
  return rows
})

const gapSummary = computed(() => ({
  deployed:  gapRows.value.filter((r) => r.state === 'deployed').length,
  missing:   gapRows.value.filter((r) => r.state === 'missing').length,
  untracked: gapRows.value.filter((r) => r.state === 'untracked').length,
}))

// ─────────────────────────────────────────────────────────────────────────────
// Phase 3-c: task dispatch
// ─────────────────────────────────────────────────────────────────────────────
const taskBrief     = ref('')
const taskInputJson = ref('{}')
const dispatchConfirmHighRisk = ref(false)
const taskRunning   = ref(false)
const taskResult    = ref<string | null>(null)
const taskError     = ref<string | null>(null)
const showDispatch  = ref(false)

async function dispatchTask() {
  if (!selectedEmp.value || !taskBrief.value.trim() || taskRunning.value) return
  // 数字管家无后端 execute 接口；点击「派发执行」直接转走事件总线，让浮窗管家接手。
  if (isVirtualEmployee(selectedEmp.value.id)) {
    publishTaskToButler()
    return
  }
  if (selectedCapability.value?.risk?.high_risk && !dispatchConfirmHighRisk.value) {
    taskError.value = '该员工包含高风险动作，请先勾选二次确认后再执行'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(taskInputJson.value)
  } catch (err: unknown) {
    taskError.value = err instanceof Error ? err.message : String(err)
    return
  }
  taskRunning.value = true
  taskResult.value  = null
  taskError.value   = null
  try {
    const res = await api.executeEmployeeTask(selectedEmp.value.id, taskBrief.value.trim(), inputData) as Record<string, unknown>
    // Normalise result to a readable string
    if (typeof res === 'string') {
      taskResult.value = res
    } else if (res?.summary) {
      taskResult.value = String(res.summary)
    } else {
      const summary = {
        duration_ms: Number(res?.duration_ms ?? 0) || 0,
        llm_tokens: Number(res?.llm_tokens ?? 0) || 0,
        cognition_error: typeof res?.cognition_error === 'string' ? res.cognition_error : '',
        result: res?.result ?? null,
      }
      taskResult.value = JSON.stringify(summary, null, 2)
    }
    // Refresh health + execution list for this employee after execution
    setTimeout(() => {
      void loadPhase2([selectedEmp.value!])
      void loadCapabilities([selectedEmp.value!])
      void fetchExecMetrics(false)
    }, 1500)
  } catch (e: unknown) {
    taskError.value = e instanceof Error ? e.message : String(e)
  } finally {
    taskRunning.value = false
  }
}

function publishTaskToButler() {
  if (!selectedEmp.value || !taskBrief.value.trim() || taskRunning.value) return
  if (selectedCapability.value?.risk?.high_risk && !dispatchConfirmHighRisk.value) {
    taskError.value = '该员工包含高风险动作，请先勾选二次确认后再发布'
    return
  }
  let inputData: Record<string, unknown> = {}
  try {
    inputData = parseJsonObjectInput(taskInputJson.value)
  } catch (err: unknown) {
    taskError.value = err instanceof Error ? err.message : String(err)
    return
  }
  const emp = selectedEmp.value
  publishButlerTask({
    source: 'admin-duty-graph',
    employeeId: emp.id,
    employeeName: emp.name || emp.id,
    brief: taskBrief.value.trim(),
    inputData,
    includeDependencies: runIncludeDependencies.value,
    allowHighRisk: dispatchConfirmHighRisk.value || runAllowHighRisk.value,
    maxConcurrency: Number(runMaxConcurrency.value) || 2,
  })
  taskError.value = null
  taskResult.value = `已发布到数字管家：${emp.name || emp.id}`
}

// ─────────────────────────────────────────────────────────────────────────────
// Selection
// ─────────────────────────────────────────────────────────────────────────────
const selectedEmp = ref<EmpRow | null>(null)
const selectedWorkshop = ref<ClientWorkshop | null>(null)
const workshopRouteCopied = ref(false)

const selectedWorkshopLinkedEmployees = computed(() => {
  const ws = selectedWorkshop.value
  if (!ws) return []
  const ids = new Set(linkedRosterEmployeeIds(ws))
  if (!ids.size) return []
  return onDutyEmployees.value.filter((e) => ids.has(e.id))
})

const selectedWorkshopRouteHref = computed(() => {
  const ws = selectedWorkshop.value
  if (!ws) return ''
  const loc = resolveClientWorkshopRoute(ws)
  if (!loc) return ''
  try {
    return router.resolve(loc).href
  } catch {
    return ''
  }
})

function openSelectedWorkshopInClient() {
  const ws = selectedWorkshop.value
  if (!ws) return
  const loc = resolveClientWorkshopRoute(ws)
  if (!loc) return
  const href = router.resolve(loc).href
  window.open(href, '_blank', 'noopener,noreferrer')
}

async function copySelectedWorkshopRoute() {
  const href = selectedWorkshopRouteHref.value
  if (!href) return
  const path = href.startsWith('http') ? href : `${window.location.origin}${href}`
  try {
    await navigator.clipboard.writeText(path)
    workshopRouteCopied.value = true
    setTimeout(() => {
      workshopRouteCopied.value = false
    }, 2000)
  } catch {
    /* ignore */
  }
}

function onClientWorkshopNodeClick(node: Node) {
  if (node.id === CLIENT_CENTER_ID) {
    selectedWorkshop.value = null
    return
  }
  const wsId = parseClientWorkshopNodeId(node.id)
  if (!wsId) {
    selectedWorkshop.value = null
    return
  }
  selectedWorkshop.value = getClientWorkshop(wsId) ?? null
  selectedEmp.value = null
  syncEmployeeRouteQuery(null)
}

function goBackFromPage() {
  if (typeof window !== 'undefined' && window.history.length > 1) {
    router.back()
    return
  }
  if (router.hasRoute('duty-roster-graph')) {
    void router.push({ name: 'duty-roster-graph', query: { view: 'department' } })
    return
  }
  if (router.hasRoute('other-tools')) {
    void router.push({ name: 'other-tools' })
    return
  }
  if (router.hasRoute('admin-database')) {
    void router.push({ name: 'admin-database' })
    return
  }
  void router.push({ name: 'chat' })
}

function focusEmployeeFromWorkshop(id: string) {
  viewMode.value = 'hub'
  selectedWorkshop.value = null
  nextTick(() => focusEmployee(id))
}

/** 管理员 API：员工任务执行明细（与运维 shell 审计不同） */
const execItems = ref<ExecRow[]>([])
const execTotal = ref(0)
const execLoading = ref(false)
const execLoadingMore = ref(false)
const execError = ref('')

async function fetchExecMetrics(append: boolean) {
  const emp = selectedEmp.value
  if (!emp) return
  if (isVirtualEmployee(emp.id)) {
    execItems.value = []
    execTotal.value = 0
    execLoading.value = false
    execLoadingMore.value = false
    return
  }
  if (append) execLoadingMore.value = true
  else {
    execLoading.value = true
    execError.value = ''
  }
  try {
    const offset = append ? execItems.value.length : 0
    const res = (await api.adminEmployeeExecutionMetrics(emp.id, {
      limit: EXEC_METRICS_PAGE,
      offset,
    })) as { items?: ExecRow[]; total?: number }
    const raw = Array.isArray(res?.items) ? res.items : []
    const items: ExecRow[] = raw.map((r) => ({
      id: Number(r.id),
      user_id: Number(r.user_id),
      task: typeof r.task === 'string' ? r.task : '',
      status: typeof r.status === 'string' ? r.status : '',
      duration_ms: Number(r.duration_ms) || 0,
      llm_tokens: Number(r.llm_tokens) || 0,
      error: typeof r.error === 'string' ? r.error : '',
      created_at: typeof r.created_at === 'string' ? r.created_at : null,
    }))
    if (append) execItems.value = [...execItems.value, ...items]
    else execItems.value = items
    execTotal.value = Number(res?.total ?? 0)
  } catch (e: unknown) {
    execError.value = e instanceof Error ? e.message : String(e)
    if (!append) execItems.value = []
  } finally {
    execLoading.value = false
    execLoadingMore.value = false
  }
}

watch(
  () => selectedEmp.value?.id,
  (id) => {
    execItems.value = []
    execTotal.value = 0
    execError.value = ''
    if (id) runTargetId.value = id
    dispatchConfirmHighRisk.value = false
    if (id) void fetchExecMetrics(false)
  },
)

function formatDurationMs(ms: number) {
  if (!Number.isFinite(ms) || ms < 0) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

const selectedHealth = computed<HealthSt | null>(() =>
  selectedEmp.value ? (healthMap.value[selectedEmp.value.id] ?? null) : null,
)
const selectedDeps = computed<string[]>(() =>
  selectedEmp.value ? (depsMap.value[selectedEmp.value.id] ?? []) : [],
)
const selectedCapabilityView = computed<EmployeeCapabilityView | null>(() =>
  selectedEmp.value ? (empCapabilityViewMap.value[selectedEmp.value.id] ?? null) : null,
)
const isSelectedVirtual = computed<boolean>(() =>
  Boolean(selectedEmp.value && isVirtualEmployee(selectedEmp.value.id)),
)
// Phase 4
const selectedLlm = computed<EmpLlmCfg | null>(() =>
  selectedEmp.value ? (empLlmMap.value[selectedEmp.value.id] ?? null) : null,
)
const selectedCapability = computed<EmpCapability | null>(() =>
  selectedEmp.value ? (capabilityMap.value[selectedEmp.value.id] ?? null) : null,
)
const selectedRunNode = computed<DutyGraphRunNode | null>(() => {
  const eid = selectedEmp.value?.id
  if (!eid || !latestRun.value?.nodes?.length) return null
  return latestRun.value.nodes.find((n) => n.employee_id === eid) ?? null
})

function onNodeClick({ node }: { node: Node }) {
  if (viewMode.value === 'client') {
    onClientWorkshopNodeClick(node)
    return
  }
  let id = node.id
  if (id === CENTER_ID || id === '__untracked__' || node.type === 'group') {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
    return
  }
  if (id.includes('::')) id = id.split('::')[1] ?? id
  const emp = employees.value.find((e) => e.id === id)
  if (!emp) {
    selectedEmp.value = null
    syncEmployeeRouteQuery(null)
    return
  }
  selectedEmp.value = emp
  runTargetId.value = emp.id
  showDispatch.value = false
  taskResult.value  = null
  taskError.value   = null
  taskBrief.value   = ''
  taskInputJson.value = '{}'
  dispatchConfirmHighRisk.value = false
  syncEmployeeRouteQuery(emp.id)
}

function buildDutyGraphEmployeePrefill(emp: EmpRow): Record<string, unknown> {
  const base = createEmptyEmployeeConfigV2() as Record<string, unknown>
  const ident = { ...(base.identity as Record<string, unknown>), id: emp.id, name: emp.name || emp.id }
  return {
    ...base,
    id: emp.id,
    name: emp.name || emp.id,
    identity: ident,
  }
}

function goUse(emp: EmpRow) {
  currentMode.value = 'client'
  if (!isPage.value) emit('close')
  if (isVirtualEmployee(emp.id)) {
    // 数字管家是常驻浮窗，没有独立工作台路由；带管理员到技能管理页
    void router.push({ name: 'admin-butler-skills' })
    return
  }
  if (emp.source === 'v1_catalog') {
    try {
      sessionStorage.setItem('modstore_employee_prefill', JSON.stringify(buildDutyGraphEmployeePrefill(emp)))
    } catch {
      /* quota / private mode */
    }
  }
  void router.push({ name: 'workbench-shell', params: { target: 'employee' }, query: { packId: emp.id, fromDutyGraph: '1' } })
}

function onAccountKeysNav() {
  if (!isPage.value) emit('close')
}

function onBackdropClick() {
  if (!isPage.value) emit('close')
}

/** 值班页工具栏「缺岗 N」：打开缺岗分析面板 */
function openGapPanel() {
  closeOtherPanels('gap')
  showGapPanel.value = true
  gapFocusHint.value = ''
}

defineExpose({ openGapPanel, focusEmployee })

// ─────────────────────────────────────────────────────────────────────────────
// Stats summary
// ─────────────────────────────────────────────────────────────────────────────
const stats = computed(() => ({
  total:     employees.value.length,
  catalogOk: employees.value.filter((e) => e.source === 'catalog').length,
  v1Only:    employees.value.filter((e) => e.source === 'v1_catalog').length,
  healthy:   employees.value.filter((e) => healthLevel(e.id) === 'healthy').length,
  depEdges:  Object.values(depsMap.value).reduce((s, d) => s + d.length, 0),
  // Phase 4（llmNoKey 不含前端虚拟员工：与 /duty-graph/no-key-employees 可修复列表一致）
  llmActive: employees.value.filter((e) => llmActLevel(e.id) === 'activated').length,
  llmNoKey:  employees.value.filter(
    (e) => !isVirtualEmployee(e.id) && llmActLevel(e.id) === 'no_key',
  ).length,
  execReady: employees.value.filter((e) => capabilityMap.value[e.id]?.executable).length,
  highRisk: employees.value.filter((e) => capabilityMap.value[e.id]?.risk?.high_risk).length,
}))

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function formatRate(r: number) { return `${Math.round(r)}%` }
function formatTime(iso?: string | null) {
  if (!iso) return '—'
  try { return new Date(iso).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}
</script>

<template>
  <Teleport :disabled="isInlineLayout" to="body">
    <transition name="dg-fade">
      <div
        v-if="isInlineLayout || open"
        :class="isInlineLayout ? 'dg-page-root dg-page-root--office' : 'dg-overlay'"
        :role="isPage ? undefined : isEmbedded ? undefined : 'dialog'"
        :aria-modal="isPage || isEmbedded ? undefined : true"
        aria-label="在岗员工节点图"
        @click.self="onBackdropClick"
      >
        <div :class="['dg-panel', isInlineLayout && 'dg-panel--page dg-panel--office', isEmbedded && 'dg-panel--embedded']">

          <!-- ══ Header ══════════════════════════════════════════════════════ -->
          <div class="dg-header">
            <div class="dg-header-left">
              <span class="dg-title">在岗员工节点图</span>
              <span
                class="dg-roster-hint"
                title="节点仅 yuangonDutyRoster 编制内岗位 + 数字管家；不含 catalog 中其它员工包。若仍出现编制外名称，说明浏览器仍在使用旧前端资源，请重新构建并强刷（Ctrl+F5）或清 CDN 缓存。"
              >编制 {{ ALL_PLANNED_IDS.size }} 岗</span>

              <div v-if="employees.length" class="dg-stats">
                <span class="dg-stat">共 <strong>{{ stats.total }}</strong> 人</span>
                <span class="dg-stat dg-stat--ok">✓ {{ stats.catalogOk }}</span>
                <span class="dg-stat dg-stat--healthy">♥ {{ stats.healthy }}</span>
                <span v-if="stats.execReady" class="dg-stat dg-stat--ok">▶ {{ stats.execReady }}</span>
                <button
                  type="button"
                  class="dg-stat dg-stat--toggle"
                  :class="{ 'dg-stat--toggle-open': showStatsDetail }"
                  @click="showStatsDetail = !showStatsDetail"
                >{{ showStatsDetail ? '▴ 收起' : '▾ 更多' }}</button>
                <template v-if="showStatsDetail">
                  <span v-if="stats.v1Only" class="dg-stat dg-stat--warn">仅目录 {{ stats.v1Only }}</span>
                  <span v-if="stats.depEdges" class="dg-stat dg-stat--dep">依赖边 {{ stats.depEdges }}</span>
                  <span v-if="stats.highRisk" class="dg-stat dg-stat--warn">高风险 {{ stats.highRisk }}</span>
                  <span
                    v-if="llmStatusFailed"
                    class="dg-stat dg-stat--warn"
                    title="无法拉取 /api/llm/status，无法判断平台密钥与 BYOK；非全员无密钥"
                  >⚠ 密钥状态未加载</span>
                  <template v-else>
                    <span v-if="stats.llmActive" class="dg-stat dg-stat--llm-ok">⚡ LLM {{ stats.llmActive }}</span>
                    <button
                      v-if="stats.llmNoKey"
                      type="button"
                      class="dg-stat dg-stat--llm-err dg-stat--clickable"
                      :class="{ 'dg-stat--active': showNoKeyPanel }"
                      title="点击查看哪些员工无密钥，并一键改为「自动」或去添加账户密钥"
                      @click="openNoKeyPanel"
                    >✗ 无密钥 {{ stats.llmNoKey }}</button>
                  </template>
                  <span v-if="capLoading" class="dg-stat dg-stat--muted">能力校验中…</span>
                  <button
                    v-if="loopRuntimeStatus"
                    type="button"
                    class="dg-stat dg-stat--loop dg-stat--clickable"
                    title="查看自进化 Loop 运行时"
                    @click="viewMode = 'loop'"
                  >Loop {{ loopStatusLabel }} · {{ loopParticipantIdSet.size }}</button>
                  <span v-if="loadingP2" class="dg-stat dg-stat--muted">⟳ 刷新中…</span>
                </template>
              </div>
            </div>

            <div class="dg-header-right">
              <div class="dg-toggle-group">
                <button :class="['dg-toggle', { active: viewMode === 'hub'  }]" @click="viewMode = 'hub' ">中心图</button>
                <button :class="['dg-toggle', { active: viewMode === 'department' }]" @click="viewMode = 'department'">六部门</button>
                <button :class="['dg-toggle', { active: viewMode === 'legacy-area' }]" @click="viewMode = 'legacy-area'">物理分区</button>
                <button :class="['dg-toggle', { active: viewMode === 'client' }]" @click="viewMode = 'client'">客户端车间</button>
                <button :class="['dg-toggle', { active: viewMode === 'loop' }]" @click="viewMode = 'loop'">自进化 Loop</button>
              </div>

              <div class="dg-loop-links" aria-label="员工闭环入口">
                <router-link :to="employeeSpaceLocation(selectedEmp?.id)" class="dg-loop-link">回员工空间</router-link>
                <router-link :to="{ name: 'workflow-visualization' }" class="dg-loop-link">流程可视化</router-link>
              </div>

              <button
                v-if="viewMode !== 'loop' && loopRuntimeStatus"
                type="button"
                class="dg-loop-status-chip"
                :class="`dg-loop-status-chip--${loopRuntimeContractStatus.tone === 'bad' ? 'bad' : (loopOpenRunCount > 0 ? 'run' : 'idle')}`"
                title="打开自进化 Loop 查看治理闭环与 runtime"
                @click="viewMode = 'loop'"
              >
                <span>Loop</span>
                <strong>{{ loopStatusLabel }}</strong>
                <small>{{ loopOpenRunCount }} runs · {{ loopParticipantIds.length }} emp</small>
              </button>

              <div class="dg-more-wrap">
                <button
                  :class="['dg-btn dg-btn--outline', { 'dg-btn--active': showMoreActions }]"
                  @click="showMoreActions = !showMoreActions"
                >操作 ▾</button>
                <transition name="dg-fade">
                  <div v-if="showMoreActions" class="dg-more-menu" @click="showMoreActions = false">
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showGapPanel }]"
                      @click="togglePanel('gap')"
                    >
                      缺岗分析
                      <span v-if="gapSummary.missing" class="dg-badge dg-badge--red">{{ gapSummary.missing }}</span>
                    </button>
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showRunPanel }]"
                      @click="togglePanel('run')"
                    >运行协作图</button>
                    <button
                      :class="['dg-more-item', { 'dg-more-item--active': showAllHandsPanel }]"
                      :disabled="allHandsBusy"
                      @click="togglePanel('allhands')"
                    >{{ allHandsBusy ? '员工大会进行中…' : '员工大会汇报' }}</button>
                    <button
                      v-if="stats.llmNoKey && !llmStatusFailed"
                      :class="['dg-more-item', { 'dg-more-item--active': showNoKeyPanel }]"
                      @click="togglePanel('nokey')"
                    >✗ 无密钥修复 ({{ stats.llmNoKey }})</button>
                  </div>
                </transition>
              </div>

              <button
                :class="['dg-btn', autoRefresh ? 'dg-btn--refresh-on' : 'dg-btn--ghost']"
                :title="autoRefresh ? `自动刷新已开启，${countdown}s 后刷新` : '开启自动刷新（30 s）'"
                @click="autoRefresh = !autoRefresh"
              >
                {{ autoRefresh ? `⟳ ${countdown}s` : '⟳' }}
              </button>

              <button class="dg-btn dg-btn--ghost" :disabled="loading" @click="load">
                {{ loading ? '…' : '↻' }}
              </button>
              <button
                v-if="isPage"
                type="button"
                class="dg-close dg-close--text"
                aria-label="返回上一页"
                @click="goBackFromPage"
              >
                ← 返回
              </button>
              <button v-else class="dg-close" aria-label="关闭" @click="emit('close')">✕</button>
            </div>
            <div v-if="$slots.pageActions" class="dg-header-actions">
              <slot name="pageActions" />
            </div>
          </div>

          <!-- ══ Error / 降级提示 ═══════════════════════════════════════════ -->
          <p v-if="error" class="dg-error">
            {{ error }}&nbsp;<button class="dg-btn--inline" @click="load">重试</button>
          </p>
          <p v-else-if="loadWarning" class="dg-error dg-error--warn">
            {{ loadWarning }}（已展示本机编制，部分运维数据可能不可用）&nbsp;
            <button class="dg-btn--inline" @click="load">重试</button>
          </p>

          <!-- ══ Body ═════════════════════════════════════════════════════════ -->
          <div class="dg-body">

            <!-- ── No-key panel：点 dg-stats「✗ 无密钥」打开 ──────────────────── -->
            <transition name="dg-slide-top">
              <div v-if="showNoKeyPanel" class="dg-nokey-panel">
                <div class="dg-nokey-header">
                  <span class="dg-nokey-title">✗ 无密钥员工修复</span>
                  <span v-if="noKeyData" class="dg-nokey-meta">
                    fernet={{ noKeyData.fernet_configured ? '已配置' : '未配置' }} ·
                    账户可用密钥={{ noKeyData.any_provider_has_key ? '有' : '无' }}
                  </span>
                  <button class="dg-btn dg-btn--ghost dg-btn--sm" :disabled="noKeyLoading" @click="loadNoKeyEmployees">
                    {{ noKeyLoading ? '加载中…' : '刷新' }}
                  </button>
                  <button class="dg-btn dg-btn--ghost dg-btn--sm" @click="showNoKeyPanel = false">关闭</button>
                </div>
                <p v-if="noKeyError" class="dg-nokey-error">{{ noKeyError }}</p>
                <p v-else-if="noKeyLoading" class="dg-nokey-empty">加载中…</p>
                <p v-else-if="noKeyData && noKeyData.count === 0" class="dg-nokey-empty">
                  当前账户视角下没有无密钥员工。
                </p>
                <div v-else-if="noKeyData" class="dg-nokey-list">
                  <div v-for="row in noKeyData.items" :key="row.pkg_id" class="dg-nokey-row">
                    <div class="dg-nokey-row__main">
                      <span class="dg-nokey-row__name">{{ row.name }}</span>
                      <span class="dg-nokey-row__pkg">{{ row.pkg_id }}</span>
                      <span class="dg-nokey-row__provider">
                        当前 provider=<code>{{ row.current_provider }}</code> ·
                        model=<code>{{ row.current_model || '(empty)' }}</code>
                      </span>
                    </div>
                    <div class="dg-nokey-row__actions">
                      <button
                        v-if="row.suggested_action === 'align_to_auto'"
                        type="button"
                        class="dg-btn dg-btn--primary dg-btn--sm"
                        :disabled="!!noKeyBusyRow[row.pkg_id]"
                        title="把该员工 manifest 改为 provider=model_name=auto，跟随账户里任一可用密钥"
                        @click="alignSingleEmployeeToAuto(row)"
                      >
                        {{ noKeyBusyRow[row.pkg_id] ? '处理中…' : '改为自动' }}
                      </button>
                      <button
                        v-else
                        type="button"
                        class="dg-btn dg-btn--outline dg-btn--sm"
                        title="员工已是 auto 但账户里没有任一可用密钥；请去 LLM 凭据页添加"
                        @click="gotoAddKey"
                      >
                        去添加密钥
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </transition>

            <!-- ── Gap panel (Phase 3-b) ─────────────────────────────────── -->
            <transition name="dg-slide-top">
              <div v-if="showGapPanel" class="dg-gap-panel">
                <p v-if="gapFocusHint" class="dg-gap-hint">{{ gapFocusHint }}</p>
                <div class="dg-gap-summary">
                  <span class="dg-gap-pill dg-gap-pill--deployed">✓ 在岗 {{ gapSummary.deployed }}</span>
                  <span class="dg-gap-pill dg-gap-pill--missing">✗ 缺岗 {{ gapSummary.missing }}</span>
                  <span v-if="gapSummary.untracked" class="dg-gap-pill dg-gap-pill--untracked">? 游离 {{ gapSummary.untracked }}</span>
                </div>
                <div class="dg-gap-list">
                  <div
                    v-for="row in gapRows"
                    :key="row.id"
                    class="dg-gap-row"
                    :class="`dg-gap-row--${row.state}`"
                    :title="row.id"
                    @click="row.state !== 'missing' && focusEmployee(row.id)"
                  >
                    <span class="dg-gap-icon">{{ row.state === 'deployed' ? '✓' : row.state === 'missing' ? '✗' : '?' }}</span>
                    <span class="dg-gap-name">{{ row.name }}</span>
                    <span class="dg-gap-area">{{ row.area }}</span>
                  </div>
                </div>
              </div>
            </transition>

            <transition name="dg-slide-top">
              <div v-if="showRunPanel" class="dg-run-panel">
                <div class="dg-run-grid">
                  <label class="dg-run-label">
                    <span>目标员工</span>
                    <select v-model="runTargetId" class="dg-run-select">
                      <option value="">请选择</option>
                      <option v-for="e in employees" :key="`run-${e.id}`" :value="e.id">
                        {{ e.name || e.id }} ({{ e.id }})
                      </option>
                    </select>
                  </label>
                  <label class="dg-run-label">
                    <span>并发上限</span>
                    <select v-model.number="runMaxConcurrency" class="dg-run-select">
                      <option :value="1">1</option>
                      <option :value="2">2</option>
                      <option :value="3">3</option>
                      <option :value="4">4</option>
                    </select>
                  </label>
                  <label class="dg-run-label dg-run-label--wide">
                    <span>任务 brief</span>
                    <textarea
                      v-model="runTaskBrief"
                      class="dg-run-textarea"
                      rows="2"
                      placeholder="例如：整理今日发布流程并输出执行摘要"
                    />
                  </label>
                  <label class="dg-run-label dg-run-label--wide">
                    <span>input_data JSON（对象）</span>
                    <textarea
                      v-model="runInputJson"
                      class="dg-run-textarea dg-run-textarea--mono"
                      rows="3"
                      placeholder='{"date":"2026-05-07","scope":"daily"}'
                    />
                  </label>
                </div>
                <div class="dg-run-options">
                  <label class="dg-run-check">
                    <input v-model="runIncludeDependencies" type="checkbox" />
                    <span>包含依赖上游</span>
                  </label>
                  <label class="dg-run-check">
                    <input v-model="runAllowHighRisk" type="checkbox" />
                    <span>允许高风险动作真实执行（管理员确认）</span>
                  </label>
                  <button
                    type="button"
                    class="dg-btn dg-btn--dispatch"
                    :disabled="runBusy || !runTaskBrief.trim() || !runTargetId"
                    @click="startGraphRun"
                  >
                    {{ runBusy ? '运行中…' : '开始运行' }}
                  </button>
                </div>
                <p v-if="runError" class="dg-run-error">{{ runError }}</p>
                <div v-if="latestRun" class="dg-run-summary">
                  <span class="dg-run-pill">#{{ latestRun.id }}</span>
                  <span class="dg-run-pill">状态 {{ latestRun.status }}</span>
                  <span class="dg-run-pill dg-run-pill--ok">成功 {{ latestRun.success_count }}</span>
                  <span class="dg-run-pill dg-run-pill--bad">失败 {{ latestRun.failed_count }}</span>
                  <span class="dg-run-pill dg-run-pill--warn">跳过 {{ latestRun.skipped_count }}</span>
                </div>
              </div>
            </transition>

            <!-- ── 全员汇报抽屉 ───────────────────────────────────────────── -->
            <transition name="dg-slide-top">
              <div v-if="showAllHandsPanel" class="dg-allhands-panel">
                <div class="dg-allhands-head">
                  <div class="dg-allhands-head-left">
                    <h3 class="dg-allhands-title">数字管家 · 员工大会汇报</h3>
                    <p class="dg-allhands-sub">
                      每个员工自述：① 文件架构与工作逻辑 ② 最近问题与解决路径
                      ③ 联网+GitHub 调研后的自我优化（含联动其他岗位）。
                      <strong>提问后</strong>每位员工只针对你的问题作答，并由数字管家做综合答复。
                      卡片上的<strong>已汇报</strong>仅表示该员工本轮生成成功，不是待办工单。
                    </p>
                  </div>
                  <div class="dg-allhands-head-right">
                    <label class="dg-run-check">
                      <input v-model="allHandsWithResearch" type="checkbox" :disabled="allHandsBusy" />
                      <span>联网 + GitHub 调研</span>
                    </label>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost"
                      :disabled="allHandsBusy"
                      @click="runAllHands()"
                    >{{ allHandsBusy ? '汇报中…' : (allHandsReport ? '重新生成全员架构汇报' : '生成全员架构汇报') }}</button>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost"
                      @click="showAllHandsPanel = false"
                    >收起</button>
                  </div>
                </div>

                <!-- 用户提问 → 19 名员工讨论 → 综合答复 -->
                <div class="dg-allhands-ask">
                  <textarea
                    v-model="allHandsQuestion"
                    class="dg-allhands-ask__input"
                    rows="2"
                    maxlength="600"
                    :disabled="allHandsBusy"
                    placeholder="例如：有没有员工负责定时清理过期文件？数字猫窝运行情况怎么样？"
                  />
                  <div class="dg-allhands-ask__row">
                    <span class="dg-allhands-ask__hint">{{ allHandsQuestion.length }}/600</span>
                    <button
                      type="button"
                      class="dg-btn dg-btn--dispatch dg-btn--sm"
                      :disabled="allHandsBusy || !allHandsQuestion.trim()"
                      @click="askAllHandsQuestion"
                    >{{ allHandsBusy ? '员工讨论中…' : '向员工大会提问' }}</button>
                  </div>
                </div>

                <p v-if="allHandsBusy && !allHandsReport" class="dg-allhands-loading">
                  <span class="dg-spinner" /> 正在召集 {{ employees.filter(e => !isVirtualEmployee(e.id)).length }} 名员工，
                  后端会话 {{ allHandsSessionId ? `#${allHandsSessionId.slice(0, 8)}` : '' }} 正在执行，
                  页面将每 2 秒轮询一次结果…
                </p>
                <div v-if="allHandsBusy && allHandsProgress.total > 0" class="dg-allhands-progress">
                  <div class="dg-allhands-progress-head">
                    <span>员工完成 {{ allHandsProgress.completed }}/{{ allHandsProgress.total }}</span>
                    <span>{{ allHandsProgress.percent }}%</span>
                  </div>
                  <div class="dg-allhands-progress-track">
                    <div
                      class="dg-allhands-progress-fill"
                      :style="{ width: `${allHandsProgress.percent}%` }"
                    />
                  </div>
                  <p class="dg-allhands-progress-sub">
                    成功 {{ allHandsProgress.ok }} · 异常 {{ allHandsProgress.error }}
                    <span v-if="allHandsProgress.current_employee_id">
                      · 最近完成 {{ allHandsProgress.current_employee_name || allHandsProgress.current_employee_id }}
                    </span>
                  </p>
                </div>
                <p v-if="allHandsError" class="dg-allhands-error">{{ allHandsError }}</p>
                <div v-if="allHandsReport" class="dg-allhands-summary">
                  <span class="dg-run-pill">共 {{ allHandsReport.summary.total ?? 0 }} 人</span>
                  <span class="dg-run-pill dg-run-pill--ok">完成 {{ allHandsReport.summary.ok ?? 0 }}</span>
                  <span
                    v-if="(allHandsReport.summary.error ?? 0) > 0"
                    class="dg-run-pill dg-run-pill--bad"
                  >失败 {{ allHandsReport.summary.error ?? 0 }}</span>
                  <span class="dg-run-pill">
                    Bench: {{ allHandsReport.summary.bench_provider }}/{{ allHandsReport.summary.bench_model }}
                  </span>
                  <span v-if="allHandsReport.summary.with_research" class="dg-run-pill">已联网 + GitHub</span>
                  <span v-if="allHandsReport.summary.user_question" class="dg-run-pill dg-run-pill--ask">
                    Q&A：{{ allHandsReport.summary.user_question.slice(0, 24) }}{{ (allHandsReport.summary.user_question || '').length > 24 ? '…' : '' }}
                  </span>
                </div>

                <!-- 数字管家综合答复（仅在用户提问 + 综合阶段成功时出现） -->
                <section
                  v-if="allHandsReport && allHandsReport.synthesized_answer && allHandsReport.synthesized_answer.markdown"
                  class="dg-allhands-synth"
                >
                  <header class="dg-allhands-synth__head">
                    <span class="dg-allhands-synth__badge">数字管家综合答复</span>
                    <span class="dg-allhands-synth__model">
                      {{ allHandsReport.synthesized_answer.model || '—' }}
                    </span>
                  </header>
                  <p class="dg-allhands-synth__question">
                    问题：{{ allHandsReport.synthesized_answer.question }}
                  </p>
                  <div class="dg-allhands-md dg-allhands-md--synth">
                    <MessageBody :content="allHandsReport.synthesized_answer.markdown" />
                  </div>
                  <div
                    v-if="allHandsReport.synthesized_answer.cited_employees && allHandsReport.synthesized_answer.cited_employees.length"
                    class="dg-allhands-synth__cited"
                  >
                    <span class="dg-allhands-synth__cited-label">引用员工：</span>
                    <button
                      v-for="cid in allHandsReport.synthesized_answer.cited_employees"
                      :key="cid"
                      type="button"
                      class="dg-allhands-synth__cite"
                      @click="focusAllHandsEmployee(cid)"
                    >{{ cid }}</button>
                  </div>
                </section>
                <p
                  v-else-if="allHandsReport && allHandsReport.synthesized_answer && allHandsReport.synthesized_answer.error"
                  class="dg-allhands-synth-error"
                >
                  综合答复未生成：{{ allHandsReport.synthesized_answer.error }}
                </p>

                <section
                  v-if="allHandsReport && (allHandsMeetingMinutes?.text || allHandsMeetingMinutes?.error || allHandsMeetingMinutesEmail)"
                  class="dg-allhands-minutes"
                >
                  <header class="dg-allhands-minutes__head">
                    <span class="dg-allhands-minutes__badge">会议摘要</span>
                    <span
                      v-if="allHandsMeetingMinutes?.model"
                      class="dg-allhands-minutes__model"
                    >{{ allHandsMeetingMinutes.model }}</span>
                    <div class="dg-allhands-minutes__actions">
                      <button
                        type="button"
                        class="dg-btn dg-btn--ghost dg-btn--small"
                        :disabled="!((allHandsMeetingMinutes?.text || '').trim())"
                        @click="copyAllHandsMeetingMinutes"
                      >复制正文</button>
                      <button
                        type="button"
                        class="dg-btn dg-btn--ghost dg-btn--small"
                        :disabled="!((allHandsMeetingMinutes?.text || '').trim())"
                        @click="downloadAllHandsMeetingMinutes"
                      >下载 .txt</button>
                    </div>
                  </header>
                  <p
                    v-if="allHandsMeetingMinutesEmail?.any_delivered"
                    class="dg-allhands-minutes__mail dg-allhands-minutes__mail--ok"
                  >
                    摘要已发送至<strong>每日摘要（早报）</strong>所配置的邮箱（与 MODSTORE_DAILY_DIGEST_EMAIL 一致）。
                  </p>
                  <p
                    v-else-if="allHandsMeetingMinutesEmail && (allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__mail dg-allhands-minutes__mail--muted"
                  >
                    <template v-if="allHandsMeetingMinutesEmail.skipped_reason">
                      未发信：{{ allHandsMeetingMinutesEmail.skipped_reason }}
                    </template>
                    <template v-else>
                      邮件未成功投递（请检查 SMTP 配置或使用 POST /api/admin/email/test）。
                    </template>
                  </p>
                  <pre
                    v-if="(allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__pre"
                  >{{ allHandsMeetingMinutes?.text }}</pre>
                  <p
                    v-if="allHandsMeetingMinutes?.error && !(allHandsMeetingMinutes?.text || '').trim()"
                    class="dg-allhands-minutes__err"
                  >
                    会议摘要生成失败：{{ allHandsMeetingMinutes.error }}
                  </p>
                </section>

                <div v-if="allHandsReport" class="dg-allhands-list">
                  <article
                    v-for="row in allHandsReport.employees"
                    :key="row.employee_id"
                    class="dg-allhands-card"
                    :style="{ borderLeftColor: allHandsAreaPalette[row.area] || '#6366f1' }"
                  >
                    <header class="dg-allhands-card-head">
                      <div class="dg-allhands-card-title">
                        <span class="dg-allhands-card-name">{{ row.name }}</span>
                        <code class="dg-allhands-card-id">{{ row.employee_id }}</code>
                        <span
                          class="dg-allhands-card-status"
                          :class="row.status === 'ok' ? 'is-ok' : 'is-bad'"
                        >{{ row.status === 'ok' ? '已汇报' : (row.status === 'model_error' ? '模型异常' : (row.status === 'empty' ? '空输出' : '失败')) }}</span>
                      </div>
                      <div class="dg-allhands-card-actions">
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="focusAllHandsEmployee(row.employee_id)"
                        >定位</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="publishFollowUpToButler(row)"
                        >推给管家跟进</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          @click="toggleAllHandsRow(row.employee_id)"
                        >{{ allHandsExpanded[row.employee_id] ? '折叠' : '展开' }}</button>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small dg-btn--plain"
                          :disabled="allHandsPlainLoading[row.employee_id]"
                          @click="requestPlainLang(row)"
                        >{{ allHandsPlainOpen[row.employee_id] ? '收起说人话' : '说人话' }}</button>
                      </div>
                    </header>

                    <div class="dg-allhands-meta">
                      <span v-if="row.area" class="dg-allhands-meta-tag">{{ row.area }}</span>
                      <span class="dg-allhands-meta-tag">handlers: {{ row.manifest_signals.handlers.join(', ') || '—' }}</span>
                      <span v-if="row.manifest_signals.workflow_id > 0" class="dg-allhands-meta-tag">
                        workflow #{{ row.manifest_signals.workflow_id }}
                      </span>
                      <span v-if="row.manifest_signals.depends_on.length" class="dg-allhands-meta-tag">
                        依赖: {{ row.manifest_signals.depends_on.join(', ') }}
                      </span>
                      <span v-if="(row.duration_ms ?? 0) > 0" class="dg-allhands-meta-tag">
                        {{ formatDurationMs(row.duration_ms || 0) }} · {{ row.llm_tokens || 0 }} tok
                      </span>
                      <span v-if="row.recent_failures.length" class="dg-allhands-meta-tag dg-allhands-meta-tag--warn">
                        近 {{ row.recent_failures.length }} 条失败
                      </span>
                    </div>

                    <div v-if="allHandsPlainOpen[row.employee_id]" class="dg-allhands-plain">
                      <span v-if="allHandsPlainLoading[row.employee_id]" class="dg-allhands-plain-loading">
                        爸爸稍等，AI 正在翻译中<span class="dg-plain-dots">...</span>
                      </span>
                      <p v-else class="dg-allhands-plain-text">{{ allHandsPlainText[row.employee_id] }}</p>
                    </div>

                    <div v-if="allHandsExpanded[row.employee_id]" class="dg-allhands-body">
                      <p v-if="row.cognition_error" class="dg-allhands-cog-err">{{ row.cognition_error }}</p>
                      <details v-if="row.recent_failures.length" class="dg-allhands-details">
                        <summary>近期失败流水（{{ row.recent_failures.length }}）</summary>
                        <ul class="dg-allhands-fail-list">
                          <li v-for="f in row.recent_failures" :key="f.id" class="dg-allhands-fail-item">
                            <span class="dg-allhands-fail-time">{{ formatTime(f.created_at) }}</span>
                            <span class="dg-allhands-fail-status">{{ f.status }}</span>
                            <span v-if="f.task" class="dg-allhands-fail-task">{{ f.task }}</span>
                            <code v-if="f.error" class="dg-allhands-fail-err">{{ f.error }}</code>
                          </li>
                        </ul>
                      </details>

                      <details v-if="row.research_sources.length" class="dg-allhands-details">
                        <summary>调研参考来源（{{ row.research_sources.length }}）</summary>
                        <ul class="dg-allhands-source-list">
                          <li v-for="(s, idx) in row.research_sources" :key="`src-${idx}`">
                            <a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title || s.url }}</a>
                            <span v-else>{{ s.title }}</span>
                          </li>
                        </ul>
                      </details>

                      <p v-if="row.warnings.length" class="dg-allhands-warns">
                        <strong>调研提示：</strong>{{ row.warnings.join('；') }}
                      </p>

                      <div v-if="row.report_markdown" class="dg-allhands-md dg-allhands-md--card">
                        <MessageBody :content="row.report_markdown" />
                      </div>
                      <p v-else class="dg-allhands-empty">（员工未输出 Markdown）</p>
                    </div>
                  </article>
                </div>
              </div>
            </transition>

            <SelfEvolutionLoopRuntimePanel
              v-if="viewMode === 'loop'"
              class="dg-loop-runtime-panel"
              surface="duty-roster"
            />

            <!-- ── Empty state ───────────────────────────────────────────── -->
            <div v-else-if="!loading && employees.length === 0" class="dg-empty">
              <p>暂无在岗员工包。<br />请先在工作台生成并发布员工包。</p>
            </div>

            <!-- ── Flow + detail ─────────────────────────────────────────── -->
            <div v-else class="dg-flow-wrap">
              <VueFlow
                id="admin-duty-graph"
                :nodes="flowNodes"
                :edges="flowEdges"
                :nodes-connectable="false"
                :elements-selectable="true"
                fit-view-on-init
                class="dg-flow"
                style="width: 100%; height: 100%;"
                @node-click="onNodeClick"
              >
                <Background :pattern-color="flowBgPatternColor" :gap="24" />
                <Controls position="bottom-left" />
                <MiniMap position="bottom-right" :mask-color="miniMapMaskColor" />

                <!-- 六部门 / 物理分区：父级 group 容器 -->
                <template #node-group="{ label }">
                  <div class="dg-group-node">
                    <span class="dg-group-node__label">{{ label }}</span>
                  </div>
                </template>

                <!-- Custom node: health dot -->
                <template #node-default="{ data, label }">
                  <div class="dg-node-inner" :class="{ 'dg-node-inner--workshop': data?.isWorkshop, 'dg-node-inner--loop': nodeLoopActive(data) }">
                    <span class="dg-node-label">{{ label }}</span>
                    <span v-if="data?.isWorkshop" class="dg-node-workshop-kind">
                      {{ data.workshop?.kind === 'gear' ? '档位' : '页面' }}
                    </span>
                    <span v-if="!data?.isWorkshop" class="dg-node-dots">
                      <!-- Health dot -->
                      <span
                        v-if="data?.healthLevel && data.healthLevel !== 'unknown'"
                        class="dg-node-dot"
                        :style="{ background: data.healthColor }"
                        :title="HEALTH_LABEL[data.healthLevel as HealthLv]"
                      />
                      <!-- LLM activation dot (Phase 4) -->
                      <span
                        v-if="data?.llmActLevel && data.llmActLevel !== 'unknown'"
                        class="dg-node-dot dg-node-dot--llm"
                        :style="{ background: data.llmActColor }"
                        :title="LLM_ACT_LABEL[data.llmActLevel as LlmActLv]"
                      />
                      <!-- Capability dot -->
                      <span
                        v-if="data?.capLevel && data.capLevel !== 'unknown'"
                        class="dg-node-dot dg-node-dot--cap"
                        :style="{ background: data.capColor }"
                        :title="data.capLevel === 'executable' ? '可执行' : '不可执行'"
                      />
                      <!-- Graph-run dot -->
                      <span
                        v-if="data?.runStatus && data.runStatus !== 'idle'"
                        class="dg-node-dot dg-node-dot--run"
                        :style="{ background: data.runStatusColor }"
                        :title="RUN_STATUS_LABEL[data.runStatus as RunNodeStatus]"
                      />
                      <!-- Self-evolution loop participation dot -->
                      <span
                        v-if="nodeLoopActive(data)"
                        class="dg-node-dot dg-node-dot--loop"
                        title="正在参与自进化 Loop"
                      />
                    </span>
                  </div>
                </template>
              </VueFlow>

              <!-- ── 客户端车间详情（仅管理端） ───────────────────────────── -->
              <transition name="dg-slide">
                <div v-if="selectedWorkshop && viewMode === 'client'" class="dg-detail dg-detail--workshop">
                  <div class="dg-detail-header">
                    <h3 class="dg-detail-name">{{ selectedWorkshop.label }}</h3>
                    <span
                      class="dg-workshop-status"
                      :class="selectedWorkshop.enabled ? 'dg-workshop-status--on' : 'dg-workshop-status--off'"
                    >
                      {{ selectedWorkshop.enabled ? '已启用' : '已停用' }}
                    </span>
                  </div>
                  <p class="dg-detail-id">{{ selectedWorkshop.id }}</p>
                  <p v-if="selectedWorkshop.description" class="dg-detail-meta">{{ selectedWorkshop.description }}</p>
                  <p class="dg-detail-meta">
                    类型：{{ selectedWorkshop.kind === 'gear' ? '档位车间' : '功能页车间' }}
                  </p>
                  <p v-if="selectedWorkshop.tags?.length" class="dg-detail-meta">
                    标签：{{ selectedWorkshop.tags.join(' · ') }}
                  </p>
                  <p v-if="selectedWorkshop.linkedAreaId" class="dg-detail-meta">
                    关联编制区：{{ YUANGON_AREAS[selectedWorkshop.linkedAreaId]?.label || selectedWorkshop.linkedAreaId }}
                  </p>

                  <div v-if="selectedWorkshopLinkedEmployees.length" class="dg-workshop-linked">
                    <p class="dg-workshop-linked__title">关联在岗员工</p>
                    <ul class="dg-workshop-linked__list">
                      <li v-for="emp in selectedWorkshopLinkedEmployees" :key="emp.id">
                        <button type="button" class="dg-workshop-linked__btn" @click="focusEmployeeFromWorkshop(emp.id)">
                          {{ emp.name || emp.id }}
                        </button>
                      </li>
                    </ul>
                    <p class="dg-workshop-linked__hint">点击员工将切换到「中心图」并定位节点。</p>
                  </div>

                  <div class="dg-workshop-actions">
                    <button
                      type="button"
                      class="dg-btn dg-btn--primary dg-btn--block"
                      :disabled="!selectedWorkshopRouteHref"
                      @click="openSelectedWorkshopInClient"
                    >
                      在浏览器打开客户端
                    </button>
                    <button
                      type="button"
                      class="dg-btn dg-btn--ghost dg-btn--block"
                      :disabled="!selectedWorkshopRouteHref"
                      @click="copySelectedWorkshopRoute"
                    >
                      {{ workshopRouteCopied ? '已复制路径' : '复制客户端路径' }}
                    </button>
                  </div>
                  <p v-if="selectedWorkshopRouteHref" class="dg-workshop-route">
                    <code>{{ selectedWorkshopRouteHref }}</code>
                  </p>
                  <button type="button" class="dg-btn dg-btn--ghost dg-btn--sm" @click="selectedWorkshop = null">关闭</button>
                </div>
              </transition>

              <!-- ── Detail sidebar ──────────────────────────────────────── -->
              <transition name="dg-slide">
                <div v-if="selectedEmp && viewMode !== 'client'" class="dg-detail">
                  <div class="dg-detail-header">
                    <span class="dg-detail-dot" :style="{ background: HEALTH_COLOR[healthLevel(selectedEmp.id)] }" />
                    <h3 class="dg-detail-name">{{ selectedEmp.name || selectedEmp.id }}</h3>
                  </div>
                  <p class="dg-detail-id">{{ selectedEmp.id }}</p>
                  <p v-if="selectedEmp.industry" class="dg-detail-meta">行业：{{ selectedEmp.industry }}</p>

                  <p class="dg-detail-badge" :class="selectedEmp.source === 'v1_catalog' ? 'dg-badge--warn' : 'dg-badge--ok'">
                    {{ selectedEmp.source === 'v1_catalog' ? '⚠ 仅目录' : '✓ 已登记' }}
                  </p>

                  <div v-if="selectedLoopContext" class="dg-detail-loop-context" :class="`dg-detail-loop-context--${selectedLoopContext.tone}`">
                    <span>Loop 状态</span>
                    <strong>{{ selectedLoopContext.title }}</strong>
                    <p>{{ selectedLoopContext.detail }}</p>
                    <div class="dg-detail-loop-context-actions">
                      <button type="button" @click="viewMode = 'loop'">完整 Loop</button>
                      <router-link :to="employeeSpaceLocation(selectedEmp.id)">员工空间</router-link>
                    </div>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('health')">
                    <span>健康状态</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('health') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('health')">
                    <div v-if="selectedHealth" class="dg-detail-health">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">状态</span>
                        <span class="dg-hval" :style="{ color: HEALTH_COLOR[healthLevel(selectedEmp.id)] }">
                          {{ HEALTH_LABEL[healthLevel(selectedEmp.id)] }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">执行次数</span>
                        <span class="dg-hval">{{ selectedHealth.total }}</span>
                      </div>
                      <div v-if="selectedHealth.total > 0" class="dg-hrow">
                        <span class="dg-hlabel">成功率</span>
                        <span class="dg-hval">{{ formatRate(selectedHealth.rate) }}</span>
                      </div>
                      <div v-if="selectedHealth.lastExecution" class="dg-hrow">
                        <span class="dg-hlabel">最后执行</span>
                        <span class="dg-hval dg-hval--sm">{{ formatTime(selectedHealth.lastExecution) }}</span>
                      </div>
                    </div>
                    <p v-else-if="loadingP2" class="dg-detail-loading">拉取状态中…</p>
                  </div>

                  <button v-if="selectedLoopParticipant" class="dg-section-toggle" @click="toggleDetail('selfloop')">
                    <span>本轮自进化 Loop</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('selfloop') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="selectedLoopParticipant && isDetailOpen('selfloop')" class="dg-detail-selfloop">
                    <div class="dg-hrow">
                      <span class="dg-hlabel">角色</span>
                      <span class="dg-hval">{{ selectedLoopParticipant.role_label || selectedLoopParticipant.role || '员工' }}</span>
                    </div>
                    <div class="dg-hrow">
                      <span class="dg-hlabel">阶段</span>
                      <span class="dg-hval dg-hval--sm">{{ loopParticipantList(selectedLoopParticipant, 'stage_labels') }}</span>
                    </div>
                    <div class="dg-hrow">
                      <span class="dg-hlabel">Run ID</span>
                      <span class="dg-hval dg-hval--sm">{{ loopParticipantList(selectedLoopParticipant, 'run_ids') }}</span>
                    </div>
                    <div class="dg-hrow">
                      <span class="dg-hlabel">来源</span>
                      <span class="dg-hval dg-hval--sm">{{ loopParticipantList(selectedLoopParticipant, 'sources') }}</span>
                    </div>
                    <div v-if="selectedLoopParticipant.latest_at" class="dg-hrow">
                      <span class="dg-hlabel">最近回写</span>
                      <span class="dg-hval dg-hval--sm">{{ formatTime(selectedLoopParticipant.latest_at) }}</span>
                    </div>
                    <div v-if="selectedLoopTimelineSummary" class="dg-hrow">
                      <span class="dg-hlabel">时间线</span>
                      <span class="dg-hval dg-hval--sm">
                        {{ selectedLoopTimelineSummary.count }} 步
                        <template v-if="selectedLoopTimelineSummary.lastLabel">
                          · 最后 {{ selectedLoopTimelineSummary.lastLabel }}
                        </template>
                        <template v-if="selectedLoopTimelineSummary.lastStatus">
                          · {{ selectedLoopTimelineSummary.lastStatus }}
                        </template>
                      </span>
                    </div>
                    <button
                      type="button"
                      class="dg-btn dg-btn--outline dg-btn--full"
                      @click="viewMode = 'loop'"
                    >
                      查看完整 Loop 时间线 →
                    </button>
                    <router-link
                      :to="employeeSpaceLocation(selectedEmp.id)"
                      class="dg-btn dg-btn--ghost dg-btn--full dg-selfloop-workspace-link"
                    >
                      回员工空间看工位现场 →
                    </router-link>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('exec')">
                    <span>最近执行</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('exec') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('exec')" class="dg-detail-exec">
                    <p v-if="execLoading" class="dg-detail-loading">加载执行记录…</p>
                    <p v-else-if="execError" class="dg-exec-err">{{ execError }}</p>
                    <template v-else>
                      <p v-if="!execItems.length" class="dg-exec-empty">暂无执行记录</p>
                      <ul v-else class="dg-exec-list">
                        <li v-for="row in execItems" :key="row.id" class="dg-exec-item">
                          <div class="dg-exec-item-meta">
                            <span class="dg-exec-time">{{ formatTime(row.created_at) }}</span>
                            <span>{{ formatDurationMs(row.duration_ms) }}</span>
                            <span
                              class="dg-exec-status"
                              :class="row.status === 'success' ? 'dg-exec-status--ok' : 'dg-exec-status--bad'"
                            >{{ row.status || '—' }}</span>
                            <span class="dg-exec-num">uid {{ row.user_id }}</span>
                            <span v-if="row.llm_tokens" class="dg-exec-num">{{ row.llm_tokens }} tok</span>
                          </div>
                          <p class="dg-exec-task" :title="row.task">{{ row.task || '（无摘要）' }}</p>
                          <p v-if="row.error" class="dg-exec-err-line" :title="row.error">{{ row.error }}</p>
                        </li>
                      </ul>
                      <div v-if="execItems.length" class="dg-exec-footer">
                        <span class="dg-exec-count">共 {{ execTotal }} 条 · 已显示 {{ execItems.length }}</span>
                        <button
                          type="button"
                          class="dg-btn dg-btn--ghost dg-btn--small"
                          :disabled="execLoadingMore || execItems.length >= execTotal"
                          @click="fetchExecMetrics(true)"
                        >
                          {{ execLoadingMore ? '加载中…' : '加载更多' }}
                        </button>
                      </div>
                    </template>
                  </div>

                  <button v-if="selectedDeps.length" class="dg-section-toggle" @click="toggleDetail('deps')">
                    <span>依赖员工 ({{ selectedDeps.length }})</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('deps') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="selectedDeps.length && isDetailOpen('deps')" class="dg-detail-deps">
                    <ul class="dg-deps-list">
                      <li v-for="dep in selectedDeps" :key="dep" class="dg-deps-item" :title="dep">{{ dep }}</li>
                    </ul>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('skills')">
                    <span>能做什么 · 怎么做</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('skills') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('skills')">
                    <div v-if="selectedCapabilityView" class="dg-detail-skills">
                      <p v-if="isSelectedVirtual" class="dg-skills-virtual-hint">
                        数字管家：浏览器内常驻智能体，不写入 employee_execution_metrics。
                      </p>
                      <p v-if="selectedCapabilityView.persona" class="dg-skills-persona">
                        {{ selectedCapabilityView.persona }}
                      </p>
                      <div v-if="selectedCapabilityView.expertise.length" class="dg-skills-expertise">
                        <span
                          v-for="tag in selectedCapabilityView.expertise"
                          :key="`exp-${tag}`"
                          class="dg-skills-tag"
                        >{{ tag }}</span>
                      </div>
                      <ul v-if="selectedCapabilityView.skills.length" class="dg-skills-list">
                        <li
                          v-for="(s, i) in selectedCapabilityView.skills"
                          :key="`sk-${i}-${s.name}`"
                          class="dg-skill-row"
                        >
                          <div class="dg-skill-head">
                            <span class="dg-skill-name">{{ s.name }}</span>
                            <span v-if="s.kind" class="dg-skill-kind">{{ s.kind }}</span>
                          </div>
                          <p v-if="s.brief" class="dg-skill-brief">{{ s.brief }}</p>
                          <p v-if="s.how" class="dg-skill-how">
                            <span class="dg-skill-how-label">怎么做</span>
                            <code>{{ s.how }}</code>
                          </p>
                        </li>
                      </ul>
                      <p v-else class="dg-skills-empty">
                        该员工 manifest.cognition.skills 为空；下面的执行通道是它实际可用的能力。
                      </p>
                      <div v-if="selectedCapabilityView.handlers.length" class="dg-skills-handlers">
                        <p class="dg-skills-subtitle">执行通道（actions.handlers）</p>
                        <ul class="dg-handler-list">
                          <li
                            v-for="h in selectedCapabilityView.handlers"
                            :key="`h-${h}`"
                            class="dg-handler-row"
                          >
                            <code class="dg-handler-name">{{ h }}</code>
                            <span class="dg-handler-desc">{{ describeHandler(h) }}</span>
                          </li>
                        </ul>
                      </div>
                      <p v-if="selectedCapabilityView.workflowId > 0" class="dg-skills-workflow">
                        关联工作流：
                        <router-link
                          :to="{ name: 'workflow' }"
                          class="dg-skills-workflow-link"
                        >#{{ selectedCapabilityView.workflowId }}</router-link>
                      </p>
                    </div>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('llm')">
                    <span>LLM 接入状态</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('llm') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('llm')">
                    <div v-if="selectedLlm" class="dg-detail-llm">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">供应商</span>
                        <span class="dg-hval">
                          {{
                            selectedLlm.provider === 'auto'
                              ? '自动（运行时解析）'
                              : llmStatusMap[selectedLlm.provider]?.label || selectedLlm.provider
                          }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">模型</span>
                        <span class="dg-hval dg-hval--sm">{{
                          selectedLlm.model === 'auto' ? '自动' : selectedLlm.model
                        }}</span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">需要 LLM</span>
                        <span class="dg-hval" :style="{ color: selectedLlm.needsLlm ? '#e0e0e0' : '#6b7280' }">
                          {{ selectedLlm.needsLlm ? '是' : '否（echo only）' }}
                        </span>
                      </div>
                      <div v-if="selectedLlm.needsLlm" class="dg-hrow">
                        <span class="dg-hlabel">密钥来源</span>
                        <span
                          class="dg-hval"
                          :style="{
                            color: selectedLlm.keySource === 'none' ? '#ef4444'
                                 : selectedLlm.keySource === 'byok' ? '#818cf8'
                                 : selectedLlm.keySource === 'auto' ? '#4ade80' : '#4ade80'
                          }"
                        >
                          {{
                            selectedLlm.keySource === 'none'
                              ? '✗ 未配置'
                              : selectedLlm.keySource === 'byok'
                                ? '⚡ BYOK'
                                : selectedLlm.keySource === 'auto'
                                  ? '⚡ 自动（账户内已有可用密钥）'
                                  : '⚡ 平台密钥'
                          }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">Handlers</span>
                        <span class="dg-hval dg-hval--sm">{{ selectedLlm.handlers.join(', ') || '—' }}</span>
                      </div>
                      <router-link
                        v-if="selectedLlm.needsLlm && selectedLlm.keySource === 'none'"
                        :to="{ name: 'account', hash: '#api-keys' }"
                        class="dg-llm-fix"
                        @click="onAccountKeysNav"
                      >→ 去账户页配置密钥</router-link>
                    </div>
                    <p v-else-if="loadingP2" class="dg-detail-loading">LLM 状态加载中…</p>
                  </div>

                  <button class="dg-section-toggle" @click="toggleDetail('cap')">
                    <span>执行能力</span>
                    <span class="dg-section-toggle-icon">{{ isDetailOpen('cap') ? '▴' : '▾' }}</span>
                  </button>
                  <div v-if="isDetailOpen('cap')">
                    <div v-if="selectedCapability" class="dg-detail-capability">
                      <div class="dg-hrow">
                        <span class="dg-hlabel">状态</span>
                        <span class="dg-hval" :style="{ color: selectedCapability.executable ? '#22c55e' : '#ef4444' }">
                          {{ selectedCapability.executable ? '可执行' : '不可执行' }}
                        </span>
                      </div>
                      <div class="dg-hrow">
                        <span class="dg-hlabel">Handlers</span>
                        <span class="dg-hval dg-hval--sm">{{ selectedCapability.handlers.join(', ') || '—' }}</span>
                      </div>
                      <p v-if="selectedCapability.reasons.length" class="dg-cap-reasons">
                        {{ selectedCapability.reasons.join('；') }}
                      </p>
                      <div v-if="selectedCapability.risk.high_risk" class="dg-cap-risk">
                        <p class="dg-cap-risk-title">高风险动作（需二次确认）</p>
                        <ul class="dg-cap-risk-list">
                          <li
                            v-for="d in selectedCapability.risk.details"
                            :key="`${d.handler}-${d.command_id || ''}-${d.reason || ''}`"
                          >
                            <code>{{ d.handler }}</code>
                            <span v-if="d.command_id"> · {{ d.command_id }}</span>
                            <span v-if="d.requires_approval"> · approval</span>
                          </li>
                        </ul>
                      </div>
                      <router-link
                        v-if="selectedCapability.recent_ops_audits.length"
                        :to="{ name: 'admin-ops-audit', query: { employee_id: selectedEmp!.id } }"
                        class="dg-cap-link"
                      >查看运维审计 →</router-link>
                    </div>
                    <p v-else-if="capLoading" class="dg-detail-loading">执行能力加载中…</p>
                  </div>

                  <div v-if="selectedRunNode" class="dg-detail-run-node">
                    <p class="dg-cap-title">本次图运行</p>
                    <div class="dg-hrow">
                      <span class="dg-hlabel">节点状态</span>
                      <span class="dg-hval" :style="{ color: RUN_STATUS_COLOR[selectedRunNode.status] }">
                        {{ RUN_STATUS_LABEL[selectedRunNode.status] }}
                      </span>
                    </div>
                    <div v-if="selectedRunNode.duration_ms > 0" class="dg-hrow">
                      <span class="dg-hlabel">耗时</span>
                      <span class="dg-hval">{{ formatDurationMs(selectedRunNode.duration_ms) }}</span>
                    </div>
                    <p v-if="selectedRunNode.error" class="dg-cap-reasons">{{ selectedRunNode.error }}</p>
                  </div>

                  <!-- Actions -->
                  <button class="dg-btn dg-btn--primary" @click="goUse(selectedEmp!)">
                    {{ isSelectedVirtual ? '去管家技能管理 →' : '去工作台使用 →' }}
                  </button>

                  <!-- Phase 3-c: task dispatch -->
                  <button class="dg-btn dg-btn--outline dg-btn--full" @click="showDispatch = !showDispatch">
                    {{ showDispatch ? '收起派发' : '派发任务 ▾' }}
                  </button>
                  <transition name="dg-fade">
                    <div v-if="showDispatch" class="dg-dispatch">
                      <textarea
                        v-model="taskBrief"
                        class="dg-dispatch-input"
                        placeholder="输入任务描述（brief）…"
                        rows="3"
                      />
                      <textarea
                        v-model="taskInputJson"
                        class="dg-dispatch-input dg-dispatch-input--mono"
                        placeholder='input_data JSON（对象），默认 {}'
                        rows="3"
                      />
                      <p v-if="selectedCapability?.handlers?.length" class="dg-dispatch-hint">
                        将触发 handlers：{{ selectedCapability.handlers.join(', ') }}
                      </p>
                      <label
                        v-if="selectedCapability?.risk?.high_risk"
                        class="dg-dispatch-confirm"
                      >
                        <input v-model="dispatchConfirmHighRisk" type="checkbox" />
                        <span>包含高风险动作，我已确认本次真实执行</span>
                      </label>
                      <div class="dg-dispatch-actions">
                        <button
                          class="dg-btn dg-btn--dispatch"
                          :disabled="taskRunning || !taskBrief.trim()"
                          @click="dispatchTask"
                        >
                          {{ taskRunning ? '执行中…' : '派发执行' }}
                        </button>
                        <button
                          class="dg-btn dg-btn--outline dg-btn--dispatch-secondary"
                          :disabled="taskRunning || !taskBrief.trim()"
                          @click="publishTaskToButler"
                        >
                          发布给管家
                        </button>
                      </div>
                      <div v-if="taskError" class="dg-dispatch-err">{{ taskError }}</div>
                      <pre v-if="taskResult" class="dg-dispatch-result">{{ taskResult }}</pre>
                    </div>
                  </transition>

                  <button class="dg-btn dg-btn--ghost" style="margin-top:4px" @click="selectedEmp = null">收起</button>
                </div>
              </transition>
            </div>

            <!-- Loading overlay (inside body — must not cover dg-header-actions) -->
            <div v-if="loading" class="dg-loading">
              <span class="dg-spinner" />
              正在拉取在岗员工列表…
            </div>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.dg-loop-command-strip,
.dg-loop-command-strip > * {
  --loop-compact-card-min: 145px;
  --loop-detail-card-min: 220px;
  min-width: 0;
}

.dg-loop-governance-map {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 8px;
  align-items: stretch;
  min-width: 0;
  overflow: hidden;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 16px;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 30%),
    radial-gradient(circle at 100% 0%, rgba(59, 130, 246, 0.1), transparent 28%),
    rgba(15, 23, 42, 0.28);
}

.dg-loop-governance-map-node {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 13px;
  background: rgba(15, 23, 42, 0.36);
}

.dg-loop-governance-map-node--center {
  border-color: rgba(20, 184, 166, 0.32);
  background: rgba(15, 118, 110, 0.22);
}

.dg-loop-governance-map-node--source {
  border-color: rgba(59, 130, 246, 0.22);
  background: rgba(30, 64, 175, 0.18);
}

.dg-loop-governance-map-node--target {
  border-color: rgba(99, 102, 241, 0.24);
  background: rgba(49, 46, 129, 0.2);
}

.dg-loop-governance-map-node--route {
  border-color: rgba(34, 211, 238, 0.58);
  box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.18), 0 18px 44px rgba(34, 211, 238, 0.12);
}

.dg-loop-governance-map-node span,
.dg-loop-governance-map-node strong,
.dg-loop-governance-map-node small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-map-node span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-map-node strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 14px;
  font-weight: 950;
}

.dg-loop-governance-map-node small {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.78);
  font-size: 11px;
  line-height: 1.35;
}

.dg-loop-governance-map-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  color: rgba(226, 232, 240, 0.7);
  font-size: 18px;
  font-weight: 950;
}

.dg-loop-governance-directive {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(0, 0.7fr) max-content;
  gap: 10px;
  align-items: center;
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 12px;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 16px;
  background:
    radial-gradient(circle at 0% 0%, rgba(34, 211, 238, 0.2), transparent 30%),
    linear-gradient(135deg, rgba(15, 23, 42, 0.72), rgba(30, 41, 59, 0.6));
  box-shadow: 0 18px 44px rgba(2, 6, 23, 0.18);
}

.dg-loop-governance-directive--ok {
  border-color: rgba(34, 197, 94, 0.24);
  background:
    radial-gradient(circle at 0% 0%, rgba(34, 197, 94, 0.16), transparent 30%),
    linear-gradient(135deg, rgba(20, 83, 45, 0.56), rgba(15, 23, 42, 0.56));
}

.dg-loop-governance-directive--warn {
  border-color: rgba(251, 191, 36, 0.28);
  background:
    radial-gradient(circle at 0% 0%, rgba(251, 191, 36, 0.16), transparent 30%),
    linear-gradient(135deg, rgba(120, 53, 15, 0.58), rgba(15, 23, 42, 0.56));
}

.dg-loop-governance-directive--bad {
  border-color: rgba(248, 113, 113, 0.3);
  background:
    radial-gradient(circle at 0% 0%, rgba(248, 113, 113, 0.18), transparent 30%),
    linear-gradient(135deg, rgba(127, 29, 29, 0.62), rgba(15, 23, 42, 0.58));
}

.dg-loop-governance-directive-copy,
.dg-loop-governance-directive-meta {
  min-width: 0;
}

.dg-loop-governance-directive-copy span,
.dg-loop-governance-directive-meta span {
  display: block;
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-directive-copy strong,
.dg-loop-governance-directive-meta strong {
  display: block;
  margin-top: 4px;
  color: #f8fafc;
  font-size: 15px;
  font-weight: 950;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-directive-copy small,
.dg-loop-governance-directive-meta small {
  display: block;
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.78);
  font-size: 11px;
  font-weight: 800;
  line-height: 1.45;
}

.dg-loop-governance-directive-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: end;
  min-width: 0;
  max-width: 100%;
  min-height: 32px;
  padding: 9px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  color: #f8fafc;
  font-size: 12px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-directive-link:hover {
  background: rgba(255, 255, 255, 0.18);
}

.dg-loop-section-head {
  display: grid;
  grid-template-columns: minmax(0, 0.32fr) minmax(0, 0.68fr);
  gap: 6px 10px;
  align-items: baseline;
  min-width: 0;
  padding: 2px 2px 0;
}

.dg-loop-section-head span,
.dg-loop-section-head strong,
.dg-loop-section-head small {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-section-head span {
  color: rgba(45, 212, 191, 0.86);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-section-head strong {
  color: #f8fafc;
  font-size: 13px;
  font-weight: 950;
}

.dg-loop-section-head small {
  grid-column: 1 / -1;
  color: rgba(226, 232, 240, 0.72);
  font-size: 11px;
  font-weight: 800;
  white-space: normal;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.dg-loop-section-legend {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.dg-loop-section-dot {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  padding: 3px 7px;
  border-radius: 999px;
  color: rgba(203, 213, 225, 0.78);
  font-size: 10px;
  font-weight: 950;
  line-height: 1;
  white-space: nowrap;
}

.dg-loop-section-dot::before {
  width: 6px;
  height: 6px;
  margin-right: 5px;
  border-radius: 999px;
  background: currentColor;
  content: '';
}

.dg-loop-section-dot--ok {
  background: rgba(34, 197, 94, 0.12);
  color: rgba(134, 239, 172, 0.92);
}

.dg-loop-section-dot--bad {
  background: rgba(239, 68, 68, 0.14);
  color: rgba(252, 165, 165, 0.92);
}

.dg-loop-section-dot--warn {
  background: rgba(245, 158, 11, 0.14);
  color: rgba(253, 230, 138, 0.92);
}

.dg-loop-surface-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  min-width: 0;
}

.dg-loop-surface-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 11px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.34);
  isolation: isolate;
}

.dg-loop-surface-card--ok {
  border-color: rgba(34, 197, 94, 0.22);
  background: rgba(20, 83, 45, 0.22);
}

.dg-loop-surface-card--warn {
  border-color: rgba(245, 158, 11, 0.26);
  background: rgba(120, 53, 15, 0.24);
}

.dg-loop-surface-card--bad {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(127, 29, 29, 0.28);
}

.dg-loop-surface-card span,
.dg-loop-surface-card strong,
.dg-loop-surface-card small,
.dg-loop-surface-card em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-surface-card span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-surface-card strong {
  margin-top: 4px;
  color: #f8fafc;
  font-size: 16px;
  font-weight: 950;
}

.dg-loop-surface-card small,
.dg-loop-surface-card em {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.78);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
}

.dg-loop-surface-card a,
.dg-loop-surface-wait {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 8px;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(45, 212, 191, 0.12);
  color: rgba(153, 246, 228, 0.94);
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-surface-card a:hover {
  background: rgba(45, 212, 191, 0.18);
}

.dg-loop-surface-route-note {
  color: rgba(148, 163, 184, 0.78);
}

.dg-loop-surface-source-note {
  color: rgba(148, 163, 184, 0.78);
  font-size: 10px;
}

.dg-loop-surface-wait {
  background: rgba(148, 163, 184, 0.12);
  color: rgba(203, 213, 225, 0.72);
  cursor: default;
}

.dg-loop-surface-card a:focus-visible,
.dg-loop-governance-directive-link:focus-visible,
.dg-loop-governance-truth-card a:focus-visible,
.dg-loop-governance-incident a:focus-visible {
  outline: 2px solid rgba(45, 212, 191, 0.74);
  outline-offset: 2px;
}

.dg-loop-governance-directive-copy small,
.dg-loop-surface-card em {
  display: -webkit-box;
  overflow: hidden;
  white-space: normal;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.dg-loop-governance-truth {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  gap: 8px;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.22);
}

.dg-loop-governance-truth-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 13px;
  background: rgba(15, 23, 42, 0.34);
}

.dg-loop-governance-truth-card span,
.dg-loop-governance-truth-card strong,
.dg-loop-governance-truth-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-truth-card span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-truth-card strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 14px;
  font-weight: 950;
}

.dg-loop-governance-truth-card small {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.76);
  font-size: 11px;
  line-height: 1.35;
}

.dg-loop-governance-truth-card a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(20, 184, 166, 0.92);
  color: #042f2e;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-truth-card--ok {
  border-color: rgba(34, 197, 94, 0.2);
}

.dg-loop-governance-truth-card--bad {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(127, 29, 29, 0.24);
}

.dg-loop-governance-truth-card--warn {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(120, 53, 15, 0.22);
}

.dg-loop-governance-truth-card--primary {
  grid-column: span 2;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 34%),
    rgba(15, 23, 42, 0.38);
}

.dg-loop-governance-incidents {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-detail-card-min), 1fr));
  gap: 8px;
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(239, 68, 68, 0.18);
  border-radius: 16px;
  background: rgba(127, 29, 29, 0.14);
}

.dg-loop-governance-incident {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(239, 68, 68, 0.28);
  border-radius: 13px;
  background: rgba(127, 29, 29, 0.22);
}

.dg-loop-governance-incident--warn {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(120, 53, 15, 0.22);
}

.dg-loop-governance-incident span,
.dg-loop-governance-incident strong,
.dg-loop-governance-incident small,
.dg-loop-governance-incident em {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-incident span {
  color: rgba(254, 202, 202, 0.86);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-incident strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 14px;
  font-weight: 950;
}

.dg-loop-governance-incident small,
.dg-loop-governance-incident em {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.76);
  font-size: 11px;
  font-style: normal;
  line-height: 1.35;
}

.dg-loop-governance-incident a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: fit-content;
  max-width: 100%;
  min-height: 28px;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: rgba(20, 184, 166, 0.92);
  color: #042f2e;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-freshness {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(var(--loop-compact-card-min), 1fr));
  min-width: 0;
  gap: 8px;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.18);
}

.dg-loop-governance-freshness-card {
  min-width: 0;
  overflow: hidden;
  contain: layout paint;
  padding: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 13px;
  background: rgba(15, 23, 42, 0.34);
}

.dg-loop-governance-freshness-card span,
.dg-loop-governance-freshness-card strong,
.dg-loop-governance-freshness-card small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-freshness-card span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-freshness-card strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 13px;
  font-weight: 950;
}

.dg-loop-governance-freshness-card small {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.76);
  font-size: 11px;
  line-height: 1.35;
}

.dg-loop-governance-freshness-card--run {
  border-color: rgba(14, 165, 233, 0.24);
}

.dg-loop-governance-freshness-card--ok {
  border-color: rgba(34, 197, 94, 0.2);
}

.dg-loop-governance-freshness-card--warn {
  border-color: rgba(245, 158, 11, 0.24);
  background: rgba(120, 53, 15, 0.22);
}

.dg-loop-governance-checklist {
  display: grid;
  grid-template-columns: minmax(220px, 1.2fr) repeat(4, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.22);
}

.dg-loop-governance-checklist-head,
.dg-loop-governance-check {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 13px;
  background: rgba(15, 23, 42, 0.34);
}

.dg-loop-governance-checklist-head span,
.dg-loop-governance-checklist-head strong,
.dg-loop-governance-checklist-head small,
.dg-loop-governance-check span,
.dg-loop-governance-check strong,
.dg-loop-governance-check small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-checklist-head span,
.dg-loop-governance-check span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-checklist-head strong,
.dg-loop-governance-check strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 13px;
  font-weight: 950;
}

.dg-loop-governance-checklist-head small,
.dg-loop-governance-check small {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.76);
  font-size: 11px;
  line-height: 1.35;
}

.dg-loop-governance-check {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 8px;
}

.dg-loop-governance-check--ok {
  border-color: rgba(34, 197, 94, 0.2);
}

.dg-loop-governance-check--bad {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(127, 29, 29, 0.24);
}

.dg-loop-governance-check button {
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: 999px;
  background: rgba(20, 184, 166, 0.92);
  color: #042f2e;
  font-size: 11px;
  font-weight: 950;
  cursor: pointer;
}

.dg-loop-governance-check button:disabled {
  opacity: 0.58;
  cursor: wait;
}

.dg-loop-governance-todos {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(0, 1fr));
  gap: 8px;
  align-items: stretch;
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 16px;
  background:
    radial-gradient(circle at 0% 100%, rgba(245, 158, 11, 0.12), transparent 32%),
    rgba(15, 23, 42, 0.22);
}

.dg-loop-governance-todos-head,
.dg-loop-governance-todo {
  min-width: 0;
  padding: 10px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 13px;
  background: rgba(15, 23, 42, 0.34);
}

.dg-loop-governance-todos-head span,
.dg-loop-governance-todos-head strong,
.dg-loop-governance-todos-head small,
.dg-loop-governance-todo span,
.dg-loop-governance-todo strong,
.dg-loop-governance-todo small {
  display: block;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dg-loop-governance-todos-head span,
.dg-loop-governance-todo span {
  color: rgba(203, 213, 225, 0.82);
  font-size: 10px;
  font-weight: 950;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dg-loop-governance-todos-head strong,
.dg-loop-governance-todo strong {
  margin-top: 3px;
  color: #f8fafc;
  font-size: 13px;
  font-weight: 950;
}

.dg-loop-governance-todos-head small,
.dg-loop-governance-todo small {
  margin-top: 4px;
  color: rgba(226, 232, 240, 0.76);
  font-size: 11px;
  line-height: 1.35;
}

.dg-loop-governance-todo {
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  gap: 8px;
}

.dg-loop-governance-todo--ok {
  border-color: rgba(34, 197, 94, 0.2);
}

.dg-loop-governance-todo--bad {
  border-color: rgba(239, 68, 68, 0.28);
  background: rgba(127, 29, 29, 0.24);
}

.dg-loop-governance-todo button {
  width: 100%;
  padding: 7px 9px;
  border: 0;
  border-radius: 999px;
  background: rgba(245, 158, 11, 0.94);
  color: #451a03;
  font-size: 11px;
  font-weight: 950;
  cursor: pointer;
}

.dg-loop-governance-todo button:disabled {
  opacity: 0.58;
  cursor: wait;
}

@media (max-width: 1180px) {
  .dg-loop-command-strip {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-command-main {
    min-width: 0;
  }

  .dg-loop-governance-map {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-map-arrow {
    transform: rotate(90deg);
  }

  .dg-loop-governance-directive {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-directive-link {
    justify-self: start;
  }

  .dg-loop-section-head {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-surface-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-truth-card--primary {
    grid-column: auto;
  }

  .dg-loop-governance-checklist {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-truth {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-freshness {
    grid-template-columns: minmax(0, 1fr);
  }

  .dg-loop-governance-todos {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* ─── Overlay ────────────────────────────────────────────────────────────── */
.dg-overlay {
  position: fixed; inset: 0; z-index: 500;
  background: rgba(0,0,0,0.65);
  display: flex; align-items: center; justify-content: center; padding: 16px;
}
.dg-fade-enter-active,.dg-fade-leave-active { transition: opacity 0.18s; }
.dg-fade-enter-from,.dg-fade-leave-to       { opacity: 0; }

/* ─── Panel ──────────────────────────────────────────────────────────────── */
.dg-panel {
  position: relative;
  width: min(1360px,97vw); height: min(860px,93vh);
  background: var(--dg-panel-bg, var(--color-bg-page,#0e0e1a));
  border: 1px solid var(--color-border-subtle,#333);
  border-radius: 14px;
  display: flex; flex-direction: column; overflow: hidden;
  box-shadow: var(--dg-panel-shadow, 0 24px 80px rgba(0,0,0,0.75));
}

/* 独立页面：嵌入 main，铺满路由网格单元 */
.dg-page-root {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: 100%;
}
.dg-panel--page {
  flex: 1;
  min-height: 0;
  width: 100%;
  max-width: none;
  height: auto;
  max-height: none;
  box-shadow: none;
}

/* Office 浅色主题：与 admin-console office-theme.css 对齐 */
.dg-page-root--office {
  --color-primary: var(--primary-color, #0b72d9);
  --dg-panel-bg: rgba(255, 255, 255, 0.92);
  --dg-header-bg: rgba(255, 255, 255, 0.96);
  --dg-flow-bg: var(--bg-color, #edf3fa);
  --color-bg-page: var(--bg-color, #edf3fa);
  --color-bg-body: var(--bg-color, #edf3fa);
  --color-bg-card: #ffffff;
  --color-bg-elevated: #f8fafc;
  --color-bg-base: #f1f5f9;
  --color-text-primary: var(--text-primary, #172033);
  --color-text-secondary: var(--text-secondary, #475569);
  --color-text-muted: var(--app-text-muted, #64748b);
  --color-border-subtle: rgba(213, 222, 235, 0.78);
  --dg-stat-bg: rgba(226, 232, 240, 0.65);
  --dg-stat-bg-ok: rgba(18, 138, 58, 0.12);
  --dg-stat-bg-warn: rgba(217, 119, 6, 0.12);
  --dg-stat-bg-healthy: rgba(18, 138, 58, 0.12);
  --dg-stat-bg-dep: rgba(11, 114, 217, 0.1);
  --dg-stat-bg-err: rgba(197, 48, 48, 0.1);
  --dg-btn-hover: rgba(226, 237, 250, 0.9);
  --dg-menu-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
  --dg-panel-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
}
.dg-page-root--office .dg-panel--page {
  border: 1px solid rgba(213, 222, 235, 0.78);
  border-radius: 18px;
  box-shadow: 0 18px 44px rgba(15, 23, 42, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.72);
  background: var(--dg-panel-bg);
}
.dg-page-root--office .dg-stat--ok,
.dg-page-root--office .dg-stat--healthy { color: #128a3a; }
.dg-page-root--office .dg-toggle.active { background: var(--primary-color, #0b72d9); }
.dg-page-root--office .dg-btn--primary {
  background: linear-gradient(135deg, #0b72d9 0%, #1394df 100%);
}
.dg-page-root--office .dg-detail-health,
.dg-page-root--office .dg-detail-capability,
.dg-page-root--office .dg-detail-run-node {
  background: rgba(241, 245, 249, 0.9);
  border-color: rgba(213, 222, 235, 0.78);
}
.dg-page-root--office .dg-section-toggle { background: rgba(241, 245, 249, 0.6); }
.dg-page-root--office .dg-section-toggle:hover {
  background: rgba(226, 237, 250, 0.85);
}
.dg-page-root--office :deep(.vue-flow__controls) {
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.1);
}
.dg-page-root--office :deep(.vue-flow__controls-button) {
  background: #ffffff;
  border-color: rgba(213, 222, 235, 0.78);
  fill: #475569;
}
.dg-page-root--office :deep(.vue-flow__controls-button:hover) {
  background: rgba(226, 237, 250, 0.9);
}
.dg-page-root--office :deep(.vue-flow__minimap) {
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(213, 222, 235, 0.78);
  border-radius: 8px;
}
.dg-panel--embedded {
  border-radius: 10px;
  border: 1px solid var(--color-border-subtle, #333);
}
.dg-close--text {
  font-size: 0.82rem;
  color: var(--color-text-secondary,#aaa);
}

/* ─── Header ─────────────────────────────────────────────────────────────── */
.dg-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'left right'
    'actions actions';
  align-items: center;
  padding: 11px 18px;
  border-bottom: 1px solid var(--color-border-subtle,#333);
  background: var(--dg-header-bg, var(--color-bg-page,#0e0e1a));
  flex-shrink: 0;
  gap: 10px;
  position: relative;
  z-index: 20;
  isolation: isolate;
}
.dg-header-left  { grid-area: left; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; min-width: 0; }
.dg-header-right { grid-area: right; display: flex; align-items: center; gap: 8px; flex-shrink: 1; flex-wrap: wrap; justify-self: end; min-width: 0; max-width: 100%; }
.dg-header-actions {
  grid-area: actions;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  position: relative;
  z-index: 21;
  pointer-events: auto;
}
.dg-title { font-size: 1rem; font-weight: 700; color: var(--color-text-primary,#e0e0e0); white-space: nowrap; }
.dg-roster-hint {
  margin-left: 0.65rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--color-text-muted,#9ca3af);
  letter-spacing: 0.02em;
  white-space: nowrap;
}

/* Stats pills */
.dg-stats { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; }
.dg-stat  { font-size: 0.76rem; padding: 2px 7px; border-radius: 20px; background: var(--dg-stat-bg, rgba(255,255,255,0.06)); color: var(--color-text-secondary,#aaa); white-space: nowrap; }
.dg-stat strong    { color: var(--color-text-primary,#e0e0e0); }
.dg-stat--ok       { color:#4ade80; background:var(--dg-stat-bg-ok, rgba(74,222,128,0.10)); }
.dg-stat--warn     { color:#f59e0b; background:var(--dg-stat-bg-warn, rgba(245,158,11,0.10)); }
.dg-stat--healthy  { color:#34d399; background:var(--dg-stat-bg-healthy, rgba(52,211,153,0.10)); }
.dg-stat--dep      { color:#818cf8; background:var(--dg-stat-bg-dep, rgba(129,140,248,0.10)); }
.dg-stat--llm-ok   { color:#818cf8; background:var(--dg-stat-bg-dep, rgba(129,140,248,0.10)); }
.dg-stat--llm-err  { color:#ef4444; background:var(--dg-stat-bg-err, rgba(239,68,68,0.10)); }
.dg-stat--muted    { color:var(--color-text-muted,#666); background:transparent; animation:pulse 1.4s ease infinite; }
.dg-stat--clickable { border:1px solid transparent; cursor:pointer; transition:background 0.15s, border-color 0.15s; font:inherit; }
.dg-stat--clickable:hover { background:rgba(239,68,68,0.18); }
.dg-stat--clickable.dg-stat--active { border-color:#ef4444; background:rgba(239,68,68,0.22); }
.dg-btn--sm { padding:3px 9px; font-size:0.74rem; width:auto; margin:0; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.35} }

/* Toggle group (view mode) */
.dg-toggle-group { display: flex; border: 1px solid var(--color-border-subtle,#444); border-radius: 7px; overflow: hidden; }
.dg-toggle {
  background: transparent; border: none; padding: 5px 12px;
  font-size: 0.8rem; cursor: pointer; color: var(--color-text-muted,#888); transition: background 0.15s, color 0.15s;
}
.dg-toggle.active { background: var(--color-primary,#6366f1); color: #fff; }
.dg-loop-links {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.dg-loop-link {
  border: 1px solid var(--color-border-subtle,#444);
  border-radius: 7px;
  padding: 5px 10px;
  background: transparent;
  color: var(--color-primary,#6366f1);
  font-size: 0.78rem;
  font-weight: 600;
  line-height: 1;
  text-decoration: none;
}
.dg-loop-link:hover {
  background: var(--dg-btn-hover, rgba(255,255,255,0.06));
}

.dg-loop-status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 220px;
  padding: 5px 10px;
  border: 1px solid rgba(20,184,166,0.28);
  border-radius: 999px;
  background: rgba(15,23,42,0.42);
  color: #94a3b8;
  font: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s, border-color 0.15s;
}

.dg-loop-status-chip span {
  color: #5eead4;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.dg-loop-status-chip strong {
  color: #f8fafc;
  font-size: 0.78rem;
  font-weight: 800;
}

.dg-loop-status-chip small {
  color: #94a3b8;
  font-size: 0.68rem;
}

.dg-loop-status-chip:hover {
  border-color: rgba(20,184,166,0.45);
  background: rgba(20,184,166,0.12);
}

.dg-loop-status-chip--run {
  border-color: rgba(59,130,246,0.35);
  background: rgba(30,64,175,0.18);
}

.dg-loop-status-chip--bad {
  border-color: rgba(239,68,68,0.35);
  background: rgba(127,29,29,0.22);
}

/* Buttons */
.dg-btn {
  border: none; border-radius: 7px; padding: 6px 13px;
  font-size: 0.82rem; cursor: pointer; transition: opacity 0.15s, background 0.15s; white-space: nowrap;
}
.dg-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.dg-btn--primary  { background: var(--color-primary,#6366f1); color:#fff; font-weight:600; width:100%; margin-bottom:6px; }
.dg-btn--primary:hover:not(:disabled) { opacity: 0.88; }
.dg-btn--ghost    { background:transparent; border:1px solid var(--color-border-subtle,#444); color:var(--color-text-secondary,#aaa); }
.dg-btn--ghost:hover:not(:disabled) { background:var(--dg-btn-hover, rgba(255,255,255,0.06)); }
.dg-btn--outline  { background:transparent; border:1px solid var(--color-border-subtle,#555); color:var(--color-text-secondary,#bbb); }
.dg-btn--outline:hover { background:var(--dg-btn-hover, rgba(255,255,255,0.06)); }
.dg-btn--active   { border-color: var(--color-primary,#6366f1); color: var(--color-primary,#6366f1); }
.dg-btn--refresh-on { background: rgba(52,211,153,0.12); border:1px solid #34d39944; color: #34d399; }
.dg-btn--full     { width:100%; }
.dg-btn--dispatch { background:rgba(99,102,241,0.15); border:1px solid #6366f188; color:#818cf8; width:100%; margin-top:6px; font-weight:600; }
.dg-btn--dispatch:hover:not(:disabled) { background:rgba(99,102,241,0.25); }
.dg-btn--inline   { background:transparent; border:none; color:var(--color-primary,#6366f1); cursor:pointer; text-decoration:underline; font-size:inherit; }
.dg-badge         { display:inline-block; margin-left:5px; border-radius:20px; padding:1px 6px; font-size:0.72rem; font-weight:700; }
.dg-badge--red    { background:#ef444422; color:#ef4444; }
.dg-close { background:transparent; border:none; color:var(--color-text-muted,#888); font-size:1rem; cursor:pointer; padding:4px 8px; border-radius:6px; transition:background 0.15s; }
.dg-close:hover { background:var(--dg-btn-hover, rgba(255,255,255,0.08)); }

.dg-stat--toggle { cursor:pointer; border:1px solid var(--color-border-subtle,#444); border-radius:12px; padding:1px 8px; font-size:0.72rem; color:var(--color-text-muted,#888); background:transparent; transition:background 0.15s; }
.dg-stat--toggle:hover { background:var(--dg-btn-hover, rgba(255,255,255,0.06)); }
.dg-stat--toggle-open { border-color:var(--color-primary,#6366f1); color:var(--color-primary,#6366f1); }

.dg-more-wrap { position:relative; }
.dg-more-menu {
  position:absolute; top:100%; right:0; margin-top:4px;
  background:var(--color-bg-elevated,#1e1e2e); border:1px solid var(--color-border-subtle,#444);
  border-radius:8px; padding:4px 0; min-width:180px; z-index:100;
  box-shadow:var(--dg-menu-shadow, 0 8px 24px rgba(0,0,0,0.4));
}
.dg-more-item {
  display:flex; align-items:center; gap:6px; width:100%;
  background:transparent; border:none; padding:8px 14px;
  font-size:0.82rem; color:var(--color-text-secondary,#bbb); cursor:pointer; text-align:left;
  transition:background 0.12s;
}
.dg-more-item:hover { background:var(--dg-btn-hover, rgba(255,255,255,0.06)); }
.dg-more-item--active { color:var(--color-primary,#6366f1); }
.dg-more-item:disabled { opacity:0.4; cursor:not-allowed; }

.dg-fade-enter-active, .dg-fade-leave-active { transition:opacity 0.15s; }
.dg-fade-enter-from, .dg-fade-leave-to { opacity:0; }

.dg-section-toggle {
  display:flex; justify-content:space-between; align-items:center;
  width:100%; background:rgba(255,255,255,0.03); border:none; border-top:1px solid var(--color-border-subtle,#333);
  padding:8px 0; cursor:pointer; color:var(--color-text-secondary,#aaa);
  font-size:0.82rem; font-weight:600; transition:background 0.12s, color 0.12s;
}
.dg-section-toggle:hover { background:rgba(255,255,255,0.05); color:var(--color-text-primary,#e0e0e0); }
.dg-section-toggle-icon { font-size:0.7rem; color:var(--color-text-muted,#666); }

/* ─── Error / empty ──────────────────────────────────────────────────────── */
.dg-error { padding:12px 18px; color:var(--color-error,#f87171); font-size:0.875rem; flex-shrink:0; }
.dg-error--warn { color:#fbbf24; }
.dg-empty { flex:1; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--color-text-muted,#888); font-size:0.95rem; line-height:1.8; }

/* ─── Body ───────────────────────────────────────────────────────────────── */
.dg-body { flex: 1; display: flex; flex-direction: column; overflow: hidden; position: relative; z-index: 0; min-height: 0; }

/* ─── Gap panel (Phase 3-b) ──────────────────────────────────────────────── */
.dg-slide-top-enter-active,.dg-slide-top-leave-active { transition: max-height 0.22s ease, opacity 0.22s; overflow:hidden; }
.dg-slide-top-enter-from,.dg-slide-top-leave-to { max-height:0!important; opacity:0; }

.dg-gap-panel {
  max-height: 180px;
  border-bottom: 1px solid var(--color-border-subtle,#333);
  display: flex; flex-direction: column; flex-shrink: 0;
  background: var(--color-bg-elevated,#1a1a2a);
}
.dg-gap-hint {
  margin: 0;
  padding: 8px 16px 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary, #aaa);
}
.dg-gap-summary { display:flex; gap:8px; padding:8px 16px 6px; flex-shrink:0; }
.dg-gap-pill { font-size:0.76rem; padding:2px 10px; border-radius:20px; font-weight:600; }
.dg-gap-pill--deployed  { background:rgba(74,222,128,0.12); color:#4ade80; }
.dg-gap-pill--missing   { background:rgba(239,68,68,0.12);  color:#ef4444; }
.dg-gap-pill--untracked { background:rgba(99,102,241,0.12); color:#818cf8; }

.dg-gap-list { display:flex; flex-wrap:wrap; gap:4px; padding:0 16px 10px; overflow-y:auto; }
.dg-gap-row  { display:flex; align-items:center; gap:5px; padding:3px 8px; border-radius:6px; font-size:0.75rem; cursor:default; }
.dg-gap-row--deployed  { background:rgba(74,222,128,0.08); color:#4ade80; cursor:pointer; }
.dg-gap-row--deployed:hover { background:rgba(74,222,128,0.16); }
.dg-gap-row--missing   { background:rgba(239,68,68,0.08);  color:#ef4444; }
.dg-gap-row--untracked { background:rgba(99,102,241,0.08); color:#818cf8; cursor:pointer; }
.dg-gap-icon { font-size:0.7rem; }
.dg-gap-name { font-weight:600; }
.dg-gap-area { font-size:0.68rem; opacity:0.7; }

/* ─── No-key panel ───────────────────────────────────────────────────────── */
.dg-nokey-panel {
  border-bottom: 1px solid var(--color-border-subtle,#333);
  background: rgba(239,68,68,0.06);
  padding: 10px 16px 12px;
  display: flex; flex-direction: column; gap: 8px; flex-shrink: 0;
}
.dg-nokey-header { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
.dg-nokey-title  { font-size:0.85rem; font-weight:600; color:#ef4444; }
.dg-nokey-meta   { font-size:0.72rem; color:var(--color-text-muted,#888); }
.dg-nokey-error  { font-size:0.78rem; color:#f87171; margin:0; }
.dg-nokey-empty  { font-size:0.78rem; color:var(--color-text-muted,#888); margin:0; }
.dg-nokey-list   { display:flex; flex-direction:column; gap:6px; max-height:220px; overflow-y:auto; }
.dg-nokey-row {
  display:flex; align-items:center; justify-content:space-between; gap:12px;
  padding:6px 10px; border-radius:6px; background:rgba(255,255,255,0.04);
  border:1px solid var(--color-border-subtle,#333);
}
.dg-nokey-row__main { display:flex; flex-direction:column; gap:2px; min-width:0; flex:1; }
.dg-nokey-row__name { font-size:0.84rem; font-weight:600; color:var(--color-text-primary,#e0e0e0); }
.dg-nokey-row__pkg  { font-size:0.7rem; color:var(--color-text-muted,#888); font-family:ui-monospace,monospace; }
.dg-nokey-row__provider { font-size:0.72rem; color:var(--color-text-secondary,#aaa); }
.dg-nokey-row__provider code { font-size:0.7rem; padding:0 4px; border-radius:3px; background:rgba(255,255,255,0.06); }
.dg-nokey-row__actions { display:flex; gap:6px; flex-shrink:0; }

/* ─── Graph run panel ─────────────────────────────────────────────────────── */
.dg-run-panel {
  border-bottom: 1px solid var(--color-border-subtle,#333);
  background: rgba(99,102,241,0.06);
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dg-run-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 8px 10px;
}
.dg-run-label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.74rem;
  color: var(--color-text-secondary,#b5b5c5);
}
.dg-run-label--wide { grid-column: 1 / -1; }
.dg-run-select,
.dg-run-textarea {
  width: 100%;
  border: 1px solid var(--color-border-subtle,#444);
  border-radius: 7px;
  background: var(--color-bg-page,#0e0e1a);
  color: var(--color-text-primary,#e0e0e0);
  padding: 6px 8px;
  font-size: 0.8rem;
}
.dg-run-textarea--mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dg-run-options {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}
.dg-run-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: var(--color-text-secondary,#b5b5c5);
}
.dg-run-error { margin: 0; color: #f87171; font-size: 0.76rem; }
.dg-run-summary { display:flex; flex-wrap:wrap; gap:6px; }
.dg-run-pill {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 20px;
  background: rgba(255,255,255,0.08);
  color: var(--color-text-secondary,#bbb);
}
.dg-run-pill--ok { color:#22c55e; background:rgba(34,197,94,0.14); }
.dg-run-pill--bad { color:#ef4444; background:rgba(239,68,68,0.14); }
.dg-run-pill--warn { color:#f59e0b; background:rgba(245,158,11,0.14); }

/* ─── Flow wrap ──────────────────────────────────────────────────────────── */
.dg-flow-wrap { flex:1; display:flex; overflow:hidden; position:relative; z-index:0; min-height:280px; height:100%; }
.dg-flow      { flex:1; width:100%; height:100%; background:var(--dg-flow-bg, var(--color-bg-body,#0a0a14)); min-height:280px; }
.dg-group-node { width:100%; height:100%; min-height:48px; pointer-events:none; box-sizing:border-box; }
.dg-group-node__label {
  position:absolute; top:8px; left:12px;
  font-weight:700; font-size:0.78rem; line-height:1.2;
  color:inherit; pointer-events:none;
  letter-spacing:0.02em;
}

/* ─── Custom node ────────────────────────────────────────────────────────── */
.dg-node-inner {
  position:relative;
  display:flex;
  align-items:center;
  gap:6px;
  width:100%;
  box-sizing:border-box;
}
.dg-node-inner--loop {
  margin:-4px;
  padding:4px;
  border-radius:8px;
  background:
    radial-gradient(circle at 0% 50%, rgba(20,184,166,0.20), transparent 46%),
    rgba(20,184,166,0.07);
  box-shadow:0 0 0 1px rgba(20,184,166,0.25), 0 0 16px rgba(20,184,166,0.18);
}
.dg-node-label { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.dg-node-dots  { display:flex; align-items:center; gap:3px; flex-shrink:0; }
.dg-node-dot   { width:9px; height:9px; border-radius:50%; box-shadow:0 0 5px currentColor; }
.dg-node-dot--llm { width:7px; height:7px; opacity:0.85; }
.dg-node-dot--cap { width:7px; height:7px; opacity:0.9; }
.dg-node-dot--run { width:8px; height:8px; box-shadow:0 0 6px rgba(59,130,246,0.45); }
.dg-node-dot--loop {
  width: 9px;
  height: 9px;
  background: #14b8a6;
  box-shadow: 0 0 0 2px rgba(20,184,166,0.18), 0 0 9px rgba(20,184,166,0.76);
}

.dg-stat--loop {
  border-color:rgba(20,184,166,0.32);
  background:rgba(20,184,166,0.12);
  color:#5eead4;
}

.dg-loop-command-strip {
  display:grid;
  grid-template-columns:minmax(150px, 190px) minmax(260px, 1fr);
  gap:8px;
  width:min(840px, 100%);
  padding:10px;
  border:1px solid rgba(20,184,166,0.22);
  border-radius:14px;
  background:
    radial-gradient(circle at 8% 0%, rgba(20,184,166,0.18), transparent 36%),
    rgba(15,23,42,0.68);
  box-shadow:0 12px 32px rgba(15,23,42,0.22);
}

.dg-loop-command-strip--compact {
  grid-template-columns:minmax(140px, 180px) minmax(0, 1fr);
  grid-template-areas:
    'main map'
    'directive directive';
  align-self:flex-start;
  width:min(720px, 100%);
}

.dg-loop-command-strip--compact .dg-loop-command-main { grid-area:main; }
.dg-loop-command-strip--compact .dg-loop-governance-map { grid-area:map; }
.dg-loop-command-strip--compact .dg-loop-governance-directive { grid-area:directive; }

.dg-loop-runtime-panel {
  flex:1;
  min-height:0;
  overflow:auto;
  padding:12px 16px;
}

.dg-loop-command-main {
  display:flex;
  min-width:0;
  flex-direction:column;
  justify-content:center;
  gap:3px;
  padding:8px 10px;
  border-radius:11px;
  background:rgba(2,6,23,0.28);
}

.dg-loop-command-main span,
.dg-loop-command-main small {
  overflow:hidden;
  color:#94a3b8;
  font-size:0.68rem;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-main span {
  color:#5eead4;
  font-weight:800;
  letter-spacing:0.05em;
  text-transform:uppercase;
}

.dg-loop-command-main strong {
  overflow:hidden;
  color:#f8fafc;
  font-size:1rem;
  font-weight:900;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-cards {
  display:grid;
  grid-template-columns:repeat(4, minmax(0, 1fr));
  gap:6px;
}

.dg-loop-command-card {
  display:flex;
  min-width:0;
  flex-direction:column;
  gap:2px;
  padding:7px 8px;
  border:1px solid rgba(148,163,184,0.10);
  border-radius:10px;
  background:rgba(15,23,42,0.58);
}

.dg-loop-command-card--run {
  border-color:rgba(20,184,166,0.30);
  background:rgba(20,184,166,0.12);
}

.dg-loop-command-card--ok {
  background:rgba(34,197,94,0.10);
}

.dg-loop-command-card--warn {
  background:rgba(245,158,11,0.11);
}

.dg-loop-command-card--bad {
  background:rgba(239,68,68,0.12);
}

.dg-loop-command-card span,
.dg-loop-command-card small {
  overflow:hidden;
  color:#94a3b8;
  font-size:0.64rem;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-card strong {
  overflow:hidden;
  color:#f8fafc;
  font-size:0.82rem;
  font-weight:900;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-workers,
.dg-loop-command-coverage,
.dg-loop-command-separation {
  grid-column:1 / -1;
  display:flex;
  gap:6px;
  overflow-x:auto;
  padding-bottom:1px;
}

.dg-loop-command-separation {
  display:grid;
  grid-template-columns:repeat(4, minmax(0, 1fr));
  overflow:visible;
  padding-bottom:0;
}

.dg-loop-command-worker,
.dg-loop-command-dept {
  display:flex;
  flex:0 0 auto;
  min-width:118px;
  max-width:180px;
  flex-direction:column;
  gap:2px;
  padding:6px 8px;
  border:1px solid rgba(20,184,166,0.24);
  border-radius:10px;
  background:rgba(20,184,166,0.09);
  color:#ccfbf1;
  cursor:pointer;
  font:inherit;
  text-align:left;
}

.dg-loop-command-dept {
  min-width:150px;
  border-color:rgba(59,130,246,0.22);
  background:rgba(59,130,246,0.08);
  color:#dbeafe;
}

.dg-loop-command-worker span,
.dg-loop-command-worker small,
.dg-loop-command-dept span,
.dg-loop-command-dept small {
  overflow:hidden;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-worker span,
.dg-loop-command-dept span {
  font-size:0.7rem;
  font-weight:900;
}

.dg-loop-command-worker small,
.dg-loop-command-dept small {
  color:#99f6e4;
  font-size:0.62rem;
}

.dg-loop-command-dept small {
  color:#bfdbfe;
}

.dg-loop-command-dept strong {
  color:#f8fafc;
  font-size:0.82rem;
  font-weight:900;
}

.dg-loop-command-separation-card {
  display:flex;
  min-width:0;
  flex-direction:column;
  gap:2px;
  padding:7px 8px;
  border:1px solid rgba(148,163,184,0.10);
  border-radius:10px;
  background:rgba(15,23,42,0.50);
}

.dg-loop-command-separation-card--ok {
  background:rgba(34,197,94,0.10);
}

.dg-loop-command-separation-card--run {
  border-color:rgba(20,184,166,0.26);
  background:rgba(20,184,166,0.11);
}

.dg-loop-command-separation-card--warn {
  background:rgba(245,158,11,0.11);
}

.dg-loop-command-separation-card--bad {
  background:rgba(239,68,68,0.12);
}

.dg-loop-command-separation-card span,
.dg-loop-command-separation-card small {
  overflow:hidden;
  color:#94a3b8;
  font-size:0.64rem;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-separation-card strong {
  overflow:hidden;
  color:#f8fafc;
  font-size:0.82rem;
  font-weight:900;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-diagnosis {
  grid-column:1 / -1;
  display:grid;
  grid-template-columns:minmax(0, 1fr) minmax(190px, 300px);
  gap:8px;
  padding:8px 9px;
  border:1px solid rgba(148,163,184,0.12);
  border-radius:11px;
  background:rgba(15,23,42,0.56);
}

.dg-loop-command-diagnosis--run {
  border-color:rgba(20,184,166,0.28);
  background:rgba(20,184,166,0.11);
}

.dg-loop-command-diagnosis--ok {
  background:rgba(34,197,94,0.10);
}

.dg-loop-command-diagnosis--warn {
  background:rgba(245,158,11,0.11);
}

.dg-loop-command-diagnosis--bad {
  background:rgba(239,68,68,0.13);
}

.dg-loop-command-diagnosis div {
  min-width:0;
}

.dg-loop-command-diagnosis span,
.dg-loop-command-diagnosis small {
  display:block;
  overflow:hidden;
  color:#94a3b8;
  font-size:0.64rem;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-diagnosis span {
  color:#5eead4;
  font-weight:900;
  letter-spacing:0.05em;
  text-transform:uppercase;
}

.dg-loop-command-diagnosis strong {
  display:block;
  overflow:hidden;
  margin:2px 0;
  color:#f8fafc;
  font-size:0.84rem;
  font-weight:900;
  text-overflow:ellipsis;
  white-space:nowrap;
}

.dg-loop-command-diagnosis-links {
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  margin-top:7px;
}

.dg-loop-command-diagnosis-links a,
.dg-loop-command-diagnosis-links button {
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:4px 8px;
  border:1px solid rgba(20,184,166,0.24);
  border-radius:999px;
  background:rgba(20,184,166,0.10);
  color:#99f6e4;
  cursor:pointer;
  font:inherit;
  font-size:0.62rem;
  font-weight:900;
  text-decoration:none;
}

.dg-loop-command-diagnosis-links button:disabled {
  opacity:0.56;
  cursor:not-allowed;
}

.dg-loop-command-diagnosis-links .dg-loop-command-diagnosis-action {
  border-color:rgba(251,191,36,0.38);
  background:linear-gradient(135deg, rgba(251,191,36,0.22), rgba(20,184,166,0.14));
  color:#fef3c7;
}

.dg-loop-command-diagnosis-result {
  margin-top:6px;
  white-space:normal;
}

.dg-loop-command-diagnosis-result--ok {
  color:#86efac;
}

.dg-loop-command-diagnosis-result--bad {
  color:#fecaca;
}

.dg-loop-command-diagnosis ul {
  display:flex;
  flex-wrap:wrap;
  gap:5px;
  align-content:center;
  margin:0;
  padding:0;
  list-style:none;
}

.dg-loop-command-diagnosis li {
  overflow:hidden;
  max-width:180px;
  padding:4px 7px;
  border-radius:999px;
  background:rgba(15,23,42,0.28);
  color:#e2e8f0;
  font-size:0.62rem;
  font-weight:800;
  text-overflow:ellipsis;
  white-space:nowrap;
}

@media (max-width: 980px) {
  .dg-loop-command-strip {
    grid-template-columns:1fr;
  }

  .dg-loop-command-cards,
  .dg-loop-command-separation {
    grid-template-columns:repeat(2, minmax(0, 1fr));
  }

  .dg-loop-command-diagnosis {
    grid-template-columns:1fr;
  }
}

/* ─── Detail sidebar ─────────────────────────────────────────────────────── */
.dg-detail {
  width: 248px; flex-shrink:0; overflow-y:auto;
  padding:16px 14px; border-left:1px solid var(--color-border-subtle,#333);
  display:flex; flex-direction:column; gap:9px;
  background:var(--color-bg-elevated,#1a1a2a);
}
.dg-slide-enter-active,.dg-slide-leave-active { transition:width 0.2s ease,opacity 0.2s; overflow:hidden; }
.dg-slide-enter-from,.dg-slide-leave-to { width:0!important; opacity:0; padding:0; }

.dg-detail-header { display:flex; align-items:center; gap:7px; }
.dg-detail-dot    { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.dg-detail-name   { font-size:0.9rem; font-weight:700; color:var(--color-text-primary,#e0e0e0); word-break:break-all; }
.dg-detail-id     { font-size:0.71rem; color:var(--color-text-muted,#888); font-family:monospace; word-break:break-all; }
.dg-detail-meta   { font-size:0.78rem; color:var(--color-text-secondary,#aaa); }
.dg-detail-badge  { font-size:0.76rem; padding:3px 8px; border-radius:5px; text-align:center; }
.dg-badge--ok   { background:rgba(74,222,128,0.10); color:#4ade80; }
.dg-badge--warn { background:rgba(245,158,11,0.10);  color:#f59e0b; }

.dg-detail-health { display:flex; flex-direction:column; gap:4px; padding:9px; background:rgba(255,255,255,0.04); border-radius:8px; }
.dg-hrow    { display:flex; justify-content:space-between; align-items:center; }
.dg-hlabel  { font-size:0.73rem; color:var(--color-text-muted,#888); }
.dg-hval    { font-size:0.79rem; color:var(--color-text-primary,#e0e0e0); font-weight:600; }
.dg-hval--sm { font-size:0.7rem; font-weight:400; }
.dg-detail-loading { font-size:0.76rem; color:var(--color-text-muted,#888); text-align:center; }

.dg-detail-capability,
.dg-detail-run-node {
  display:flex;
  flex-direction:column;
  gap:5px;
  padding:9px;
  border-radius:8px;
  background:rgba(255,255,255,0.03);
  border:1px solid var(--color-border-subtle,#333);
}
.dg-cap-title {
  margin:0;
  font-size:0.72rem;
  font-weight:700;
  color:var(--color-text-secondary,#bbb);
  text-transform:uppercase;
  letter-spacing:0.04em;
}
.dg-cap-reasons {
  margin:0;
  font-size:0.72rem;
  color:#f59e0b;
  line-height:1.4;
}
.dg-cap-risk {
  padding:6px 7px;
  border-radius:6px;
  background:rgba(239,68,68,0.08);
  border:1px solid rgba(239,68,68,0.22);
}
.dg-cap-risk-title {
  margin:0 0 4px;
  font-size:0.68rem;
  color:#f87171;
  font-weight:700;
}
.dg-cap-risk-list {
  margin:0;
  padding-left:14px;
  display:flex;
  flex-direction:column;
  gap:3px;
  font-size:0.7rem;
  color:#fda4af;
}
.dg-cap-link {
  font-size:0.72rem;
  color:#818cf8;
  text-decoration:underline;
  text-align:right;
}

.dg-detail-exec { display:flex; flex-direction:column; gap:6px; padding:9px; background:rgba(255,255,255,0.03); border-radius:8px; }
.dg-detail-selfloop {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 9px;
  border: 1px solid rgba(20,184,166,0.22);
  border-radius: 8px;
  background:
    radial-gradient(circle at 8% 0%, rgba(20,184,166,0.16), transparent 38%),
    rgba(20,184,166,0.06);
}
.dg-detail-loop-context {
  display:flex;
  flex-direction:column;
  gap:5px;
  padding:10px;
  border:1px solid rgba(148,163,184,0.14);
  border-radius:9px;
  background:rgba(255,255,255,0.035);
}
.dg-detail-loop-context--run {
  border-color:rgba(20,184,166,0.28);
  background:rgba(20,184,166,0.10);
}
.dg-detail-loop-context--idle {
  border-color:rgba(59,130,246,0.20);
  background:rgba(59,130,246,0.08);
}
.dg-detail-loop-context--warn {
  border-color:rgba(245,158,11,0.24);
  background:rgba(245,158,11,0.09);
}
.dg-detail-loop-context--bad {
  border-color:rgba(239,68,68,0.26);
  background:rgba(239,68,68,0.10);
}
.dg-detail-loop-context span {
  color:#5eead4;
  font-size:0.68rem;
  font-weight:900;
  letter-spacing:0.05em;
  text-transform:uppercase;
}
.dg-detail-loop-context strong {
  color:var(--color-text-primary,#e0e0e0);
  font-size:0.8rem;
  font-weight:900;
}
.dg-detail-loop-context p {
  margin:0;
  color:var(--color-text-secondary,#aaa);
  font-size:0.72rem;
  line-height:1.42;
}
.dg-detail-loop-context-actions {
  display:flex;
  flex-wrap:wrap;
  gap:6px;
  margin-top:2px;
}
.dg-detail-loop-context-actions a,
.dg-detail-loop-context-actions button {
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:4px 8px;
  border:1px solid rgba(20,184,166,0.22);
  border-radius:999px;
  background:rgba(20,184,166,0.10);
  color:#99f6e4;
  cursor:pointer;
  font:inherit;
  font-size:0.64rem;
  font-weight:900;
  text-decoration:none;
}
.dg-selfloop-workspace-link {
  text-decoration: none;
}
.dg-exec-title { font-size:0.72rem; font-weight:700; color:var(--color-text-secondary,#bbb); text-transform:uppercase; letter-spacing:0.04em; margin:0; }
.dg-exec-hint { font-size:0.68rem; color:var(--color-text-muted,#777); line-height:1.35; margin:0; }
.dg-exec-empty { font-size:0.76rem; color:var(--color-text-muted,#888); margin:0; }
.dg-exec-err { font-size:0.75rem; color:#f87171; word-break:break-all; margin:0; }
.dg-exec-list { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:8px; max-height:280px; overflow-y:auto; }
.dg-exec-item { padding:7px 8px; border-radius:6px; background:rgba(0,0,0,0.2); border:1px solid var(--color-border-subtle,#333); }
.dg-exec-item-meta { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:center; font-size:0.7rem; color:var(--color-text-secondary,#aaa); }
.dg-exec-time { color:var(--color-text-primary,#ddd); font-weight:600; }
.dg-exec-num { font-family:monospace; font-size:0.68rem; opacity:0.85; }
.dg-exec-status { font-weight:700; }
.dg-exec-status--ok { color:#4ade80; }
.dg-exec-status--bad { color:#f87171; }
.dg-exec-task { font-size:0.72rem; color:var(--color-text-primary,#e0e0e0); margin:6px 0 0; line-height:1.35; display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; word-break:break-word; }
.dg-exec-err-line { font-size:0.68rem; color:#f87171; margin:4px 0 0; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.dg-exec-footer { display:flex; flex-direction:column; gap:6px; align-items:stretch; margin-top:4px; }
.dg-exec-count { font-size:0.68rem; color:var(--color-text-muted,#777); }
.dg-btn--small { padding:4px 10px; font-size:0.76rem; width:auto; align-self:flex-start; }

.dg-detail-deps { display:flex; flex-direction:column; gap:4px; }
.dg-deps-title  { font-size:0.72rem; color:var(--color-text-muted,#888); font-weight:600; text-transform:uppercase; letter-spacing:0.04em; }
.dg-deps-list   { list-style:none; display:flex; flex-direction:column; gap:3px; }
.dg-deps-item   { font-size:0.73rem; padding:2px 7px; border-radius:5px; background:rgba(129,140,248,0.10); color:#818cf8; font-family:monospace; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* ── 能做什么 · 怎么做（与真实员工 manifest.cognition.skills 同源） ─────────────── */
.dg-detail-skills {
  display:flex;
  flex-direction:column;
  gap:8px;
  padding:9px;
  border-radius:8px;
  background:rgba(34,211,238,0.05);
  border:1px solid rgba(34,211,238,0.18);
}
.dg-skills-title {
  margin:0;
  font-size:0.72rem;
  font-weight:700;
  color:#22d3ee;
  text-transform:uppercase;
  letter-spacing:0.04em;
}
.dg-skills-subtitle {
  margin:4px 0 2px;
  font-size:0.68rem;
  font-weight:600;
  color:var(--color-text-muted,#888);
  text-transform:uppercase;
  letter-spacing:0.04em;
}
.dg-skills-virtual-hint {
  margin:0;
  font-size:0.68rem;
  color:#22d3ee;
  background:rgba(34,211,238,0.08);
  border-radius:5px;
  padding:4px 6px;
  line-height:1.35;
}
.dg-skills-persona {
  margin:0;
  font-size:0.74rem;
  color:var(--color-text-primary,#e0e0e0);
  line-height:1.45;
}
.dg-skills-expertise {
  display:flex;
  flex-wrap:wrap;
  gap:4px;
}
.dg-skills-tag {
  font-size:0.68rem;
  padding:2px 7px;
  border-radius:999px;
  background:rgba(34,211,238,0.12);
  color:#67e8f9;
}
.dg-skills-list {
  list-style:none;
  margin:0;
  padding:0;
  display:flex;
  flex-direction:column;
  gap:6px;
}
.dg-skill-row {
  border-radius:6px;
  background:rgba(0,0,0,0.18);
  border:1px solid var(--color-border-subtle,#333);
  padding:6px 8px;
  display:flex;
  flex-direction:column;
  gap:3px;
}
.dg-skill-head {
  display:flex;
  align-items:baseline;
  gap:6px;
  justify-content:space-between;
}
.dg-skill-name {
  font-size:0.78rem;
  font-weight:600;
  color:var(--color-text-primary,#e0e0e0);
}
.dg-skill-kind {
  font-size:0.66rem;
  font-family:ui-monospace,SFMono-Regular,monospace;
  color:#a78bfa;
  background:rgba(167,139,250,0.10);
  border-radius:4px;
  padding:1px 5px;
}
.dg-skill-brief {
  margin:0;
  font-size:0.7rem;
  color:var(--color-text-secondary,#aaa);
  line-height:1.4;
}
.dg-skill-how {
  margin:0;
  font-size:0.68rem;
  color:var(--color-text-muted,#888);
  display:flex;
  flex-wrap:wrap;
  gap:4px;
  align-items:baseline;
}
.dg-skill-how-label {
  color:#22d3ee;
  font-weight:600;
}
.dg-skill-how code {
  font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:0.66rem;
  background:rgba(255,255,255,0.04);
  padding:1px 5px;
  border-radius:4px;
  color:var(--color-text-secondary,#bbb);
}
.dg-skills-empty {
  margin:0;
  font-size:0.7rem;
  color:var(--color-text-muted,#888);
  line-height:1.4;
}
.dg-skills-handlers {
  display:flex;
  flex-direction:column;
  gap:3px;
}
.dg-handler-list {
  list-style:none;
  margin:0;
  padding:0;
  display:flex;
  flex-direction:column;
  gap:3px;
}
.dg-handler-row {
  display:flex;
  flex-wrap:wrap;
  gap:5px;
  align-items:baseline;
  font-size:0.68rem;
  color:var(--color-text-secondary,#bbb);
  line-height:1.35;
}
.dg-handler-name {
  font-family:ui-monospace,SFMono-Regular,monospace;
  font-size:0.66rem;
  background:rgba(255,255,255,0.04);
  padding:1px 5px;
  border-radius:4px;
  color:var(--color-text-primary,#e0e0e0);
}
.dg-handler-desc {
  flex:1;
  min-width:0;
}
.dg-skills-workflow {
  margin:0;
  font-size:0.7rem;
  color:var(--color-text-muted,#888);
}
.dg-skills-workflow-link {
  color:#818cf8;
  text-decoration:underline;
  font-family:ui-monospace,SFMono-Regular,monospace;
}

/* ── 全员汇报抽屉 ───────────────────────────────────────────────────────────── */
.dg-btn--ah {
  border-color: rgba(34, 211, 238, 0.45);
  color: #67e8f9;
}
.dg-btn--ah:hover:not(:disabled) {
  background: rgba(34, 211, 238, 0.12);
}
.dg-allhands-panel {
  border-bottom: 1px solid var(--color-border-subtle, #333);
  background: linear-gradient(180deg, rgba(34,211,238,0.06), rgba(34,211,238,0.02));
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 60vh;
  overflow-y: auto;
}
.dg-allhands-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.dg-allhands-head-left { min-width: 220px; flex: 1; }
.dg-allhands-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.dg-allhands-title {
  margin: 0;
  font-size: 0.95rem;
  color: #67e8f9;
  font-weight: 700;
}
.dg-allhands-sub {
  margin: 4px 0 0;
  font-size: 0.74rem;
  color: var(--color-text-secondary, #a8a8b8);
  line-height: 1.5;
}
.dg-allhands-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 0.78rem;
  color: var(--color-text-secondary, #aaa);
}
.dg-allhands-progress {
  border: 1px solid rgba(34, 211, 238, 0.24);
  border-radius: 8px;
  padding: 8px 10px;
  background: rgba(15, 23, 42, 0.35);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dg-allhands-progress-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 0.74rem;
  color: var(--color-text-secondary, #aab);
}
.dg-allhands-progress-track {
  position: relative;
  height: 6px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.1);
  overflow: hidden;
}
.dg-allhands-progress-fill {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 0;
  border-radius: inherit;
  background: linear-gradient(90deg, #22d3ee, #3b82f6);
  transition: width 0.25s ease;
}
.dg-allhands-progress-sub {
  margin: 0;
  font-size: 0.7rem;
  color: var(--color-text-muted, #8b93a6);
}
.dg-allhands-error {
  margin: 0;
  font-size: 0.78rem;
  color: #f87171;
  background: rgba(239,68,68,0.08);
  border-radius: 6px;
  padding: 6px 10px;
}
.dg-allhands-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dg-allhands-ask {
  display: flex; flex-direction: column; gap: 6px;
  background: rgba(99,102,241,0.08);
  border: 1px solid rgba(99,102,241,0.4);
  border-radius: 8px; padding: 8px 10px;
}
.dg-allhands-ask__input {
  resize: vertical;
  width: 100%;
  background: rgba(0,0,0,0.25);
  color: var(--color-text-primary, #e0e0e0);
  border: 1px solid var(--color-border-subtle, #444);
  border-radius: 6px; padding: 6px 8px;
  font: inherit; font-size: 0.86rem;
}
.dg-allhands-ask__input:disabled { opacity: 0.6; }
.dg-allhands-ask__row { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.dg-allhands-ask__hint { font-size: 0.72rem; color: var(--color-text-muted, #888); }
.dg-run-pill--ask { background: rgba(99,102,241,0.18); color: #a5b4fc; }
.dg-allhands-synth {
  background: linear-gradient(180deg, rgba(99,102,241,0.10), rgba(99,102,241,0.04));
  border: 1px solid rgba(99,102,241,0.5);
  border-radius: 10px;
  padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px;
}
.dg-allhands-synth__head { display:flex; align-items:center; gap:10px; flex-wrap: wrap; }
.dg-allhands-synth__badge {
  font-size: 0.78rem; font-weight: 700; color: #fff;
  background: var(--color-primary, #6366f1); border-radius: 4px; padding: 2px 8px;
}
.dg-allhands-synth__model { font-size: 0.7rem; color: var(--color-text-muted, #888); font-family: ui-monospace, monospace; }
.dg-allhands-synth__question { font-size: 0.82rem; color: var(--color-text-secondary, #aaa); margin: 0; }
/* Markdown + Mermaid：复用 MessageBody + lightMarkdown；滚动在容器上 */
.dg-allhands-md {
  margin: 0;
  border-radius: 6px;
  max-height: 360px;
  overflow-y: auto;
  word-break: break-word;
}
.dg-allhands-md--card {
  background: rgba(0, 0, 0, 0.3);
  padding: 8px 10px;
}
.dg-allhands-md--synth {
  background: rgba(0, 0, 0, 0.25);
  padding: 10px 12px;
}
.dg-allhands-md :deep(.msg-body) {
  color: var(--color-text-primary, #e0e0e0);
  line-height: 1.55;
  font-size: 0.74rem;
  word-break: break-word;
}
.dg-allhands-md--synth :deep(.msg-body) {
  font-size: 0.86rem;
}
.dg-allhands-md :deep(.md-h1) { font-size: 1.15rem; }
.dg-allhands-md :deep(.md-h2) { font-size: 1rem; }
.dg-allhands-md :deep(.md-h3) { font-size: 0.9rem; }
.dg-allhands-md :deep(.md-h4),
.dg-allhands-md :deep(.md-h5),
.dg-allhands-md :deep(.md-h6) { font-size: 0.85rem; }
.dg-allhands-md :deep(.md-mermaid) {
  display: block;
  margin: 0.55rem 0;
  padding: 0.6rem;
  background: rgba(15, 23, 42, 0.6);
  border-radius: 0.6rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
  text-align: center;
}
.dg-allhands-md :deep(.md-mermaid svg) {
  max-width: 100%;
  height: auto;
}
.dg-allhands-synth__cited { display:flex; align-items:center; flex-wrap:wrap; gap:6px; }
.dg-allhands-synth__cited-label { font-size: 0.74rem; color: var(--color-text-muted, #888); }
.dg-allhands-synth__cite {
  background: rgba(255,255,255,0.06);
  border: 1px solid rgba(99,102,241,0.5);
  color: #a5b4fc;
  border-radius: 12px;
  padding: 1px 8px;
  font-size: 0.72rem; font-family: ui-monospace, monospace;
  cursor: pointer;
}
.dg-allhands-synth__cite:hover { background: rgba(99,102,241,0.18); }
.dg-allhands-synth-error { font-size: 0.78rem; color: #f59e0b; margin: 0; }

.dg-allhands-minutes {
  margin: 14px 0;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid var(--color-border-subtle, #333);
  background: rgba(99, 102, 241, 0.06);
}
.dg-allhands-minutes__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}
.dg-allhands-minutes__badge {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #a5b4fc;
}
.dg-allhands-minutes__model {
  font-size: 0.7rem;
  color: var(--color-text-muted, #888);
  font-family: ui-monospace, monospace;
}
.dg-allhands-minutes__actions {
  margin-left: auto;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dg-allhands-minutes__mail {
  font-size: 0.76rem;
  margin: 0 0 8px;
  line-height: 1.4;
}
.dg-allhands-minutes__mail--ok { color: #86efac; }
.dg-allhands-minutes__mail--muted { color: var(--color-text-muted, #888); }
.dg-allhands-minutes__pre {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: var(--color-bg-base, #0d0d18);
  border: 1px solid var(--color-border-subtle, #333);
  font-size: 0.82rem;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
  color: var(--color-text-primary, #e8e8e8);
}
.dg-allhands-minutes__err {
  margin: 0;
  font-size: 0.78rem;
  color: #f87171;
}
.dg-allhands-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dg-allhands-card {
  border: 1px solid var(--color-border-subtle, #333);
  border-left-width: 3px;
  border-radius: 8px;
  padding: 10px 12px;
  background: rgba(0,0,0,0.18);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dg-allhands-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.dg-allhands-card-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.dg-allhands-card-name {
  font-weight: 700;
  font-size: 0.9rem;
  color: var(--color-text-primary, #e0e0e0);
}
.dg-allhands-card-id {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 0.7rem;
  color: var(--color-text-muted, #888);
  background: rgba(255,255,255,0.04);
  padding: 1px 6px;
  border-radius: 4px;
}
.dg-allhands-card-status {
  display: inline-block;
  font-size: 0.68rem;
  padding: 1px 7px;
  border-radius: 999px;
  font-weight: 600;
}
.dg-allhands-card-status.is-ok { background: rgba(34,197,94,0.16); color: #4ade80; }
.dg-allhands-card-status.is-bad { background: rgba(239,68,68,0.16); color: #f87171; }
.dg-allhands-card-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.dg-btn--plain {
  border-color: rgba(251, 191, 36, 0.5);
  color: #fbbf24;
}
.dg-btn--plain:hover:not(:disabled) {
  background: rgba(251, 191, 36, 0.1);
}
.dg-allhands-plain {
  margin: 6px 0 4px;
  padding: 10px 14px;
  border-radius: 8px;
  background: rgba(251, 191, 36, 0.07);
  border: 1px solid rgba(251, 191, 36, 0.2);
  font-size: 0.82rem;
  line-height: 1.7;
  color: var(--color-text-primary, #e0e0e0);
}
.dg-allhands-plain-loading {
  color: #fbbf24;
  font-size: 0.8rem;
}
.dg-plain-dots {
  display: inline-block;
  animation: dg-plain-blink 1.2s steps(3, end) infinite;
  letter-spacing: 2px;
}
@keyframes dg-plain-blink {
  0%   { clip-path: inset(0 100% 0 0); }
  33%  { clip-path: inset(0 67% 0 0); }
  66%  { clip-path: inset(0 33% 0 0); }
  100% { clip-path: inset(0 0% 0 0); }
}
.dg-allhands-plain-text {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
}
.dg-allhands-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.dg-allhands-meta-tag {
  font-size: 0.66rem;
  padding: 2px 7px;
  border-radius: 999px;
  background: rgba(255,255,255,0.05);
  color: var(--color-text-secondary, #aaa);
}
.dg-allhands-meta-tag--warn {
  background: rgba(245,158,11,0.12);
  color: #fbbf24;
}
.dg-allhands-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 4px;
}
.dg-allhands-cog-err {
  margin: 0;
  font-size: 0.7rem;
  color: #f87171;
  word-break: break-all;
  background: rgba(239,68,68,0.06);
  border-radius: 6px;
  padding: 5px 8px;
}
.dg-allhands-empty {
  margin: 0;
  font-size: 0.72rem;
  color: var(--color-text-muted, #888);
}
.dg-allhands-details {
  font-size: 0.72rem;
  color: var(--color-text-secondary, #bbb);
}
.dg-allhands-details summary {
  cursor: pointer;
  color: #818cf8;
  outline: none;
}
.dg-allhands-fail-list,
.dg-allhands-source-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dg-allhands-fail-item {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: baseline;
  padding: 4px 6px;
  border-radius: 5px;
  background: rgba(255,255,255,0.03);
}
.dg-allhands-fail-time { color: var(--color-text-muted, #888); font-family: ui-monospace, monospace; font-size: 0.66rem; }
.dg-allhands-fail-status { color: #f87171; font-weight: 600; font-size: 0.66rem; }
.dg-allhands-fail-task { flex: 1; min-width: 0; color: var(--color-text-primary, #ddd); }
.dg-allhands-fail-err {
  display: block;
  width: 100%;
  font-size: 0.65rem;
  color: #fda4af;
  font-family: ui-monospace, monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.dg-allhands-source-list a { color: #818cf8; text-decoration: underline; }
.dg-allhands-warns {
  margin: 0;
  font-size: 0.7rem;
  color: #fbbf24;
}

/* LLM activation block (Phase 4) */
.dg-detail-llm { display:flex; flex-direction:column; gap:4px; padding:9px; background:rgba(129,140,248,0.06); border-radius:8px; border:1px solid rgba(129,140,248,0.15); }
.dg-llm-title  { font-size:0.72rem; color:#818cf8; font-weight:700; text-transform:uppercase; letter-spacing:0.04em; margin-bottom:2px; }
.dg-llm-fix    { font-size:0.75rem; color:#818cf8; text-decoration:underline; margin-top:4px; text-align:center; }
.dg-llm-fix:hover { opacity:0.8; }

/* Task dispatch (Phase 3-c) */
.dg-dispatch { display:flex; flex-direction:column; gap:6px; }
.dg-dispatch-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.dg-dispatch-input {
  width:100%; background:var(--color-bg-page,#0e0e1a); border:1px solid var(--color-border-subtle,#444);
  border-radius:7px; color:var(--color-text-primary,#e0e0e0); padding:7px 9px; font-size:0.8rem;
  resize:vertical; font-family:inherit; outline:none;
}
.dg-dispatch-input:focus { border-color:var(--color-primary,#6366f1); }
.dg-dispatch-input--mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.dg-dispatch-hint { margin:0; font-size:0.69rem; color:var(--color-text-muted,#888); line-height:1.35; }
.dg-dispatch-confirm {
  display:flex;
  align-items:flex-start;
  gap:6px;
  font-size:0.72rem;
  color:#f59e0b;
  line-height:1.35;
}
.dg-dispatch-actions .dg-btn--dispatch {
  flex: 1;
  margin-top: 0;
}
.dg-btn--dispatch-secondary {
  flex: 1;
  border-color: rgba(34, 211, 238, 0.35);
  color: #67e8f9;
}
.dg-btn--dispatch-secondary:hover:not(:disabled) {
  background: rgba(34, 211, 238, 0.12);
}
.dg-dispatch-err { font-size:0.75rem; color:#f87171; word-break:break-all; }
.dg-dispatch-result {
  font-size:0.72rem; color:var(--color-text-secondary,#bbb); background:rgba(255,255,255,0.04);
  border-radius:7px; padding:8px; max-height:160px; overflow-y:auto; white-space:pre-wrap; word-break:break-all;
}

/* ─── Loading ─────────────────────────────────────────────────────────────── */
.dg-loading {
  position:absolute; inset:0;
  display:flex; flex-direction:column; align-items:center; justify-content:center;
  gap:14px; color:var(--color-text-muted,#888); font-size:0.9rem;
  background:var(--color-bg-page,#0e0e1a); z-index:5;
}
@keyframes spin { to { transform:rotate(360deg); } }
.dg-spinner {
  display:block; width:28px; height:28px;
  border:3px solid rgba(255,255,255,0.1); border-top-color:var(--color-primary,#6366f1);
  border-radius:50%; animation:spin 0.8s linear infinite;
}

/* ─── 客户端车间（管理端） ─────────────────────────────────────────────── */
.dg-node-inner--workshop {
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}
.dg-node-workshop-kind {
  font-size: 0.62rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: #94a3b8;
  text-transform: uppercase;
}
.dg-detail--workshop .dg-detail-header {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.dg-workshop-status {
  font-size: 0.68rem;
  padding: 2px 8px;
  border-radius: 999px;
  flex-shrink: 0;
}
.dg-workshop-status--on {
  background: rgba(52, 211, 153, 0.15);
  color: #6ee7b7;
}
.dg-workshop-status--off {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}
.dg-workshop-linked {
  margin: 0.75rem 0;
}
.dg-workshop-linked__title {
  margin: 0 0 0.35rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--color-text-secondary, #aaa);
}
.dg-workshop-linked__list {
  margin: 0;
  padding: 0;
  list-style: none;
  max-height: 140px;
  overflow-y: auto;
}
.dg-workshop-linked__btn {
  display: block;
  width: 100%;
  padding: 0.35rem 0;
  border: none;
  background: transparent;
  color: #93c5fd;
  font-size: 0.8rem;
  text-align: left;
  cursor: pointer;
}
.dg-workshop-linked__btn:hover {
  color: #bfdbfe;
  text-decoration: underline;
}
.dg-workshop-linked__hint {
  margin: 0.35rem 0 0;
  font-size: 0.68rem;
  color: var(--color-text-muted, #888);
}
.dg-workshop-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin: 0.75rem 0;
}
.dg-btn--block {
  width: 100%;
  justify-content: center;
}
.dg-workshop-route {
  margin: 0 0 0.5rem;
  font-size: 0.68rem;
  word-break: break-all;
  color: var(--color-text-muted, #888);
}
.dg-workshop-route code {
  font-family: ui-monospace, monospace;
}
</style>
