import { computed, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { useRouter, type RouteLocationRaw } from 'vue-router'
import xcmaxMarketProxy from '@/api/xcmaxMarketProxy'

export type LoopRuntimeConsoleDeps = {
  plannedIds: Ref<ReadonlySet<string>>
  visualizedEmployeeCount: Ref<number>
  totalCount: Ref<number>
  routeFocusedEmployeeId: Ref<string>
  showManagementLoopPanels: Ref<boolean>
}

export function loopRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {}
}

export function loopArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

export function loopString(v: unknown): string {
  return String(v ?? '').trim()
}

export function loopFirstText(...values: unknown[]): string {
  for (const value of values) {
    const text = loopString(value)
    if (text) return text
  }
  return ''
}

export function loopNumber(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

const DUTY_ROSTER_VIEW_TOKENS = new Set(['department', 'dept', '六部门', 'hub', 'center', '中心', '中心图', 'legacy-area', 'area', '物理', '物理分区', 'client', 'workshop', '车间', '客户端车间'])

function normalizeDutyRosterView(raw: unknown): string {
  const token = String(Array.isArray(raw) ? raw[0] : raw || '').trim().toLowerCase()
  return DUTY_ROSTER_VIEW_TOKENS.has(token) ? token : 'department'
}

export function useLoopRuntimeConsole(deps: LoopRuntimeConsoleDeps) {
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

  return {
    loopRuntime,
    refreshLoopRuntime,
    loopRecord,
    loopArray,
    loopString,
    loopFirstText,
    loopNumber,
    panoramaLocation,
    dutyRosterLoopLocation,
    dutyRosterDepartmentLocation,
    dutyRosterGovernanceLocation,
    dutyRosterEmployeeLocation,
    loopParticipantIds,
    loopRawParticipantIds,
    loopRosterAlignment,
    loopRosterGate,
    loopRosterRemediation,
    loopUiBridge,
    loopActiveGates,
    loopActiveGateBlockingKeys,
    loopGovernanceAudit,
    loopGovernanceAuditSummary,
    loopGovernanceAuditLast,
    loopEmployeeSpaceBridge,
    loopGovernanceAction,
    loopGovernanceAuditLastTargets,
    loopGovernanceAuditLastSummary,
    loopBridgePrimaryEmployeeId,
    loopBridgeBlockedEmployeeIds,
    loopOutOfRosterParticipantIds,
    loopOutOfRosterCount,
    loopNotDeployedCount,
    loopAlignedPlannedCount,
    loopAlignedInRosterCount,
    loopAlignedInDeployedCount,
    loopParticipantRoleLabels,
    loopParticipantDisplay,
    loopGate,
    loopEvidence,
    loopMergeDecision,
    loopMetrics,
    loopOpenRunCount,
    loopRuntimeSchemaVersion,
    loopRuntimeContract,
    loopRuntimeContractValidation,
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
    loopStatusLabel,
    loopMissingEvidenceCount,
    loopGateReasonText,
    loopRuntimeCards,
    loopTimelineItems,
    loopPipelineStages,
    loopActiveGateCards,
    loopWorkerTaskCards,
    loopWorkOrderCards,
    loopFocusedEmployeeId,
    loopFocusedWorkerTaskCard,
    loopEmployeeSeparationMatrix,
    loopWorkspaceActionCards,
    loopRuntimeTruthCards,
    loopRuntimeFreshnessCards,
    loopIsolationCards,
    loopDiagnosis,
    loopGovernanceBridge,
    loopRoleGroups,
  }
}

export type LoopRuntimeConsole = ReturnType<typeof useLoopRuntimeConsole>
