/**
 * 自进化 Loop 治理卡片区（只读 computed）。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { DutyLoopCore } from './useDutyLoopCore'
import { YUANGON_PKG_ROLE_LABELS, SIX_LINE_DEPARTMENTS, DEPARTMENT_ORDER } from '@host/domain/yuangonDutyRoster'
import { ALL_PLANNED_IDS, dgLoopRecord, dgLoopArray, dgLoopString, dgLoopFirstText, dgLoopNumber } from './dutyRosterConstants'
export function useDutyLoopGovernance(s: DutyRosterState, core: DutyLoopCore) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { loopRuntimeTimer, refreshLoopRuntimeStatus, loopParticipantIdSet, loopParticipantById, loopParticipantIds, loopUiBridgeRecord, loopGovernanceAuditRecord, loopCurrentGovernanceGateRecord, loopGovernanceAuditSummary, loopGovernanceAuditLast, loopGovernanceAuditLastTargets, loopGovernanceAuditLastSummary, loopRuntimeSchemaVersion, loopRuntimeContractRecord, loopRuntimeContractValidationRecord, loopRuntimeSurfaceReadinessCards, loopRuntimeContractRequiredFields, loopRuntimeContractMissingFields, loopRuntimeContractMissingNested, loopRuntimeSurfaceReadiness, loopRuntimeSurfaceReadinessOk, loopRuntimeSurfaceMissing, loopRuntimeSurfaceIncidents, loopRuntimeSurfaceIncident, loopRuntimeSurfaceIncidentSummary, loopRuntimeContractStatus, loopRuntimeContractPrimaryRoute, loopRuntimePrimaryRouteLocation, loopRuntimePrimaryRouteLabel, loopRuntimeContractOk, loopDutyRosterBridgeRecord, loopGovernanceActionRecord, loopGovernanceAllowedSurfaces, loopGovernanceActionAllowedInDutyGraph, loopBridgePrimaryEmployeeId, loopBridgeIsolationIds, loopRosterAlignment, loopRosterGateRecord, loopRosterRemediationRecord, loopRawParticipantIds, loopOutOfRosterParticipantIds, loopOutOfRosterCount, loopNotDeployedCount, loopGateRecord, loopEvidenceRecord, loopMergeDecisionRecord, loopMetricsRecord, loopOpenRunCount, loopRemediationBusy, loopRemediationError, loopRemediationResult, loopGovernanceReviewBusy, loopGovernanceReviewError, loopGovernanceReviewResult, loopCanReviewGovernanceAudit, loopRemediationResultSummary, loopRemediationTargetIds, loopCanRunDutyRegistration, nodeEmployeeId, nodeLoopActive, focusLoopParticipant, employeeSpaceLocation } = core

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
  const deptMap = SIX_LINE_DEPARTMENTS as Record<string, unknown>
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

  return {
    loopGovernanceControlCards,
    loopGovernanceActionPathCards,
    loopGovernanceIsolationMatrix,
    loopGovernanceChecklist,
    loopGovernanceTodoQueue,
    loopGovernanceFreshnessCards,
    loopMissingEvidenceCount,
    loopStatusLabel,
    loopParticipantPreview,
    loopDepartmentCoverage,
  }
}

export type DutyLoopGovernance = ReturnType<typeof useDutyLoopGovernance>
