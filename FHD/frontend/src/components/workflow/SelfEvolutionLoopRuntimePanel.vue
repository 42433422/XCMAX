<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

const props = withDefaults(defineProps<{
  compact?: boolean
  surface?: 'employee-space' | 'duty-roster'
}>(), {
  compact: false,
  surface: 'employee-space',
})

type AnyRecord = Record<string, unknown>

const router = useRouter()
const raw = ref<AnyRecord | null>(null)
const loading = ref(false)
const error = ref('')
const paraCopied = ref(false)
const governanceReviewBusy = ref(false)
const governanceReviewError = ref('')
const governanceReviewResult = ref<AnyRecord | null>(null)
let timer: number | null = null

function asRecord(v: unknown): AnyRecord {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as AnyRecord : {}
}

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

function asString(v: unknown): string {
  return String(v ?? '').trim()
}

function asNumber(v: unknown, fallback = 0): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const s = asString(value)
    if (s) return s
  }
  return ''
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    raw.value = await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(props.compact ? 40 : 80) as AnyRecord
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function copyParaTaskId() {
  const value = paraTaskId.value
  if (!value || typeof navigator === 'undefined' || !navigator.clipboard) return
  await navigator.clipboard.writeText(value)
  paraCopied.value = true
  window.setTimeout(() => {
    paraCopied.value = false
  }, 1400)
}

async function reviewGovernanceAudit() {
  if (!canReviewGovernanceAudit.value) return
  governanceReviewBusy.value = true
  governanceReviewError.value = ''
  governanceReviewResult.value = null
  try {
    governanceReviewResult.value = await xcmaxMarketProxy.selfMaintenanceGovernanceReview({
      note: `self-evolution panel reviewed governance audit on ${props.surface}`,
    }) as AnyRecord
    await refresh()
  } catch (err: unknown) {
    const e = err as { message?: unknown; detail?: unknown }
    governanceReviewError.value = String(e?.message || e?.detail || err || '治理审计复核失败')
  } finally {
    governanceReviewBusy.value = false
  }
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(() => {
    void refresh()
  }, 30000)
})

onBeforeUnmount(() => {
  if (timer != null) window.clearInterval(timer)
  timer = null
})

const evidence = computed<AnyRecord>(() => asRecord(raw.value?.evidence))
const memory = computed<AnyRecord>(() => asRecord(raw.value?.memory))
const policy = computed<AnyRecord>(() => asRecord(raw.value?.policy))
const gate = computed<AnyRecord>(() => asRecord(raw.value?.current_gate))
const cron = computed<AnyRecord>(() => asRecord(raw.value?.cron))
const activeGates = computed<AnyRecord>(() => {
  const fromDecision = asRecord(mergeDecision.value.active_gates)
  return Object.keys(fromDecision).length ? fromDecision : asRecord(raw.value?.active_gates)
})
const activeGateItems = computed(() =>
  asArray(activeGates.value.items)
    .map((item) => asRecord(item))
    .filter((item) => firstText(item.key, item.label)),
)
const runtimeSchemaVersion = computed(() => firstText(asRecord(raw.value).schema_version, 'unknown'))
const runtimeContract = computed<AnyRecord>(() => asRecord(asRecord(raw.value).contract))
const runtimeContractValidation = computed<AnyRecord>(() => asRecord(asRecord(raw.value).contract_validation))
const runtimeContractRequiredFields = computed(() =>
  asArray(runtimeContract.value.required_top_level).map((item) => asString(item)).filter(Boolean),
)
const runtimeContractMissingFields = computed(() => {
  const backendMissing = asArray(runtimeContractValidation.value.missing_fields).map((item) => asString(item)).filter(Boolean)
  if (backendMissing.length || runtimeContractValidation.value.ok === false) return backendMissing
  const payload = asRecord(raw.value)
  return runtimeContractRequiredFields.value.filter((field) => !(field in payload))
})
const runtimeContractMissingNested = computed(() =>
  asArray(runtimeContractValidation.value.missing_nested).map((item) => asString(item)).filter(Boolean),
)
const runtimeSurfaceKey = computed(() => {
  if (props.surface === 'duty-roster') return 'duty_roster_graph'
  if (props.surface === 'employee-space') return 'employee_space'
  return 'self_evolution_loop_runtime'
})
const runtimeSurfaceReadiness = computed<AnyRecord>(() =>
  asRecord(asRecord(runtimeContractValidation.value.surface_readiness)[runtimeSurfaceKey.value]),
)
const runtimeSurfaceReadinessOk = computed(() => runtimeSurfaceReadiness.value.ok === true)
const runtimeSurfaceMissing = computed(() =>
  asArray(runtimeSurfaceReadiness.value.missing).map((item) => asString(item)).filter(Boolean),
)
const runtimeAllSurfaceIncidents = computed(() =>
  asArray(runtimeContractValidation.value.surface_incidents)
    .map((item) => asRecord(item))
    .filter((item) => firstText(item.surface, item.action)),
)
const runtimeSurfaceIncidentSummary = computed<AnyRecord>(() =>
  asRecord(runtimeContractValidation.value.surface_incident_summary),
)
const runtimeContractStatus = computed<AnyRecord>(() => {
  const topLevel = asRecord(raw.value?.contract_status)
  return Object.keys(topLevel).length
    ? topLevel
    : asRecord(runtimeContractValidation.value.contract_status)
})
const runtimeContractPrimaryRoute = computed<AnyRecord>(() =>
  asRecord(runtimeContractStatus.value.primary_route),
)
const DUTY_ROSTER_VIEW_TOKENS = new Set(['department', 'dept', '六部门', 'hub', 'center', '中心', '中心图', 'legacy-area', 'area', '物理', '物理分区', 'client', 'workshop', '车间', '客户端车间'])

