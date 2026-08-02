import { computed } from 'vue'
import { loopArray, loopFirstText, loopRecord, loopString, type LoopRuntimeConsoleDeps } from './loopRuntimeValues'
import type { LoopRuntimeCore } from './useLoopRuntimeCore'

export function useLoopRuntimeActivity(core: LoopRuntimeCore, deps: LoopRuntimeConsoleDeps) {
  const { visualizedEmployeeCount, routeFocusedEmployeeId } = deps
  const {
    loopMissingEvidenceCount, loopMergeDecision, loopStatusLabel, loopRuntime,
    loopRuntimeContractOk, loopRuntimeSchemaVersion, loopOpenRunCount, loopGateReasonText,
    loopParticipantIds, loopGate, loopMetrics, loopEvidence, loopActiveGates,
    loopActiveGateBlockingKeys, loopRosterAlignment, loopOutOfRosterParticipantIds,
    loopBridgePrimaryEmployeeId, dutyRosterEmployeeLocation, dutyRosterLoopLocation,
    loopAlignedPlannedCount, loopAlignedInRosterCount, loopAlignedInDeployedCount,
    loopOutOfRosterCount, loopNotDeployedCount, loopRuntimeSurfaceIncident,
    loopRuntimeSurfaceReadiness, loopRuntimeSurfaceIncidents, loopRuntimeSurfaceMissing,
    dutyRosterGovernanceLocation, loopBridgeBlockedEmployeeIds, loopParticipantRoleLabels,
  } = core
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

  return {
    loopRuntimeCards, loopTimelineItems, loopPipelineStages, loopActiveGateCards,
    loopWorkerTaskCards, loopWorkOrderCards, loopFocusedEmployeeId,
    loopFocusedWorkerTaskCard, loopEmployeeSeparationMatrix, loopWorkspaceActionCards,
  }
}

export type LoopRuntimeActivity = ReturnType<typeof useLoopRuntimeActivity>
