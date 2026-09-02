/**
 * 运行时契约 / UI Bridge / 治理复核（由 SelfEvolutionLoopRuntimePanel.vue 原文机械切分而来，行为保持不变）。
 */
import { computed, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { asArray, asRecord, asString, firstText, normalizeDutyRosterView, type AnyRecord } from './runtimeHelpers'
import type { SelfEvolutionRuntimeProps, useSelfEvolutionRuntime } from './useSelfEvolutionRuntime'

type Runtime = ReturnType<typeof useSelfEvolutionRuntime>

/** active gates 列表项：模板把 ``key`` / ``label`` 当字符串键使用，其余字段保持开放。 */
export interface ActiveGateItem {
  [key: string]: unknown
  key?: string
  label?: string
}

export function useRuntimeContract(props: SelfEvolutionRuntimeProps, runtime: Runtime) {
  const router = useRouter()
  const {
    raw, gate, mergeDecision, refresh,
    uiBridge, governanceAuditSummary, governanceAuditLast,
  } = runtime

  const governanceReviewBusy = ref(false)
  const governanceReviewError = ref('')
  const governanceReviewResult = ref<AnyRecord | null>(null)

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
      const row = asRecord(err)
      governanceReviewError.value = String(row.message || row.detail || err || '治理审计复核失败')
    } finally {
      governanceReviewBusy.value = false
    }
  }

  const activeGates = computed<AnyRecord>(() => {
    const fromDecision = asRecord(mergeDecision.value.active_gates)
    return Object.keys(fromDecision).length ? fromDecision : asRecord(raw.value?.active_gates)
  })
  const activeGateItems = computed(() =>
    asArray(activeGates.value.items)
      .map((item) => asRecord(item) as ActiveGateItem)
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

  return {
    governanceReviewBusy,
    governanceReviewError,
    governanceReviewResult,
    reviewGovernanceAudit,
    canReviewGovernanceAudit,
    activeGates,
    activeGateItems,
    runtimeSchemaVersion,
    runtimeContract,
    runtimeContractValidation,
    runtimeContractRequiredFields,
    runtimeContractMissingFields,
    runtimeContractMissingNested,
    runtimeSurfaceKey,
    runtimeSurfaceReadiness,
    runtimeSurfaceReadinessOk,
    runtimeSurfaceMissing,
    runtimeAllSurfaceIncidents,
    runtimeSurfaceIncidentSummary,
    runtimeSurfaceIncidents,
    runtimeSurfaceIncident,
    runtimeContractStatus,
    runtimeContractPrimaryRoute,
    runtimeContractRouteEmployeeId,
    runtimeContractDutyRosterLocation,
    runtimeContractEmployeeSpaceLocation,
    runtimeContractSurfaces,
    runtimeContractGateDependencies,
    runtimeContractOk,
    employeeSpaceBridge,
    dutyRosterBridge,
    uiBridgeGovernanceAction,
    uiBridgeTargets,
    uiBridgeBlockedIds,
    uiBridgeActions,
    uiBridgePath,
    uiBridgeVisible,
    governanceAuditLastTargets,
    governanceAuditLastSummary,
    uiBridgeDutyRosterLocation,
    uiBridgeEmployeeSpaceLocation,
  }
}
