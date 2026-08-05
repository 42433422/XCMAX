import { computed, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { AUTONOMY_L4_READINESS, overlayDeployGap } from '@/constants/autonomyL4Readiness'
import { useLoopRuntimePanel, type AnyRecord } from './useLoopRuntimePanel'
import { collectEmployeeMentions, normalizeDutyRosterView, type EmployeeMention } from './selfEvolutionRuntimeValues'

export type SelfEvolutionSurface = 'employee-space' | 'duty-roster'

/**
 * 自进化循环运行面板的业务状态逻辑。
 * 负责把 `useLoopRuntimePanel` 拉取的 raw runtime 快照解析为领域状态
 * （contract / ui_bridge / governance_audit / merge_decision / l4 readiness 等），
 * 以及本地交互状态（para 复制、治理审计复核）。
 * `surface` / `compact` 由外层组件传入，保持与 props 行为一致。
 */
export function useSelfEvolutionRuntimePanelState(surface: SelfEvolutionSurface, compact: boolean) {
  const router = useRouter()
  const {
    raw, loading, error, refresh,
    asRecord, asArray, asString, asNumber, firstText,
  } = useLoopRuntimePanel(() => compact ? 40 : 80)
  const paraCopied = ref(false)
  const governanceReviewBusy = ref(false)
  const governanceReviewError = ref('')
  const governanceReviewResult = ref<AnyRecord | null>(null)

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
        note: `self-evolution panel reviewed governance audit on ${surface}`,
      }) as AnyRecord
      await refresh()
    } catch (err: unknown) {
      const e = err as { message?: unknown; detail?: unknown }
      governanceReviewError.value = String(e?.message || e?.detail || err || '操作审计复核失败')
    } finally {
      governanceReviewBusy.value = false
    }
  }

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
  const runtimeSchemaVersion = computed(() => firstText(asRecord(raw.value).schema_version, '未知'))
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
    if (surface === 'duty-roster') return 'duty_roster_graph'
    if (surface === 'employee-space') return 'employee_space'
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
    surface === 'duty-roster' ? 'duty_roster_graph' : 'employee_space',
  )
  const canReviewGovernanceAudit = computed(() =>
    !governanceReviewBusy.value
    && uiBridgeGovernanceAction.value.requires_admin === true
    && surface === 'duty-roster'
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
      return `已上岗 ${onboarded} · 已跳过 ${skipped} · 失败 ${failed}`
    }
    return ''
  })
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

  const structuredParticipants = computed<EmployeeMention[]>(() =>
    asArray(raw.value?.participants)
      .map((item) => {
        const row = asRecord(item)
        const id = firstText(row.employee_id, row.id)
        if (!id) return null
        const role = firstText(row.role_label, row.role)
        const stage = asArray(row.stage_labels).map((x) => asString(x)).filter(Boolean).join(' / ')
          || asArray(row.stages).map((x) => asString(x)).filter(Boolean).join(' / ')
          || '循环'
        return {
          id,
          stage: role ? `${role} · ${stage}` : stage,
          source: asArray(row.sources).map((x) => asString(x)).filter(Boolean).join(' / ') || '参与员工',
          rosterLabel: firstText(row.roster_label, row.roster_status),
          rosterStatus: firstText(row.roster_status),
          dutyRegisteredLabel: firstText(row.duty_registered_label),
          dutyRegistered: row.duty_registered,
          department: firstText(row.department_label, row.department_key),
        }
      })
      .filter(Boolean) as EmployeeMention[],
  )

  const teamLanes = computed<EmployeeMention[]>(() => {
    if (structuredParticipants.value.length) return structuredParticipants.value.slice(0, 12)
    const found = new Map<string, EmployeeMention>()
    collectEmployeeMentions(evidence.value.steps_by_open_run, found, '运行中')
    collectEmployeeMentions(evidence.value.recent_rows, found, '记录')
    collectEmployeeMentions(memory.value.last_run, found, '最近运行')
    collectEmployeeMentions(memory.value.recent_runs, found, '历史')
    return Array.from(found.values()).slice(0, 12)
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

  const l4Closure = computed(() => asRecord(raw.value?.l4_closure))
  const autoDispatchDeploy = computed(() => {
    if (typeof l4Closure.value.auto_dispatch_deploy === 'boolean') {
      return l4Closure.value.auto_dispatch_deploy
    }
    if (typeof policy.value.auto_dispatch_deploy === 'boolean') {
      return policy.value.auto_dispatch_deploy
    }
    return null
  })
  const l4Gaps = computed(() =>
    overlayDeployGap(AUTONOMY_L4_READINESS.gaps, autoDispatchDeploy.value),
  )
  const l4P0Count = computed(() => l4Gaps.value.filter((g) => g.severity === 'P0' && g.status !== 'ok').length)
  const l4BlockedCount = computed(() => l4Gaps.value.filter((g) => g.status === 'blocked').length)

  return {
    raw, loading, error, refresh,
    asRecord, asArray, asString, asNumber, firstText,
    evidence, memory, policy, gate, cron,
    activeGates, activeGateItems,
    runtimeSchemaVersion, runtimeContract, runtimeContractValidation,
    runtimeContractRequiredFields, runtimeContractMissingFields, runtimeContractMissingNested,
    runtimeSurfaceKey, runtimeSurfaceReadiness, runtimeSurfaceReadinessOk, runtimeSurfaceMissing,
    runtimeAllSurfaceIncidents, runtimeSurfaceIncidentSummary, runtimeContractStatus,
    runtimeContractPrimaryRoute, runtimeContractRouteEmployeeId,
    runtimeContractDutyRosterLocation, runtimeContractEmployeeSpaceLocation,
    runtimeSurfaceIncidents, runtimeSurfaceIncident, runtimeContractSurfaces,
    runtimeContractGateDependencies, runtimeContractOk,
    kbSummary, evolutionMetrics, rosterAlignment, currentGovernanceGate,
    uiBridge, governanceAudit, governanceAuditSummary, governanceAuditLast, governanceAuditRecent,
    employeeSpaceBridge, dutyRosterBridge, uiBridgeGovernanceAction, uiBridgeAllowedSurfaces,
    currentGovernanceSurface, canReviewGovernanceAudit,
    uiBridgeTargets, uiBridgeBlockedIds, uiBridgePrimaryEmployeeId, uiBridgeActions, uiBridgePath,
    uiBridgeVisible, uiBridgeDutyRosterLocation, uiBridgeEmployeeSpaceLocation,
    governanceAuditLastTargets, governanceAuditLastSummary,
    latestComplete, latestSkip, lastRun, decision, mergeDecision,
    openRunIds, openItems, recentRuns, structuredParticipants, teamLanes,
    paraTaskId, branchName, actionLabel,
    l4Closure, autoDispatchDeploy, l4Gaps, l4P0Count, l4BlockedCount,
    paraCopied, governanceReviewBusy, governanceReviewError, governanceReviewResult,
    copyParaTaskId, reviewGovernanceAudit,
  }
}

export type SelfEvolutionRuntimePanelState = ReturnType<typeof useSelfEvolutionRuntimePanelState>