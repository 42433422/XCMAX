/**
 * 自进化 Loop 运行时：基础状态、派生只读视图与轮询定时器。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed, ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { Router } from 'vue-router'
import api from '@/api/xcmaxMarketProxy'
import { ALL_PLANNED_IDS, parseViewModeFromQuery, dgLoopRecord, dgLoopArray, dgLoopString, dgLoopFirstText, dgLoopNumber, collectDutyLoopEmployeeIds } from './dutyRosterConstants'
export function useDutyLoopCore(s: DutyRosterState, ctx: { focusEmployee: (id: string) => void; router: Router }) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { focusEmployee, router } = ctx

let loopRuntimeTimer: number | null = null

async function refreshLoopRuntimeStatus() {
  try {
    loopRuntimeStatus.value = await api.selfMaintenanceRuntimeStatus(80) as Record<string, unknown>
  } catch {
    loopRuntimeStatus.value = null
  }
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
  const out: Record<string, Record<string, unknown>> = {}
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
const loopRemediationResult = ref<Record<string, unknown> | null>(null)
const loopGovernanceReviewBusy = ref(false)
const loopGovernanceReviewError = ref('')
const loopGovernanceReviewResult = ref<Record<string, unknown> | null>(null)
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


  return {
    loopRuntimeStatus,
    loopRuntimeTimer,
    refreshLoopRuntimeStatus,
    loopParticipantIdSet,
    loopParticipantById,
    loopParticipantIds,
    loopUiBridgeRecord,
    loopGovernanceAuditRecord,
    loopCurrentGovernanceGateRecord,
    loopGovernanceAuditSummary,
    loopGovernanceAuditLast,
    loopGovernanceAuditLastTargets,
    loopGovernanceAuditLastSummary,
    loopRuntimeSchemaVersion,
    loopRuntimeContractRecord,
    loopRuntimeContractValidationRecord,
    loopRuntimeSurfaceReadinessCards,
    loopRuntimeContractRequiredFields,
    loopRuntimeContractMissingFields,
    loopRuntimeContractMissingNested,
    loopRuntimeSurfaceReadiness,
    loopRuntimeSurfaceReadinessOk,
    loopRuntimeSurfaceMissing,
    loopRuntimeSurfaceIncidents,
    loopRuntimeSurfaceIncident,
    loopRuntimeSurfaceIncidentSummary,
    loopRuntimeContractStatus,
    loopRuntimeContractPrimaryRoute,
    loopRuntimePrimaryRouteLocation,
    loopRuntimePrimaryRouteLabel,
    loopRuntimeContractOk,
    loopDutyRosterBridgeRecord,
    loopGovernanceActionRecord,
    loopGovernanceAllowedSurfaces,
    loopGovernanceActionAllowedInDutyGraph,
    loopBridgePrimaryEmployeeId,
    loopBridgeIsolationIds,
    loopRosterAlignment,
    loopRosterGateRecord,
    loopRosterRemediationRecord,
    loopRawParticipantIds,
    loopOutOfRosterParticipantIds,
    loopOutOfRosterCount,
    loopNotDeployedCount,
    loopGateRecord,
    loopEvidenceRecord,
    loopMergeDecisionRecord,
    loopMetricsRecord,
    loopOpenRunCount,
    loopRemediationBusy,
    loopRemediationError,
    loopRemediationResult,
    loopGovernanceReviewBusy,
    loopGovernanceReviewError,
    loopGovernanceReviewResult,
    loopCanReviewGovernanceAudit,
    loopRemediationResultSummary,
    loopRemediationTargetIds,
    loopCanRunDutyRegistration,
    nodeEmployeeId,
    nodeLoopActive,
    focusLoopParticipant,
    employeeSpaceLocation,
  }
}

export type DutyLoopCore = ReturnType<typeof useDutyLoopCore>