function normalizeDutyRosterView(raw: unknown): string {
  const token = firstText(raw, '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}
const runtimeContractRouteEmployeeId = computed(() =>
  firstText(runtimeContractPrimaryRoute.value.employee_id, asArray(runtimeContractPrimaryRoute.value.target_employee_ids)[0]),
)
const runtimeContractDutyRosterLocation = computed(() => {
  if (!uiBridgeDutyRosterLocation.value) return null
  const employeeId = runtimeContractRouteEmployeeId.value
  const view = normalizeDutyRosterView(runtimeContractPrimaryRoute.value.view)
  if (!employeeId) return uiBridgeDutyRosterLocation.value
  return {
    ...(uiBridgeDutyRosterLocation.value as Record<string, unknown>),
    query: { view, employee: employeeId },
  }
})
const runtimeContractEmployeeSpaceLocation = computed(() => {
  if (!uiBridgeEmployeeSpaceLocation.value) return null
  const employeeId = runtimeContractRouteEmployeeId.value
  if (!employeeId) return uiBridgeEmployeeSpaceLocation.value
  return {
    ...(uiBridgeEmployeeSpaceLocation.value as Record<string, unknown>),
    query: { employee: employeeId },
  }
})
const runtimeSurfaceIncidents = computed(() =>
  runtimeAllSurfaceIncidents.value.filter((item) => asString(item.surface) === runtimeSurfaceKey.value),
)
const runtimeSurfaceIncident = computed<AnyRecord>(() => runtimeSurfaceIncidents.value[0] || {})
const runtimeContractSurfaces = computed(() =>
  asArray(runtimeContract.value.surfaces).map((item) => asString(item)).filter(Boolean),
)
const runtimeContractGateDependencies = computed(() =>
  asArray(runtimeContract.value.gate_dependencies).map((item) => asString(item)).filter(Boolean),
)
const runtimeContractOk = computed(() =>
  runtimeSchemaVersion.value === 'self_maintenance_runtime.v1'
  && runtimeContractRequiredFields.value.length > 0
  && runtimeContractMissingFields.value.length === 0
  && runtimeSurfaceReadinessOk.value
)
const kbSummary = computed<AnyRecord>(() => asRecord(raw.value?.kb_summary))
const evolutionMetrics = computed<AnyRecord>(() => asRecord(raw.value?.evolution_metrics_summary))
const rosterAlignment = computed<AnyRecord>(() => asRecord(raw.value?.roster_alignment))
const currentGovernanceGate = computed<AnyRecord>(() => asRecord(raw.value?.governance_gate))
const uiBridge = computed<AnyRecord>(() => asRecord(raw.value?.ui_bridge))
const governanceAudit = computed<AnyRecord>(() => asRecord(raw.value?.governance_audit))
const governanceAuditSummary = computed<AnyRecord>(() => asRecord(governanceAudit.value.summary))
const governanceAuditLast = computed<AnyRecord>(() => asRecord(governanceAudit.value.last))
const governanceAuditRecent = computed(() =>
  asArray(governanceAudit.value.recent)
    .map((item) => asRecord(item))
    .filter((item) => firstText(item.action, item.created_at)),
)
const employeeSpaceBridge = computed<AnyRecord>(() => asRecord(uiBridge.value.employee_space))
const dutyRosterBridge = computed<AnyRecord>(() => asRecord(uiBridge.value.duty_roster_graph))
const uiBridgeGovernanceAction = computed<AnyRecord>(() => asRecord(uiBridge.value.governance_action))
const uiBridgeAllowedSurfaces = computed(() =>
  asArray(uiBridgeGovernanceAction.value.allowed_surfaces).map((item) => asString(item)).filter(Boolean),
)
const currentGovernanceSurface = computed(() =>
  props.surface === 'duty-roster' ? 'duty_roster_graph' : 'employee_space',
)
const canReviewGovernanceAudit = computed(() =>
  !governanceReviewBusy.value
  && uiBridgeGovernanceAction.value.requires_admin === true
  && props.surface === 'duty-roster'
  && currentGovernanceSurface.value === 'duty_roster_graph'
  && uiBridgeAllowedSurfaces.value.includes('duty_roster_graph')
  && (
    governanceAuditSummary.value.health === 'bad'
    || uiBridge.value.state === 'governance_degraded'
    || uiBridgeGovernanceAction.value.id === 'inspect_governance_audit'
  ),
)
const uiBridgeTargets = computed(() =>
  asArray(uiBridge.value.target_employee_ids).map((id) => asString(id)).filter(Boolean),
)
const uiBridgeBlockedIds = computed(() =>
  asArray(uiBridge.value.blocked_employee_ids).map((id) => asString(id)).filter(Boolean),
)
const uiBridgePrimaryEmployeeId = computed(() =>
  firstText(uiBridge.value.primary_employee_id, uiBridgeTargets.value[0]),
)
const uiBridgeActions = computed(() =>
  asArray(uiBridge.value.next_actions).map((action) => asString(action)).filter(Boolean),
)
const uiBridgePath = computed(() =>
  asArray(uiBridge.value.handoff_path)
    .map((item) => asRecord(item))
    .map((item) => firstText(item.surface, item.role))
    .filter(Boolean),
)
const uiBridgeVisible = computed(() =>
  Boolean(firstText(uiBridge.value.state, uiBridge.value.title, employeeSpaceBridge.value.title, dutyRosterBridge.value.title)),
)
const governanceAuditLastTargets = computed(() =>
  asArray(governanceAuditLast.value.target_employee_ids).map((id) => asString(id)).filter(Boolean),
)
const governanceAuditLastSummary = computed(() => {
  const summary = asRecord(governanceAuditLast.value.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  return ''
})
function governanceSummaryText(row: AnyRecord): string {
  const summary = asRecord(row.onboard_summary)
  const onboarded = Number(summary.onboarded)
  const skipped = Number(summary.skipped)
  const failed = Number(summary.failed)
  if ([onboarded, skipped, failed].every((n) => Number.isFinite(n))) {
    return `onboarded ${onboarded} · skipped ${skipped} · failed ${failed}`
  }
  return firstText(row.status, row.ok === false ? 'failed' : 'success')
}
const uiBridgeDutyRosterLocation = computed<RouteLocationRaw | null>(() => {
  if (!router.hasRoute('duty-roster-graph')) return null
  const view = normalizeDutyRosterView(uiBridge.value.primary_view)
  const employee = uiBridgePrimaryEmployeeId.value
  return {
    name: 'duty-roster-graph',
    query: employee ? { view, employee } : { view },
  }
})
const uiBridgeEmployeeSpaceLocation = computed<RouteLocationRaw | null>(() => {
  if (!router.hasRoute('workflow-employee-space')) return null
  const employee = uiBridgePrimaryEmployeeId.value
  return {
    name: 'workflow-employee-space',
    query: employee ? { employee } : {},
  }
})
const latestComplete = computed<AnyRecord>(() => asRecord(evidence.value.latest_complete))
const latestSkip = computed<AnyRecord>(() => asRecord(evidence.value.latest_skip))
const lastRun = computed<AnyRecord>(() => {
  const fromMemory = asRecord(memory.value.last_run)
  if (Object.keys(fromMemory).length) return fromMemory
  if (Object.keys(latestComplete.value).length) return latestComplete.value
  return latestSkip.value
})
const decision = computed<AnyRecord>(() => asRecord(memory.value.last_policy_decision))
const mergeDecision = computed<AnyRecord>(() => {
  const structured = asRecord(raw.value?.merge_decision)
  if (Object.keys(structured).length) return structured
  return {
    action: firstText(decision.value.action),
    reason: firstText(decision.value.reason),
    risk_score_v1: asRecord(decision.value.risk_score),
    safety_score_v2: asRecord(decision.value.safety_score_v2),
    safety_score_v3: asRecord(decision.value.safety_score_v3),
    roster_gate: asRecord(decision.value.roster_gate),
    qa_verdict: firstText(asRecord(decision.value.qa).verdict),
    review_max_severity: firstText(asRecord(decision.value.review).max_severity),
  }
})
const openRunIds = computed(() => asArray(evidence.value.open_run_ids).map((x) => asString(x)).filter(Boolean))
const openItems = computed(() => asArray(memory.value.open_items))
const recentRuns = computed(() => asArray(memory.value.recent_runs))

function collectEmployeeMentions(value: unknown, out: Map<string, { id: string; stage: string; source: string }>, source: string) {
  if (value == null) return
  if (typeof value === 'string') {
    const match = value.match(/\b[a-z][a-z0-9]+(?:-[a-z0-9]+)+\b/g) || []
    for (const id of match) {
      if (!out.has(id)) out.set(id, { id, stage: 'mentioned', source })
    }
    return
  }
  if (Array.isArray(value)) {
    for (const item of value) collectEmployeeMentions(item, out, source)
    return
  }
  if (typeof value !== 'object') return
  const row = value as AnyRecord
  const id = firstText(row.employee_id, row.employeeId, row.emp_id, row.empId, row.actor, row.assignee)
  if (id && id.includes('-')) {
    out.set(id, {
      id,
      stage: firstText(row.step, row.stage, row.role, row.phase, row.status, 'loop'),
      source,
    })
  }
  for (const [key, child] of Object.entries(row)) {
    if (key === 'prompt' || key === 'report' || key === 'result' || key === 'steps' || key === 'nodes') {
      collectEmployeeMentions(child, out, source)
    }
  }
}

const structuredParticipants = computed(() =>
  asArray(raw.value?.participants)
    .map((item) => {
      const row = asRecord(item)
      const id = firstText(row.employee_id, row.id)
      if (!id) return null
      const role = firstText(row.role_label, row.role)
      const stage = asArray(row.stage_labels).map((x) => asString(x)).filter(Boolean).join(' / ')
        || asArray(row.stages).map((x) => asString(x)).filter(Boolean).join(' / ')
        || 'loop'
      return {
        id,
        stage: role ? `${role} · ${stage}` : stage,
        source: asArray(row.sources).map((x) => asString(x)).filter(Boolean).join(' / ') || 'participants',
        rosterLabel: firstText(row.roster_label, row.roster_status),
        rosterStatus: firstText(row.roster_status),
        dutyRegisteredLabel: firstText(row.duty_registered_label),
        dutyRegistered: row.duty_registered,
        department: firstText(row.department_label, row.department_key),
      }
    })
    .filter(Boolean) as Array<{ id: string; stage: string; source: string; rosterLabel?: string; rosterStatus?: string; dutyRegisteredLabel?: string; dutyRegistered?: unknown; department?: string }>,
)

const teamLanes = computed(() => {
  if (structuredParticipants.value.length) return structuredParticipants.value.slice(0, 12)
  const found = new Map<string, { id: string; stage: string; source: string; rosterLabel?: string; rosterStatus?: string; dutyRegisteredLabel?: string; dutyRegistered?: unknown; department?: string }>()
  collectEmployeeMentions(evidence.value.steps_by_open_run, found, 'open run')
  collectEmployeeMentions(evidence.value.recent_rows, found, 'ledger')
  collectEmployeeMentions(memory.value.last_run, found, 'last run')
  collectEmployeeMentions(memory.value.recent_runs, found, 'memory')
  return Array.from(found.values()).slice(0, 12)
})

const runTimeline = computed(() => {
  const timelines = asArray(raw.value?.run_timelines).map((item) => asRecord(item))
  const open = timelines.find((item) => item.open === true)
  const picked = open || timelines[timelines.length - 1]
  if (!picked) return null
  const items = asArray(picked.items).map((item) => asRecord(item))
  const md = mergeDecision.value
  if (md.action || md.reason) {
    items.push({
      phase: 'policy',
      step: 'risk_gate',
      label: 'Risk / Merge Gate',
      status: firstText(md.action, md.reason),
      reason: firstText(md.reason),
      qa_verdict: firstText(md.qa_verdict),
      review_max_severity: firstText(md.review_max_severity),
    })
  }
  return {
    runId: firstText(picked.run_id),
    open: picked.open === true,
    items,
  }
})

const statusTone = computed(() => {
  if (error.value) return 'bad'
  if (openRunIds.value.length > 0) return 'running'
  if (gate.value.should_run === true) return 'warn'
  if (asString(latestComplete.value.phase) === 'complete') return 'ok'
  return 'idle'
})

const statusLabel = computed(() => {
  if (error.value) return '接口异常'
  if (openRunIds.value.length > 0) return '运行中'
  if (gate.value.should_run === true) return '达到触发阈值'
  if (asString(gate.value.reason) === 'cooldown') return '冷却中'
  if (asString(latestComplete.value.phase) === 'complete') return '最近完成'
  return '待命'
})

const cronLine = computed(() => {
  const hour = asNumber(cron.value.hour, 3)
  const minute = asNumber(cron.value.minute, 0)
  const tz = firstText(cron.value.timezone, 'Asia/Shanghai')
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')} ${tz}`
})

const decisionCards = computed(() => {
  const md = mergeDecision.value
  const cards = [
    {
      key: 'action',
      label: 'Action',
      value: firstText(md.action, '等待决策'),
      sub: firstText(md.reason, 'policy pending'),
    },
  ]
  const v1 = asRecord(md.risk_score_v1)
  const v2 = asRecord(md.safety_score_v2)
  const v3 = asRecord(md.safety_score_v3)
  const roster = asRecord(md.roster_gate)
  const governance = Object.keys(asRecord(md.governance_gate)).length
    ? asRecord(md.governance_gate)
    : currentGovernanceGate.value
  const evolution = asRecord(md.evolution_gate)
  if (v1.score != null) cards.push({
    key: 'v1',
    label: 'V1 风险分',
    value: String(v1.score),
    sub: `max ${v1.max_allowed ?? '—'} · ${firstText(v1.reason, v1.source, '')}`,
  })
  if (v2.score != null) cards.push({
    key: 'v2',
    label: 'V2 安全分',
    value: String(v2.score),
    sub: `min ${v2.min_allowed ?? '—'} · ${firstText(v2.reason, v2.source, '')}`,
  })
  if (v3.score != null) cards.push({
    key: 'v3',
    label: 'V3 安全分',
    value: String(v3.score),
    sub: `min ${v3.min_allowed ?? '—'} · ${firstText(v3.reason, v3.source, '')}`,
  })
  if (md.qa_verdict || md.review_max_severity) cards.push({
    key: 'qa',
    label: 'QA / Review',
    value: firstText(md.qa_verdict, '—'),
    sub: md.review_max_severity ? `review ${md.review_max_severity}` : 'structured gate',
  })
  if (Object.keys(roster).length) cards.push({
    key: 'roster',
    label: 'Roster Gate',
    value: firstText(roster.action, roster.ok === true ? 'allow' : 'blocked'),
    sub: firstText(roster.reason, roster.policy, 'roster policy'),
  })
  if (Object.keys(governance).length) cards.push({
    key: 'governance',
    label: 'Governance Gate',
    value: firstText(governance.action, governance.ok === true ? 'allow' : 'blocked'),
    sub: firstText(
      governance.reason,
      asRecord(governance.summary).health,
      governance.policy,
      'governance audit policy',
    ),
  })
  if (Object.keys(evolution).length) cards.push({
    key: 'evolution',
    label: 'Evolution Gate',
    value: evolution.pause === true ? 'pause' : 'allow',
    sub: firstText(evolution.reason, `history ${evolution.history_count ?? 0}`, 'evolution metrics policy'),
  })
  return cards
})

const kbCards = computed(() => {
  const kb = kbSummary.value
  const redis = asRecord(kb.redisvl_status)
  return [
    {
      key: 'redisvl',
      label: 'RedisVL',
      value: redis.ready === true ? 'ready' : 'not ready',
      sub: firstText(redis.reason, redis.error, redis.backend, 'vector index'),
      tone: redis.ready === true ? 'ok' : 'warn',
    },
    {
      key: 'fix',
      label: '修复知识命中',
      value: String(asNumber(kb.fix_hit_count, 0)),
      sub: firstText(kb.engine, 'KB search'),
      tone: asNumber(kb.fix_hit_count, 0) > 0 ? 'ok' : 'idle',
    },
    {
      key: 'pattern',
      label: '代码模式命中',
      value: String(asNumber(kb.pattern_hit_count, 0)),
      sub: firstText(kb.kb_root, 'FHD/XCAGI/kb'),
      tone: asNumber(kb.pattern_hit_count, 0) > 0 ? 'ok' : 'idle',
    },
  ]
})

const kbHitLines = computed(() => {
  const fixes = asArray(kbSummary.value.top_fix_hits).map((item) => {
    const row = asRecord(item)
    return firstText(row.symptom, row.root_cause, row.path)
  }).filter(Boolean)
  const patterns = asArray(kbSummary.value.top_pattern_hits).map((item) => {
    const row = asRecord(item)
    return firstText(row.pattern, row.summary, row.path)
  }).filter(Boolean)
  return [...fixes, ...patterns].slice(0, 5)
})

const kbFixHitDetails = computed(() =>
  asArray(kbSummary.value.top_fix_hits).map((item) => asRecord(item)).slice(0, 3),
)

const kbPatternHitDetails = computed(() =>
  asArray(kbSummary.value.top_pattern_hits).map((item) => asRecord(item)).slice(0, 3),
)

const proactiveSignals = computed<AnyRecord>(() => asRecord(gate.value.proactive_signals))
const proactiveCandidates = computed(() =>
  asArray(proactiveSignals.value.candidates)
    .map((item) => asRecord(item))
    .slice(0, 6),
)

const proactiveCards = computed(() => {
  const count = asNumber(gate.value.proactive_task_count, proactiveCandidates.value.length)
  const kinds = new Set(
    proactiveCandidates.value
      .map((item) => firstText(item.task_type, item.kind, item.category, item.signal_type))
      .filter(Boolean),
  )
  return [
    {
      key: 'count',
      label: '主动优化候选',
      value: String(count),
      sub: count > 0 ? '已进入自进化信号池' : '暂无候选',
      tone: count > 0 ? 'ok' : 'idle',
    },
    {
      key: 'types',
      label: '任务类型',
      value: String(kinds.size),
      sub: Array.from(kinds).slice(0, 3).join(' / ') || 'performance / coverage / debt',
      tone: kinds.size > 0 ? 'ok' : 'idle',
    },
    {
      key: 'source',
      label: '信号源',
      value: firstText(proactiveSignals.value.source, proactiveSignals.value.engine, 'scripts/dev'),
      sub: firstText(proactiveSignals.value.generated_at, proactiveSignals.value.checked_at, 'runtime scan'),
      tone: 'idle',
    },
  ]
})

function proactiveCandidateTitle(item: Record<string, unknown>): string {
  return firstText(
    item.title,
    item.summary,
    item.reason,
    item.module,
    item.path,
    item.file,
    item.task_type,
    '主动优化候选',
  )
}

function proactiveCandidateMeta(item: Record<string, unknown>): string {
  return [
    firstText(item.task_type, item.kind, item.category, item.signal_type),
    firstText(item.source, item.script, item.metric),
    item.score != null ? `score ${item.score}` : '',
  ].filter(Boolean).join(' · ') || 'proactive signal'
}

const metricWindows = computed(() =>
  asArray(evolutionMetrics.value.windows).map((item) => asRecord(item)).slice(-2),
)

const rosterCoverage = computed(() =>
  asArray(rosterAlignment.value.department_coverage)
    .map((item) => asRecord(item))
    .filter((item) => String(item.key || item.label || '').trim()),
)

const rosterGate = computed<AnyRecord>(() => asRecord(rosterAlignment.value.gate))
const rosterRemediation = computed<AnyRecord>(() => asRecord(rosterAlignment.value.remediation))

const rosterAlignmentCards = computed(() => [
  {
    key: 'planned',
    label: '编制基线',
    value: `${rosterAlignment.value.planned_count ?? '—'}`,
    sub: firstText(rosterAlignment.value.source, 'duty_roster.py'),
    tone: 'ok',
  },
  {
    key: 'participants',
    label: 'Loop 编制命中',
    value: `${rosterAlignment.value.in_roster_count ?? '—'}`,
    sub: `runtime participants ${rosterAlignment.value.participant_count ?? 0}`,
    tone: Number(rosterAlignment.value.in_roster_count || 0) > 0 ? 'run' : 'warn',
  },
  {
    key: 'deployed',
    label: 'Loop 上岗命中',
    value: `${rosterAlignment.value.in_deployed_count ?? '—'}`,
    sub: `registered duty ${rosterAlignment.value.deployed_count ?? 0}`,
    tone: Number(rosterAlignment.value.in_deployed_count || 0) > 0 ? 'run' : 'warn',
  },
  {
    key: 'outside',
    label: '非编制混入',
    value: `${rosterAlignment.value.out_of_roster_count ?? 0}`,
    sub: asArray(rosterAlignment.value.out_of_roster_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '未混入',
    tone: Number(rosterAlignment.value.out_of_roster_count || 0) > 0 ? 'bad' : 'ok',
  },
  {
    key: 'not-deployed',
    label: '未登记上岗',
    value: `${rosterAlignment.value.not_deployed_count ?? 0}`,
    sub: asArray(rosterAlignment.value.not_deployed_ids).map((id) => String(id)).filter(Boolean).slice(0, 3).join(' / ') || '全部已登记',
    tone: Number(rosterAlignment.value.not_deployed_count || 0) > 0 ? 'bad' : 'ok',
  },
  {
    key: 'coverage',
    label: '部门覆盖',
    value: `${rosterCoverage.value.length}`,
    sub: firstText(rosterAlignment.value.status, 'roster alignment'),
    tone: rosterCoverage.value.length > 0 ? 'run' : 'warn',
  },
  {
    key: 'gate',
    label: '隔离策略',
    value: firstText(rosterGate.value.action, '—'),
    sub: firstText(rosterGate.value.reason, rosterGate.value.policy, 'roster gate'),
    tone: rosterGate.value.blocking === true ? 'bad' : rosterGate.value.action === 'allow' ? 'ok' : 'warn',
  },
])

const evolutionMetricCards = computed(() => {
  const latest = metricWindows.value[metricWindows.value.length - 1] || {}
  return [
    {
      key: 'pause',
      label: '自进化状态',
      value: evolutionMetrics.value.pause === true ? '暂停' : '允许运行',
      sub: firstText(evolutionMetrics.value.reason, 'metrics gate'),
      tone: evolutionMetrics.value.pause === true ? 'bad' : 'ok',
    },
    {
      key: 'coverage',
      label: '覆盖率变化',
      value: latest.coverage_delta == null ? '—' : `${latest.coverage_delta}`,
      sub: `${firstText(latest.from_week, 'from')} → ${firstText(latest.to_week, 'to')}`,
      tone: latest.coverage_delta != null && Number(latest.coverage_delta) >= 0.5 ? 'ok' : 'warn',
    },
    {
      key: 'pytest',
      label: 'pytest 通过数',
      value: latest.passed_delta == null ? '—' : `${latest.passed_delta}`,
      sub: `history ${evolutionMetrics.value.history_count ?? 0}`,
      tone: latest.passed_delta != null && Number(latest.passed_delta) >= 0 ? 'ok' : 'warn',
    },
    {
      key: 'debt',
      label: '类型债务变化',
      value: latest.debt_delta == null ? '—' : `${latest.debt_delta}`,
      sub: firstText(evolutionMetrics.value.metrics_path, 'evolution_metrics.jsonl'),
      tone: latest.debt_delta != null && Number(latest.debt_delta) <= -5 ? 'ok' : 'warn',
    },
  ]
})

const signalCount = computed(() => asNumber(gate.value.signal_count, 0))
const threshold = computed(() => asNumber(gate.value.threshold, asNumber(policy.value.threshold, 1)))
const riskScore = computed(() => {
  const v3 = asRecord(decision.value.safety_score_v3)
  const v2 = asRecord(decision.value.safety_score_v2)
  const v1 = asRecord(decision.value.risk_score)
  if (v3.score != null) return { label: 'V3 安全分', value: asNumber(v3.score), goodHigh: true }
  if (v2.score != null) return { label: 'V2 安全分', value: asNumber(v2.score), goodHigh: true }
  if (v1.score != null) return { label: 'V1 风险分', value: asNumber(v1.score), goodHigh: false }
  return null
})

const qaVerdict = computed(() => {
  const qa = asRecord(decision.value.qa)
  const reviewGate = asRecord(decision.value.structured_gate)
  return firstText(qa.verdict, reviewGate.qa_verdict, lastRun.value.qa_verdict, '待回写')
})

const paraTaskId = computed(() =>
  firstText(
    lastRun.value.para_task_id,
    asRecord(lastRun.value.result).para_task_id,
    asRecord(decision.value.final).para_task_id,
  ),
)

const branchName = computed(() =>
  firstText(
    lastRun.value.branch,
    lastRun.value.target_branch,
    asRecord(decision.value.final).branch,
  ),
)

const actionLabel = computed(() =>
  firstText(decision.value.action, lastRun.value.action, lastRun.value.status, latestSkip.value.reason, '等待决策'),
)

const loopStages = computed(() => [
  {
    key: 'signals',
    title: '信号感知',
    value: `${signalCount.value}/${threshold.value}`,
    meta: firstText(gate.value.reason, 'below_threshold'),
    tone: signalCount.value >= threshold.value ? 'warn' : 'idle',
  },
  {
    key: 'incident',
    title: 'Incident 入池',
    value: String(asNumber(gate.value.incident_count, 0)),
    meta: `${asNumber(gate.value.lookback_hours, 24)}h 窗口`,
    tone: asNumber(gate.value.incident_count, 0) > 0 ? 'running' : 'idle',
  },
  {
    key: 'team',
    title: '三员工执行',
    value: openRunIds.value.length ? `${openRunIds.value.length} 轮` : '待命',
    meta: 'Scout / Fix / QA',
    tone: openRunIds.value.length ? 'running' : 'idle',
  },
  {
    key: 'qa',
    title: 'QA JSON',
    value: qaVerdict.value,
    meta: '结构化门禁',
    tone: qaVerdict.value === 'PASS' ? 'ok' : qaVerdict.value === 'FAIL' ? 'bad' : 'idle',
  },
  {
    key: 'risk',
    title: 'Risk Gate',
    value: riskScore.value ? String(riskScore.value.value) : '待评分',
    meta: riskScore.value?.label || 'V1/V2/V3',
    tone: riskScore.value ? 'ok' : 'idle',
  },
  {
    key: 'merge',
    title: '合并/审批',
    value: actionLabel.value,
    meta: branchName.value || 'branch 待回写',
    tone: /merge|merged|pass|auto/i.test(actionLabel.value) ? 'ok' : 'idle',
  },
])

const evidenceCards = computed(() => [
  { label: 'Para task', value: paraTaskId.value || '无进行中任务' },
  { label: 'Open items', value: String(openItems.value.length) },
  { label: 'Recent runs', value: String(recentRuns.value.length) },
  { label: 'Cooldown', value: `${asNumber(policy.value.cooldown_minutes, 360)} min` },
])

const openApprovalItems = computed(() =>
  openItems.value
    .map((item) => asRecord(item))
    .filter((item) => firstText(item.kind, item.reason, item.run_id))
    .slice(-5)
    .reverse(),
)
</script>

<template>
  <section class="selp" :class="[`selp--${statusTone}`, { 'selp--compact': compact }]" aria-label="自进化 loop 运行状态">
    <div class="selp-head">
      <div>
        <p class="selp-kicker">Self-Evolution Loop</p>
        <h3 class="selp-title">自维护 / 自进化真实运行线</h3>
        <p class="selp-desc">
          读取后端 self-maintenance ledger、gate、policy 与 memory；不是静态演示。
        </p>
      </div>
      <div class="selp-state">
        <span class="selp-state-dot" aria-hidden="true" />
        <strong>{{ statusLabel }}</strong>
        <button type="button" class="selp-refresh" :disabled="loading" @click="refresh">
          {{ loading ? '刷新中' : '刷新' }}
        </button>
      </div>
    </div>

    <p v-if="error" class="selp-error">{{ error }}</p>

    <div class="selp-meta" role="list" aria-label="loop 调度与证据">
      <div class="selp-meta-card" role="listitem">
        <span>每日调度</span>
        <strong>{{ cronLine }}</strong>
      </div>
      <div v-for="card in evidenceCards" :key="card.label" class="selp-meta-card" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <button
          v-if="card.label === 'Para task' && paraTaskId"
          type="button"
          class="selp-copy"
          @click="copyParaTaskId"
        >
          {{ paraCopied ? '已复制' : '复制 ID' }}
        </button>
      </div>
    </div>

    <div v-if="uiBridgeVisible" class="selp-ui-bridge" :class="`selp-ui-bridge--${firstText(uiBridge.tone, 'ok')}`">
      <div class="selp-ui-bridge-main">
        <span>UI Bridge · {{ firstText(uiBridge.state, 'runtime') }}</span>
        <strong>{{ firstText(uiBridge.title, 'Loop 桥接状态') }}</strong>
        <small>{{ firstText(uiBridge.detail, '后端 runtime 正在统一员工空间、编制图谱和完整 Loop 的展示意图。') }}</small>
        <div class="selp-ui-bridge-actions">
          <router-link v-if="uiBridgeDutyRosterLocation" :to="uiBridgeDutyRosterLocation">去编制图谱</router-link>
          <router-link v-if="uiBridgeEmployeeSpaceLocation" :to="uiBridgeEmployeeSpaceLocation">去员工空间</router-link>
          <button
            v-if="canReviewGovernanceAudit || governanceReviewBusy"
            type="button"
            :disabled="governanceReviewBusy"
            @click="reviewGovernanceAudit"
          >
            {{ governanceReviewBusy ? '复核中...' : '人工复核治理审计' }}
          </button>
        </div>
        <small v-if="governanceReviewResult" class="selp-ui-bridge-review selp-ui-bridge-review--ok">
          治理审计已复核：{{ asRecord(governanceReviewResult.summary).health || 'ok' }}
        </small>
        <small v-if="governanceReviewError" class="selp-ui-bridge-review selp-ui-bridge-review--bad">
          {{ governanceReviewError }}
        </small>
      </div>
      <div class="selp-ui-bridge-surfaces" role="list" aria-label="三端职责">
        <div role="listitem">
          <span>员工空间</span>
          <strong>{{ firstText(employeeSpaceBridge.role, 'execution_surface') }}</strong>
          <small>{{ firstText(employeeSpaceBridge.cta, '看执行现场') }}</small>
        </div>
        <div role="listitem">
          <span>编制图谱</span>
          <strong>{{ firstText(dutyRosterBridge.role, 'governance_surface') }}</strong>
          <small>{{ firstText(dutyRosterBridge.cta, '查看编制准入') }}</small>
        </div>
        <div role="listitem">
          <span>主动作</span>
          <strong>{{ firstText(uiBridgeGovernanceAction.label, uiBridge.primary_action, 'observe') }}</strong>
          <small>{{ firstText(uiBridgeGovernanceAction.status, uiBridge.primary_surface, 'self_evolution_loop') }} · {{ firstText(uiBridgeGovernanceAction.view, uiBridge.primary_view, 'department') }}</small>
        </div>
        <div role="listitem">
          <span>目标员工</span>
          <strong>{{ firstText(uiBridge.primary_employee_id, uiBridgeTargets[0], '—') }}</strong>
          <small>{{ uiBridgeTargets.length ? `targets ${uiBridgeTargets.length}` : '无定向目标' }}</small>
        </div>
      </div>
      <div v-if="uiBridgeActions.length || uiBridgeTargets.length" class="selp-ui-bridge-foot">
        <span v-if="uiBridgePath.length">path: {{ uiBridgePath.join(' -> ') }}</span>
        <span v-if="uiBridgeGovernanceAction.id">governance: {{ uiBridgeGovernanceAction.id }} · {{ uiBridgeGovernanceAction.requires_admin === true ? 'admin-only' : (uiBridgeGovernanceAction.executable === false ? 'view-only' : 'executable') }}</span>
        <span v-if="uiBridgeActions.length">{{ uiBridgeActions.slice(0, 4).join(' / ') }}</span>
        <small v-if="uiBridgeBlockedIds.length">isolated: {{ uiBridgeBlockedIds.slice(0, 8).join(' / ') }}</small>
        <small v-if="uiBridgeTargets.length">targets: {{ uiBridgeTargets.slice(0, 8).join(' / ') }}</small>
        <small v-if="governanceAuditLast.action">
          last governance: {{ governanceAuditLast.action }} · {{ governanceAuditLast.status || (governanceAuditLast.ok === false ? 'failed' : 'success') }}<template v-if="governanceAuditLastSummary"> · {{ governanceAuditLastSummary }}</template><template v-if="governanceAuditLastTargets.length"> · {{ governanceAuditLastTargets.slice(0, 4).join(' / ') }}</template>
        </small>
      </div>
    </div>

    <div class="selp-contract" :class="runtimeContractOk ? 'selp-contract--ok' : 'selp-contract--bad'" aria-label="Runtime contract">
      <div class="selp-contract-head">
        <span>Runtime contract</span>
        <strong>{{ runtimeContractOk ? 'trusted' : 'blocked' }} · {{ runtimeSchemaVersion }}</strong>
        <small>
          required {{ runtimeContractValidation.required_count ?? runtimeContractRequiredFields.length }} · missing {{ runtimeContractMissingFields.length + runtimeSurfaceMissing.length }}
          <template v-if="runtimeContractMissingFields.length"> · {{ runtimeContractMissingFields.slice(0, 5).join(' / ') }}</template>
          <template v-else-if="runtimeSurfaceMissing.length"> · {{ runtimeSurfaceMissing.slice(0, 5).join(' / ') }}</template>
        </small>
      </div>
      <div class="selp-contract-grid">
        <div class="selp-contract-primary">
          <span>Primary state</span>
          <strong>{{ firstText(runtimeContractStatus.state, runtimeSurfaceIncidentSummary.status, runtimeContractOk ? 'trusted' : 'blocked') }}</strong>
          <small>{{ firstText(runtimeContractPrimaryRoute.action, runtimeContractStatus.primary_action, runtimeSurfaceIncidentSummary.primary_action, runtimeSurfaceReadiness.action, runtimeContractOk ? 'all clear' : 'inspect contract') }} -> {{ firstText(runtimeContractPrimaryRoute.surface, runtimeContractStatus.primary_target_surface, 'self_evolution_loop_runtime') }}</small>
          <small v-if="firstText(runtimeContractPrimaryRoute.employee_id, asArray(runtimeContractPrimaryRoute.target_employee_ids)[0])">target employee · {{ firstText(runtimeContractPrimaryRoute.employee_id, asArray(runtimeContractPrimaryRoute.target_employee_ids)[0]) }}</small>
          <small>global={{ runtimeContractStatus.global_ok === false ? 'blocked' : 'ok' }} · all_surfaces={{ runtimeContractStatus.all_surfaces_ok === false ? 'blocked' : 'ok' }}</small>
          <small>{{ runtimeContractPrimaryRoute.requires_admin ? 'admin-only' : 'operator' }} · {{ runtimeContractPrimaryRoute.executable ? 'executable' : 'navigate-only' }} · {{ firstText(runtimeContractPrimaryRoute.detail, 'route supplied by backend contract_status') }}</small>
          <router-link
            v-if="runtimeContractPrimaryRoute.surface === 'duty_roster_graph' && runtimeContractDutyRosterLocation"
            :to="runtimeContractDutyRosterLocation"
          >
            {{ firstText(runtimeContractPrimaryRoute.label, '打开目标面') }}
          </router-link>
          <router-link
            v-else-if="runtimeContractPrimaryRoute.surface === 'employee_space' && runtimeContractEmployeeSpaceLocation"
            :to="runtimeContractEmployeeSpaceLocation"
          >
            {{ firstText(runtimeContractPrimaryRoute.label, '打开目标面') }}
          </router-link>
          <small v-else>route fallback · {{ firstText(runtimeContractPrimaryRoute.view, 'department') }}</small>
        </div>
        <div>
          <span>Surfaces</span>
          <strong>{{ runtimeContractSurfaces.length || 0 }}</strong>
          <small>{{ runtimeContractSurfaces.join(' / ') || 'contract.surfaces missing' }}</small>
        </div>
        <div>
          <span>Gate deps</span>
          <strong>{{ runtimeContractGateDependencies.length || 0 }}</strong>
          <small>{{ runtimeContractGateDependencies.slice(0, 4).join(' / ') || 'contract.gate_dependencies missing' }}</small>
        </div>
        <div>
          <span>Policy</span>
          <strong>{{ runtimeContractOk ? 'allow view' : 'do not trust' }}</strong>
          <small>完整 Loop 面板与员工空间、编制图谱共用同一 contract guard。</small>
        </div>
        <div>
          <span>Surface ready</span>
          <strong>{{ runtimeSurfaceReadinessOk ? 'ready' : 'blocked' }}</strong>
          <small>{{ runtimeSurfaceMissing.length ? `${runtimeSurfaceReadiness.action || 'repair'} · ${runtimeSurfaceMissing.slice(0, 3).join(' / ')}` : (runtimeSurfaceReadiness.title || runtimeSurfaceKey) }}</small>
        </div>
        <div>
          <span>Surface incidents</span>
          <strong>{{ runtimeSurfaceIncidents.length }} / {{ runtimeAllSurfaceIncidents.length }}</strong>
          <small>{{ runtimeSurfaceIncidents.length ? `${firstText(runtimeSurfaceIncident.action, runtimeSurfaceIncident.title, 'inspect_runtime_contract')} -> ${firstText(runtimeSurfaceIncident.target_surface, runtimeSurfaceKey)} · ${asArray(runtimeSurfaceIncident.missing).slice(0, 3).join(' / ') || runtimeSurfaceKey}` : 'current surface clear' }}</small>
        </div>
        <div>
          <span>Incident summary</span>
          <strong>{{ firstText(runtimeSurfaceIncidentSummary.status, runtimeSurfaceIncidentSummary.total ?? 0) }}</strong>
          <small>{{ firstText(runtimeSurfaceIncidentSummary.primary_action) ? `${runtimeSurfaceIncidentSummary.primary_action} -> ${firstText(runtimeSurfaceIncidentSummary.primary_target_surface, runtimeSurfaceIncidentSummary.primary_surface, 'unknown')} · total ${runtimeSurfaceIncidentSummary.total ?? 0}` : (asArray(runtimeSurfaceIncidentSummary.actions).slice(0, 3).join(' / ') || 'all surfaces clear') }}</small>
        </div>
        <div>
          <span>Global nested audit</span>
          <strong>{{ runtimeContractMissingNested.length ? `missing ${runtimeContractMissingNested.length}` : 'clear' }}</strong>
          <small>{{ runtimeContractMissingNested.length ? runtimeContractMissingNested.slice(0, 4).join(' / ') : `global=${runtimeContractValidation.global_ok === false ? 'blocked' : 'ok'} · all_surfaces=${runtimeContractValidation.all_surfaces_ok === false ? 'blocked' : 'ok'}` }}</small>
        </div>
      </div>
    </div>

    <div v-if="activeGateItems.length" class="selp-active-gates" aria-label="当前门禁总览">
      <div class="selp-active-gates-head">
        <span>Active gates</span>
        <strong>{{ activeGates.ok === false ? 'blocked' : 'clear' }}</strong>
        <small>{{ activeGates.blocking_count ?? 0 }} blocking · {{ asArray(activeGates.blocking_keys).join(' / ') || 'none' }}</small>
      </div>
      <div class="selp-active-gates-grid" role="list">
        <div
          v-for="gateItem in activeGateItems"
          :key="firstText(gateItem.key, gateItem.label)"
          class="selp-active-gate"
          :class="gateItem.blocking ? 'selp-active-gate--bad' : 'selp-active-gate--ok'"
          role="listitem"
        >
          <span>{{ gateItem.label || gateItem.key }}</span>
          <strong>{{ gateItem.status || (gateItem.ok === false ? 'blocked' : 'allow') }}</strong>
          <small>{{ firstText(gateItem.reason, gateItem.detail, 'ready') }}</small>
        </div>
      </div>
    </div>

    <div v-if="runtimeAllSurfaceIncidents.length" class="selp-contract-incidents" aria-label="Surface contract incidents">
      <div class="selp-contract-incidents-head">
        <span>Surface incidents</span>
        <strong>{{ runtimeAllSurfaceIncidents.length }}</strong>
        <small>{{ asArray(runtimeSurfaceIncidentSummary.surfaces).slice(0, 4).join(' / ') || 'contract incidents' }}</small>
      </div>
      <div class="selp-contract-incidents-grid" role="list">
        <div
          v-for="incident in runtimeAllSurfaceIncidents"
          :key="firstText(incident.id, incident.surface, incident.action)"
          class="selp-contract-incident"
          :class="`selp-contract-incident--${firstText(incident.severity, 'bad')}`"
          role="listitem"
        >
          <span>{{ firstText(incident.surface, 'surface') }} · {{ firstText(incident.severity, 'bad') }}</span>
          <strong>{{ firstText(incident.title, 'Surface contract incident') }}</strong>
          <small>{{ firstText(incident.action, 'inspect_runtime_contract') }} -> {{ firstText(incident.target_surface, 'self_evolution_loop_runtime') }}</small>
          <small>{{ incident.requires_admin ? 'admin-only' : 'operator' }} · {{ incident.executable ? 'executable' : 'navigate-only' }} · {{ firstText(incident.id, 'contract:surface') }}</small>
          <small>{{ firstText(incident.source, 'contract_validation') }} · {{ firstText(incident.schema_version, runtimeSchemaVersion) }} · {{ firstText(incident.created_at, 'time unknown') }}</small>
          <em>{{ asArray(incident.missing).map((item) => asString(item)).filter(Boolean).slice(0, 5).join(' / ') || firstText(incident.detail, 'missing dependencies') }}</em>
        </div>
      </div>
    </div>

    <div v-if="governanceAuditRecent.length" class="selp-governance-audit" aria-label="最近治理动作">
      <div class="selp-governance-audit-head">
        <span>Governance audit</span>
        <strong>{{ firstText(governanceAuditSummary.health, 'ok') }} · {{ governanceAuditRecent.length }}</strong>
        <small>{{ governanceAuditSummary.success_count ?? 0 }} ok · {{ governanceAuditSummary.failure_count ?? 0 }} failed · consecutive {{ governanceAuditSummary.consecutive_failures ?? 0 }}</small>
      </div>
      <ul>
        <li v-for="item in governanceAuditRecent.slice().reverse().slice(0, 5)" :key="`${item.created_at || item.action}-${item.exit_code ?? ''}`">
          <span>{{ item.action || 'governance' }}</span>
          <strong>{{ item.status || (item.ok === false ? 'failed' : 'success') }}</strong>
          <small>{{ governanceSummaryText(item) }}<template v-if="asArray(item.target_employee_ids).length"> · {{ asArray(item.target_employee_ids).slice(0, 3).join(' / ') }}</template></small>
        </li>
      </ul>
    </div>

    <div v-if="openApprovalItems.length" class="selp-open-items" aria-label="待处理审批与记忆项">
      <div v-for="item in openApprovalItems" :key="`${item.kind || 'item'}-${item.run_id || item.created_at}`" class="selp-open-item">
        <div>
          <span>{{ item.kind || 'open item' }}</span>
          <strong>{{ item.reason || 'pending' }}</strong>
          <small>
            <template v-if="item.run_id">run {{ item.run_id }}</template>
            <template v-if="item.task_id"> · task {{ item.task_id }}</template>
            <template v-if="item.created_at"> · {{ item.created_at }}</template>
          </small>
        </div>
        <small v-if="asRecord(item.roster_gate).action || asRecord(item.roster_gate).reason" class="selp-open-item-gate">
          roster {{ asRecord(item.roster_gate).action || 'gate' }} · {{ asRecord(item.roster_gate).reason || 'policy' }}
        </small>
        <small v-if="asArray(asRecord(item.active_gates).blocking_keys).length" class="selp-open-item-gate">
          active gates blocked · {{ asArray(asRecord(item.active_gates).blocking_keys).join(' / ') }}
        </small>
        <small v-if="asRecord(item.governance_gate).action || asRecord(item.governance_gate).reason" class="selp-open-item-gate">
          governance {{ asRecord(item.governance_gate).action || 'gate' }} · {{ asRecord(item.governance_gate).reason || 'policy' }}
        </small>
        <small v-if="asRecord(item.evolution_gate).pause === true || asRecord(item.evolution_gate).reason" class="selp-open-item-gate">
          evolution {{ asRecord(item.evolution_gate).pause === true ? 'pause' : 'allow' }} · {{ asRecord(item.evolution_gate).reason || 'metrics policy' }}
        </small>
        <small v-if="asArray(asRecord(item.roster_gate).out_of_roster_ids).length" class="selp-open-item-ids">
          {{ asArray(asRecord(item.roster_gate).out_of_roster_ids).slice(0, 4).join(' / ') }}
        </small>
        <small v-if="asArray(asRecord(item.roster_gate).not_deployed_ids).length" class="selp-open-item-ids">
          未登记上岗：{{ asArray(asRecord(item.roster_gate).not_deployed_ids).slice(0, 4).join(' / ') }}
        </small>
      </div>
    </div>

    <div class="selp-flow" role="list" aria-label="自进化 loop 阶段">
      <div
        v-for="stage in loopStages"
        :key="stage.key"
        class="selp-stage"
        :class="`selp-stage--${stage.tone}`"
        role="listitem"
      >
        <span class="selp-stage-dot" aria-hidden="true" />
        <span class="selp-stage-title">{{ stage.title }}</span>
        <strong class="selp-stage-value">{{ stage.value }}</strong>
        <span class="selp-stage-meta">{{ stage.meta }}</span>
      </div>
    </div>

    <div class="selp-decision" role="list" aria-label="auto merge 决策">
      <div v-for="card in decisionCards" :key="card.key" class="selp-decision-card" role="listitem">
        <span>{{ card.label }}</span>
        <strong>{{ card.value }}</strong>
        <small>{{ card.sub }}</small>
      </div>
    </div>

    <div class="selp-kb" aria-label="修复知识库与 RedisVL">
      <div class="selp-kb-cards" role="list">
        <div v-for="card in kbCards" :key="card.key" class="selp-kb-card" :class="`selp-kb-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="kbHitLines.length" class="selp-kb-hits">
        <li v-for="line in kbHitLines" :key="line">{{ line }}</li>
      </ul>
      <div v-if="kbFixHitDetails.length || kbPatternHitDetails.length" class="selp-kb-detail-list">
        <details v-for="hit in kbFixHitDetails" :key="`fix-${hit.path || hit.symptom}`" class="selp-kb-detail">
          <summary>{{ hit.symptom || hit.path || '修复知识命中' }}</summary>
          <dl>
            <dt>症状</dt>
            <dd>{{ hit.symptom || '—' }}</dd>
            <dt>根因</dt>
            <dd>{{ hit.root_cause || '—' }}</dd>
            <dt>修复 diff</dt>
            <dd><code>{{ hit.fix_diff || '—' }}</code></dd>
            <dt>required tests</dt>
            <dd>{{ Array.isArray(hit.required_tests) && hit.required_tests.length ? hit.required_tests.join(' / ') : '—' }}</dd>
            <dt>rollback plan</dt>
            <dd>{{ firstText(hit.rollback_plan, asRecord(hit.executable_template).rollback_plan, '—') }}</dd>
          </dl>
        </details>
        <details v-for="hit in kbPatternHitDetails" :key="`pattern-${hit.path || hit.pattern}`" class="selp-kb-detail">
          <summary>{{ hit.pattern || hit.summary || '代码模式命中' }}</summary>
          <dl>
            <dt>模式</dt>
            <dd>{{ hit.pattern || '—' }}</dd>
            <dt>摘要</dt>
            <dd>{{ hit.summary || '—' }}</dd>
            <dt>适用性</dt>
            <dd>{{ hit.applicability || '—' }}</dd>
            <dt>patch strategy</dt>
            <dd>{{ hit.patch_strategy || '—' }}</dd>
          </dl>
        </details>
      </div>
    </div>

    <div class="selp-proactive" aria-label="主动优化任务信号">
      <div class="selp-proactive-cards" role="list">
        <div v-for="card in proactiveCards" :key="card.key" class="selp-proactive-card" :class="`selp-proactive-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="proactiveCandidates.length" class="selp-proactive-list">
        <li v-for="item in proactiveCandidates" :key="`${proactiveCandidateTitle(item)}-${proactiveCandidateMeta(item)}`">
          <strong>{{ proactiveCandidateTitle(item) }}</strong>
          <span>{{ proactiveCandidateMeta(item) }}</span>
        </li>
      </ul>
    </div>

    <div class="selp-metrics" aria-label="进化指标与暂停门禁">
      <div class="selp-metrics-cards" role="list">
        <div v-for="card in evolutionMetricCards" :key="card.key" class="selp-metrics-card" :class="`selp-metrics-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <ul v-if="metricWindows.length" class="selp-metrics-windows">
        <li v-for="window in metricWindows" :key="`${window.from_week}-${window.to_week}`">
          <strong>{{ window.from_week || 'from' }} → {{ window.to_week || 'to' }}</strong>
          <span>
            coverage {{ window.coverage_delta ?? '—' }} · pytest {{ window.passed_delta ?? '—' }} · debt {{ window.debt_delta ?? '—' }}
          </span>
          <small v-if="Array.isArray(window.misses) && window.misses.length">{{ window.misses.join(' / ') }}</small>
        </li>
      </ul>
    </div>

    <div class="selp-roster" aria-label="编制对齐与员工隔离">
      <div class="selp-roster-cards" role="list">
        <div v-for="card in rosterAlignmentCards" :key="card.key" class="selp-roster-card" :class="`selp-roster-card--${card.tone}`" role="listitem">
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
          <small>{{ card.sub }}</small>
        </div>
      </div>
      <div v-if="rosterRemediation.action && rosterRemediation.action !== 'none'" class="selp-roster-remediation">
        <div>
          <span>修复指引</span>
          <strong>{{ rosterRemediation.title || rosterRemediation.action }}</strong>
          <small>{{ rosterRemediation.detail || rosterRemediation.action }}</small>
        </div>
        <small v-if="asArray(rosterRemediation.target_employee_ids).length" class="selp-roster-remediation-ids">
          {{ asArray(rosterRemediation.target_employee_ids).slice(0, 6).join(' / ') }}
        </small>
      </div>
      <ul v-if="rosterCoverage.length" class="selp-roster-coverage">
        <li v-for="dept in rosterCoverage" :key="String(dept.key || dept.label)">
          <strong>{{ dept.label || dept.key }}</strong>
          <span>{{ dept.count ?? 0 }}/{{ dept.total ?? 0 }}</span>
          <small>{{ asArray(dept.ids).join(' / ') }}</small>
        </li>
      </ul>
    </div>

    <div class="selp-team" role="list" aria-label="loop 参与员工">
      <div class="selp-team-head">
        <span>参与员工泳道</span>
        <strong>{{ teamLanes.length ? `${teamLanes.length} 名` : '等待 ledger 回写' }}</strong>
      </div>
      <div v-if="teamLanes.length" class="selp-team-list">
        <span v-for="lane in teamLanes" :key="`${lane.id}-${lane.stage}`" class="selp-team-chip" :class="{ 'selp-team-chip--outside': lane.rosterStatus === 'out_of_roster' || lane.dutyRegistered === false }" role="listitem">
          <strong>{{ lane.id }}</strong>
          <small>{{ lane.stage }} · {{ lane.source }}</small>
          <small v-if="lane.rosterLabel || lane.dutyRegisteredLabel || lane.department">{{ lane.rosterLabel || '编制未知' }}<template v-if="lane.dutyRegisteredLabel"> · {{ lane.dutyRegisteredLabel }}</template><template v-if="lane.department"> · {{ lane.department }}</template></small>
        </span>
      </div>
      <p v-else class="selp-team-empty">
        当前 status payload 尚未暴露员工 ID；后端 ledger 一旦写入 employee_id / actor / assignee 会自动显示。
      </p>
    </div>

    <div v-if="runTimeline" class="selp-timeline" aria-label="自进化 run 时间线">
      <div class="selp-timeline-head">
        <span>Run 时间线</span>
        <strong>#{{ runTimeline.runId || 'unknown' }}{{ runTimeline.open ? ' · 运行中' : '' }}</strong>
      </div>
      <ol class="selp-timeline-list">
        <li v-for="(item, idx) in runTimeline.items" :key="`${item.phase}-${item.step}-${idx}`" class="selp-timeline-item">
          <span class="selp-timeline-index">{{ idx + 1 }}</span>
          <div class="selp-timeline-main">
            <strong>{{ item.label || item.step || item.phase || '事件' }}</strong>
            <span>
              <template v-if="item.employee_id">{{ item.employee_id }}</template>
              <template v-if="item.role_label"> · {{ item.role_label }}</template>
              <template v-if="item.status"> · {{ item.status }}</template>
            </span>
            <small v-if="item.roster_label || item.department_label" class="selp-timeline-roster" :class="{ 'selp-timeline-roster--outside': item.roster_status === 'out_of_roster' }">
              {{ item.roster_label || item.roster_status || '编制未知' }}
              <template v-if="item.duty_registered_label"> · {{ item.duty_registered_label }}</template>
              <template v-if="item.department_label"> · {{ item.department_label }}</template>
            </small>
            <small>
              <template v-if="item.para_task_id">Para {{ item.para_task_id }}</template>
              <template v-if="item.branch"> · {{ item.branch }}</template>
              <template v-if="item.qa_verdict"> · QA {{ item.qa_verdict }}</template>
              <template v-if="item.review_max_severity"> · Review {{ item.review_max_severity }}</template>
              <template v-if="item.created_at"> · {{ item.created_at }}</template>
            </small>
            <div v-if="item.qa_verdict || item.review_max_severity" class="selp-report">
              <span v-if="item.qa_verdict" class="selp-report-pill" :class="item.qa_verdict === 'PASS' ? 'selp-report-pill--ok' : 'selp-report-pill--bad'">
                QA {{ item.qa_verdict }}
              </span>
              <span v-if="item.qa_target_branch_available !== null && item.qa_target_branch_available !== undefined" class="selp-report-pill">
                branch {{ item.qa_target_branch_available ? 'ok' : 'missing' }}
              </span>
              <span v-if="item.qa_risk_class" class="selp-report-pill">risk {{ item.qa_risk_class }}</span>
              <span v-if="item.review_max_severity" class="selp-report-pill">review {{ item.review_max_severity }}</span>
              <span v-if="Array.isArray(item.qa_tested_commands) && item.qa_tested_commands.length" class="selp-report-pill">
                tests {{ item.qa_tested_commands.length }}
              </span>
              <span v-if="Array.isArray(item.qa_blocking_findings) && item.qa_blocking_findings.length" class="selp-report-pill selp-report-pill--bad">
                blockers {{ item.qa_blocking_findings.length }}
              </span>
              <span v-if="Array.isArray(item.review_findings) && item.review_findings.length" class="selp-report-pill">
                findings {{ item.review_findings.length }}
              </span>
            </div>
          </div>
        </li>
      </ol>
    </div>

    <div v-if="!compact" class="selp-bottom">
      <div class="selp-policy">
        <span>Auto merge</span>
        <strong>{{ policy.auto_merge_low_risk === false ? '关闭' : '低风险开启' }}</strong>
        <small>max risk {{ policy.auto_merge_max_risk_score ?? '—' }} · min safety {{ policy.auto_merge_min_safety_score_v2 ?? '—' }}</small>
      </div>
      <div class="selp-policy">
        <span>最近分支</span>
        <strong>{{ branchName || '无' }}</strong>
        <small>{{ actionLabel }}</small>
      </div>
    </div>
  </section>
</template>

<style scoped>
.selp {
  --selp-accent: #2563eb;
  --selp-bg: #ffffff;
  --selp-border: #dbe3ef;
  --selp-text: #0f172a;
  --selp-muted: #64748b;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--selp-border);
  border-left: 4px solid var(--selp-accent);
  border-radius: 14px;
  background:
    radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.10), transparent 34%),
    linear-gradient(180deg, #fff 0%, #f8fafc 100%);
  color: var(--selp-text);
}

.selp--running { --selp-accent: #2563eb; }
.selp--ok { --selp-accent: #16a34a; }
.selp--warn { --selp-accent: #f59e0b; }
.selp--bad { --selp-accent: #ef4444; }
.selp--idle { --selp-accent: #64748b; }

.selp-head {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  align-items: flex-start;
}

.selp-kicker {
  margin: 0 0 4px;
  color: var(--selp-accent);
  font-size: 12px;
  font-weight: 900;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.selp-title {
  margin: 0 0 5px;
  color: var(--selp-text);
  font-size: 18px;
  font-weight: 900;
}

.selp-desc {
  margin: 0;
  color: var(--selp-muted);
  font-size: 13px;
  line-height: 1.5;
}

.selp-state {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
  color: var(--selp-accent);
  font-size: 13px;
}

.selp-state-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--selp-accent);
  box-shadow: 0 0 0 5px color-mix(in srgb, var(--selp-accent) 16%, transparent);
}

.selp-refresh {
  border: 1px solid color-mix(in srgb, var(--selp-accent) 25%, #dbe3ef);
  border-radius: 999px;
  background: #fff;
  color: var(--selp-accent);
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 800;
  cursor: pointer;
}

.selp-refresh:disabled {
  opacity: 0.6;
  cursor: default;
}

.selp-error {
  margin: 0;
  border-radius: 10px;
  background: #fef2f2;
  color: #b91c1c;
  padding: 9px 11px;
  font-size: 12px;
}

.selp-meta {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
}

.selp-meta-card,
.selp-stage,
.selp-policy {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.82);
}

.selp-meta-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 11px;
}

.selp-meta-card span,
.selp-stage-meta,
.selp-policy span,
.selp-policy small {
  color: var(--selp-muted);
  font-size: 12px;
  line-height: 1.35;
}

.selp-meta-card strong,
.selp-policy strong {
  overflow: hidden;
  color: var(--selp-text);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-copy {
  align-self: flex-start;
  border: 1px solid #99f6e4;
  border-radius: 999px;
  background: #ecfeff;
  color: #0f766e;
  padding: 3px 7px;
  font-size: 11px;
  font-weight: 900;
  cursor: pointer;
}

.selp-open-items {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: 10px 11px;
  border: 1px solid #fed7aa;
  border-radius: 12px;
  background: #fffbeb;
}

.selp-open-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  min-width: 0;
}

.selp-open-item div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.selp-open-item span,
.selp-open-item small {
  overflow: hidden;
  color: #92400e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-open-item strong {
  overflow: hidden;
  color: #78350f;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-open-item-gate {
  max-width: 260px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #fee2e2;
  color: #991b1b !important;
  font-weight: 900;
}

.selp-open-item-ids {
  grid-column: 1 / -1;
  padding: 5px 7px;
  border-radius: 8px;
  background: rgba(153, 27, 27, 0.08);
  color: #991b1b !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 800;
}

.selp-flow {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 9px;
}

.selp-decision {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-decision-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px 11px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-decision-card span,
.selp-decision-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-decision-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(59, 130, 246, 0.11), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-kb-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.selp-kb-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-kb-card--ok {
  background: #ecfdf5;
}

.selp-kb-card--warn {
  background: #fffbeb;
}

.selp-kb-card span,
.selp-kb-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-hits {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-kb-hits li {
  overflow: hidden;
  color: #475569;
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-kb-detail-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.selp-kb-detail {
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
  padding: 8px 9px;
}

.selp-kb-detail summary {
  cursor: pointer;
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.selp-kb-detail dl {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 5px 8px;
  margin: 8px 0 0;
}

.selp-kb-detail dt {
  color: #64748b;
  font-size: 11px;
  font-weight: 900;
}

.selp-kb-detail dd {
  min-width: 0;
  margin: 0;
  color: #334155;
  font-size: 11px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.selp-kb-detail code {
  white-space: pre-wrap;
}

.selp-proactive {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(99, 102, 241, 0.11), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-proactive-cards {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.selp-proactive-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-proactive-card--ok {
  background: #eef2ff;
}

.selp-proactive-card span,
.selp-proactive-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-proactive-list li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-proactive-list strong,
.selp-proactive-list span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-proactive-list strong {
  color: #312e81;
  font-size: 12px;
}

.selp-proactive-list span {
  color: #64748b;
  font-size: 11px;
}

.selp-metrics {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #dcfce7;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(34, 197, 94, 0.10), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-metrics-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-metrics-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-metrics-card--ok { background: #ecfdf5; }
.selp-metrics-card--warn { background: #fffbeb; }
.selp-metrics-card--bad { background: #fef2f2; }

.selp-metrics-card span,
.selp-metrics-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-windows {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-metrics-windows li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-metrics-windows strong,
.selp-metrics-windows span,
.selp-metrics-windows small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-metrics-windows strong {
  color: #14532d;
  font-size: 12px;
}

.selp-metrics-windows span,
.selp-metrics-windows small {
  color: #64748b;
  font-size: 11px;
}

.selp-stage {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 12px;
  overflow: hidden;
}

.selp-stage::after {
  content: "";
  position: absolute;
  inset: auto -18px -28px auto;
  width: 70px;
  height: 70px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--stage-color, #64748b) 14%, transparent);
}

.selp-stage--ok { --stage-color: #16a34a; }
.selp-stage--warn { --stage-color: #f59e0b; }
.selp-stage--bad { --stage-color: #ef4444; }
.selp-stage--running { --stage-color: #2563eb; }
.selp-stage--idle { --stage-color: #64748b; }

.selp-stage-dot {
  width: 9px;
  height: 9px;
  border-radius: 999px;
  background: var(--stage-color, #64748b);
  box-shadow: 0 0 10px color-mix(in srgb, var(--stage-color, #64748b) 50%, transparent);
}

.selp-stage-title {
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-stage-value {
  position: relative;
  z-index: 1;
  overflow: hidden;
  color: #0f172a;
  font-size: 15px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-bottom {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 9px;
}

.selp-team {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.78);
}

.selp-timeline-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-timeline-list {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-timeline-item {
  display: grid;
  grid-template-columns: 24px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
}

.selp-timeline-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--selp-accent) 13%, #fff);
  color: var(--selp-accent);
  font-size: 11px;
  font-weight: 900;
}

.selp-timeline-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.selp-timeline-main strong {
  color: #0f172a;
  font-size: 12px;
}

.selp-timeline-main span,
.selp-timeline-main small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-report {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 3px;
}

.selp-report-pill {
  border-radius: 999px;
  background: #f1f5f9;
  color: #475569;
  padding: 3px 6px;
  font-size: 10px;
  font-weight: 900;
  line-height: 1;
}

.selp-report-pill--ok {
  background: #dcfce7;
  color: #166534;
}

.selp-report-pill--bad {
  background: #fee2e2;
  color: #991b1b;
}

.selp-team-head,
.selp-team-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.selp-team-head {
  justify-content: space-between;
  color: #334155;
  font-size: 12px;
  font-weight: 900;
}

.selp-team-chip {
  display: inline-flex;
  flex-direction: column;
  gap: 2px;
  max-width: 220px;
  padding: 7px 9px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--selp-accent) 10%, #fff);
  color: #0f172a;
}

.selp-team-chip--outside {
  background: #fef2f2;
  color: #991b1b;
}

.selp-timeline-roster {
  align-self: flex-start;
  padding: 3px 7px;
  border-radius: 999px;
  background: #dcfce7;
  color: #166534;
  font-weight: 900;
}

.selp-timeline-roster--outside {
  background: #fef2f2;
  color: #991b1b;
}

.selp-team-chip strong {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-team-chip small,
.selp-team-empty {
  margin: 0;
  color: var(--selp-muted);
  font-size: 11px;
  line-height: 1.35;
}

.selp-policy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 11px 12px;
}

.selp--compact {
  padding: 14px;
}

.selp--compact .selp-title {
  font-size: 16px;
}

@media (max-width: 980px) {
  .selp-meta,
  .selp-flow,
  .selp-decision,
  .selp-kb-cards,
  .selp-proactive-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .selp-bottom {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .selp-head {
    flex-direction: column;
  }

  .selp-meta,
  .selp-flow,
  .selp-decision,
  .selp-kb-cards,
  .selp-proactive-cards {
    grid-template-columns: 1fr;
  }
}
.selp-roster {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 11px 12px;
  border: 1px solid #ccfbf1;
  border-radius: 12px;
  background:
    radial-gradient(circle at 12% 0%, rgba(20, 184, 166, 0.10), transparent 36%),
    rgba(255, 255, 255, 0.78);
}

.selp-governance-audit {
  display: grid;
  grid-template-columns: minmax(190px, 0.45fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #dbeafe;
  border-radius: 12px;
  background: rgba(239, 246, 255, 0.78);
}

.selp-contract {
  display: grid;
  grid-template-columns: minmax(190px, 0.45fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.82);
}

.selp-contract--ok {
  border-color: #bbf7d0;
  background: rgba(240, 253, 244, 0.82);
}

.selp-contract--bad {
  border-color: #fecaca;
  background: rgba(254, 242, 242, 0.9);
}

.selp-contract-head,
.selp-contract-grid > div {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.7);
}

.selp-contract-grid > .selp-contract-primary {
  grid-column: span 2;
  background:
    radial-gradient(circle at 0% 0%, rgba(20, 184, 166, 0.12), transparent 34%),
    rgba(255, 255, 255, 0.86);
}

.selp-contract-head span,
.selp-contract-head small,
.selp-contract-grid span,
.selp-contract-grid small {
  display: block;
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-grid a {
  display: inline-flex;
  width: fit-content;
  margin-top: 7px;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  font-size: 11px;
  font-weight: 950;
  text-decoration: none;
}

.selp-contract-head strong,
.selp-contract-grid strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 6px;
}

.selp-contract-incidents {
  display: grid;
  grid-template-columns: minmax(190px, 0.34fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 12px;
  background: rgba(254, 242, 242, 0.88);
}

.selp-contract-incidents-head,
.selp-contract-incident {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-contract-incidents-head span,
.selp-contract-incidents-head small,
.selp-contract-incident span,
.selp-contract-incident small,
.selp-contract-incident em {
  display: block;
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-incidents-head strong,
.selp-contract-incident strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-contract-incidents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 6px;
}

.selp-contract-incident--warn {
  background: rgba(255, 251, 235, 0.9);
}

.selp-active-gates {
  display: grid;
  grid-template-columns: minmax(160px, 0.36fr) minmax(0, 1fr);
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid #e0e7ff;
  border-radius: 12px;
  background: rgba(238, 242, 255, 0.78);
}

.selp-active-gates-head,
.selp-active-gate {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-active-gates-head span,
.selp-active-gates-head small,
.selp-active-gate span,
.selp-active-gate small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-active-gates-head strong,
.selp-active-gate strong {
  display: block;
  overflow: hidden;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-active-gates-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

.selp-active-gate--ok {
  background: rgba(240, 253, 244, 0.86);
}

.selp-active-gate--bad {
  background: rgba(254, 242, 242, 0.92);
}

.selp-governance-audit-head,
.selp-governance-audit li {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.68);
}

.selp-governance-audit-head span,
.selp-governance-audit-head small,
.selp-governance-audit li span,
.selp-governance-audit li small {
  color: var(--selp-muted);
  font-size: 11px;
}

.selp-governance-audit-head strong,
.selp-governance-audit li strong {
  display: block;
  margin: 2px 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 900;
}

.selp-governance-audit ul {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-ui-bridge {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1.35fr);
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid #bae6fd;
  border-radius: 12px;
  background:
    radial-gradient(circle at 0% 0%, rgba(14, 165, 233, 0.12), transparent 36%),
    linear-gradient(135deg, rgba(240, 249, 255, 0.96), rgba(248, 250, 252, 0.88));
}

.selp-ui-bridge--run {
  border-color: #99f6e4;
  background: linear-gradient(135deg, #ecfeff, #f8fafc);
}

.selp-ui-bridge--ok {
  border-color: #bbf7d0;
  background: linear-gradient(135deg, #f0fdf4, #f8fafc);
}

.selp-ui-bridge--warn {
  border-color: #fde68a;
  background: linear-gradient(135deg, #fffbeb, #f8fafc);
}

.selp-ui-bridge--bad {
  border-color: #fecaca;
  background: linear-gradient(135deg, #fef2f2, #f8fafc);
}

.selp-ui-bridge-main {
  min-width: 0;
}

.selp-ui-bridge-main span,
.selp-ui-bridge-main small,
.selp-ui-bridge-surfaces span,
.selp-ui-bridge-surfaces small,
.selp-ui-bridge-foot {
  color: var(--selp-muted);
  font-size: 11px;
}

.selp-ui-bridge-main span {
  display: block;
  font-weight: 900;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.selp-ui-bridge-main strong {
  display: block;
  margin: 3px 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 900;
}

.selp-ui-bridge-main small {
  display: block;
  line-height: 1.45;
}

.selp-ui-bridge-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.selp-ui-bridge-actions a,
.selp-ui-bridge-actions button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  padding: 5px 8px;
  border-radius: 999px;
  background: #0f172a;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 11px;
  font-weight: 900;
  text-decoration: none;
}

.selp-ui-bridge-actions button:disabled {
  cursor: not-allowed;
  opacity: 0.58;
}

.selp-ui-bridge-review {
  display: block;
  margin-top: 6px;
  font-weight: 900;
}

.selp-ui-bridge-review--ok {
  color: #047857 !important;
}

.selp-ui-bridge-review--bad {
  color: #b91c1c !important;
}

.selp-ui-bridge-surfaces {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.selp-ui-bridge-surfaces div {
  min-width: 0;
  padding: 8px 9px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.72);
}

.selp-ui-bridge-surfaces span,
.selp-ui-bridge-surfaces strong,
.selp-ui-bridge-surfaces small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-ui-bridge-surfaces strong {
  margin: 2px 0;
  color: #0f172a;
  font-size: 12px;
  font-weight: 900;
}

.selp-ui-bridge-foot {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 2px;
  font-weight: 800;
}

.selp-roster-cards {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 8px;
}

.selp-roster-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 10px;
  background: #f8fafc;
}

.selp-roster-card--run { background: #ecfeff; }
.selp-roster-card--ok { background: #f0fdf4; }
.selp-roster-card--warn { background: #fffbeb; }
.selp-roster-card--bad { background: #fef2f2; }

.selp-roster-card span,
.selp-roster-card small {
  overflow: hidden;
  color: var(--selp-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-card strong {
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 9px 10px;
  border: 1px solid #fed7aa;
  border-radius: 10px;
  background: #fffbeb;
}

.selp-roster-remediation div {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.selp-roster-remediation span,
.selp-roster-remediation small {
  overflow: hidden;
  color: #92400e;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation strong {
  overflow: hidden;
  color: #78350f;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-remediation-ids {
  max-width: 340px;
  padding: 5px 8px;
  border-radius: 8px;
  background: rgba(153, 27, 27, 0.08);
  color: #991b1b !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 900;
}

.selp-roster-coverage {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.selp-roster-coverage li {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 2px 8px;
  min-width: 0;
  padding: 7px 8px;
  border-radius: 9px;
  background: rgba(240, 253, 250, 0.72);
}

.selp-roster-coverage strong,
.selp-roster-coverage span,
.selp-roster-coverage small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.selp-roster-coverage strong {
  color: #0f766e;
  font-size: 12px;
}

.selp-roster-coverage span,
.selp-roster-coverage small {
  color: #64748b;
  font-size: 11px;
}

.selp-roster-coverage small {
  grid-column: 1 / -1;
}

@media (max-width: 760px) {
  .selp-ui-bridge,
  .selp-contract,
  .selp-contract-incidents,
  .selp-active-gates,
  .selp-governance-audit,
  .selp-roster-cards,
  .selp-roster-coverage {
    grid-template-columns: 1fr;
  }

  .selp-active-gates-grid,
  .selp-contract-grid,
  .selp-contract-incidents-grid,
  .selp-governance-audit ul,
  .selp-ui-bridge-surfaces {
    grid-template-columns: 1fr;
  }
}
</style>
