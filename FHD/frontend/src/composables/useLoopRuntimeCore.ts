import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'
import { loopArray, loopFirstText, loopNumber, loopRecord, loopString, normalizeDutyRosterView, type LoopRuntimeConsoleDeps } from './loopRuntimeValues'

export function useLoopRuntimeCore(deps: LoopRuntimeConsoleDeps) {
  const { plannedIds: ALL_PLANNED_YUANGON_PKG_IDS, visualizedEmployeeCount, totalCount, routeFocusedEmployeeId, showManagementLoopPanels } = deps
  const router = useRouter()
  const loopRuntime = ref<Record<string, unknown> | null>(null)
  let loopRuntimeTimer: number | null = null

  onMounted(() => {
    if (showManagementLoopPanels.value) {
      void refreshLoopRuntime()
      loopRuntimeTimer = window.setInterval(() => {
        void refreshLoopRuntime()
      }, 30000)
    }
  })

  onBeforeUnmount(() => {
    if (loopRuntimeTimer != null) window.clearInterval(loopRuntimeTimer)
    loopRuntimeTimer = null
  })

  async function refreshLoopRuntime() {
    try {
      loopRuntime.value = await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(40) as Record<string, unknown>
    } catch {
      loopRuntime.value = null
    }
  }

  const panoramaLocation = computed<RouteLocationRaw>(() => {
    if (showManagementLoopPanels.value && router.hasRoute('duty-roster-graph')) {
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

  return {
    loopRuntime, refreshLoopRuntime, loopRecord, loopArray, loopString, loopFirstText, loopNumber,
    panoramaLocation, dutyRosterLoopLocation, dutyRosterDepartmentLocation,
    dutyRosterGovernanceLocation, dutyRosterEmployeeLocation, loopParticipantIds,
    loopRawParticipantIds, loopRosterAlignment, loopRosterGate, loopRosterRemediation,
    loopUiBridge, loopActiveGates, loopActiveGateBlockingKeys, loopGovernanceAudit,
    loopGovernanceAuditSummary, loopGovernanceAuditLast, loopEmployeeSpaceBridge,
    loopGovernanceAction, loopGovernanceAuditLastTargets, loopGovernanceAuditLastSummary,
    loopBridgePrimaryEmployeeId, loopBridgeBlockedEmployeeIds, loopOutOfRosterParticipantIds,
    loopOutOfRosterCount, loopNotDeployedCount, loopAlignedPlannedCount,
    loopAlignedInRosterCount, loopAlignedInDeployedCount, loopParticipantRoleLabels,
    loopParticipantDisplay, loopGate, loopEvidence, loopMergeDecision, loopMetrics,
    loopOpenRunCount, loopRuntimeSchemaVersion, loopRuntimeContract,
    loopRuntimeContractValidation, loopRuntimeSurfaceReadinessCards,
    loopRuntimeContractRequiredFields, loopRuntimeContractMissingFields,
    loopRuntimeContractMissingNested, loopRuntimeSurfaceReadiness,
    loopRuntimeSurfaceReadinessOk, loopRuntimeSurfaceMissing, loopRuntimeSurfaceIncidents,
    loopRuntimeSurfaceIncident, loopRuntimeSurfaceIncidentSummary, loopRuntimeContractStatus,
    loopRuntimeContractPrimaryRoute, loopRuntimePrimaryRouteLocation,
    loopRuntimePrimaryRouteLabel, loopRuntimeContractOk, loopStatusLabel,
    loopMissingEvidenceCount, loopGateReasonText,
  }
}

export type LoopRuntimeCore = ReturnType<typeof useLoopRuntimeCore>
