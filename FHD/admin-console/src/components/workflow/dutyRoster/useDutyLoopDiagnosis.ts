/**
 * 自进化 Loop 诊断视图与治理动作。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { DutyLoopCore } from './useDutyLoopCore'
import type { DutyLoopGovernance } from './useDutyLoopGovernance'
import { SIX_LINE_DEPARTMENTS } from '@host/domain/yuangonDutyRoster'
import api from '@/api/xcmaxMarketProxy'
import { ALL_PLANNED_IDS, dgLoopRecord, dgLoopArray, dgLoopString, dgLoopFirstText, dgLoopNumber } from './dutyRosterConstants'
export function useDutyLoopDiagnosis(s: DutyRosterState, core: DutyLoopCore, gov: DutyLoopGovernance, ctx: { load: () => Promise<void> }) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { load } = ctx
  const { loopRuntimeTimer, refreshLoopRuntimeStatus, loopParticipantIdSet, loopParticipantById, loopParticipantIds, loopUiBridgeRecord, loopGovernanceAuditRecord, loopCurrentGovernanceGateRecord, loopGovernanceAuditSummary, loopGovernanceAuditLast, loopGovernanceAuditLastTargets, loopGovernanceAuditLastSummary, loopRuntimeSchemaVersion, loopRuntimeContractRecord, loopRuntimeContractValidationRecord, loopRuntimeSurfaceReadinessCards, loopRuntimeContractRequiredFields, loopRuntimeContractMissingFields, loopRuntimeContractMissingNested, loopRuntimeSurfaceReadiness, loopRuntimeSurfaceReadinessOk, loopRuntimeSurfaceMissing, loopRuntimeSurfaceIncidents, loopRuntimeSurfaceIncident, loopRuntimeSurfaceIncidentSummary, loopRuntimeContractStatus, loopRuntimeContractPrimaryRoute, loopRuntimePrimaryRouteLocation, loopRuntimePrimaryRouteLabel, loopRuntimeContractOk, loopDutyRosterBridgeRecord, loopGovernanceActionRecord, loopGovernanceAllowedSurfaces, loopGovernanceActionAllowedInDutyGraph, loopBridgePrimaryEmployeeId, loopBridgeIsolationIds, loopRosterAlignment, loopRosterGateRecord, loopRosterRemediationRecord, loopRawParticipantIds, loopOutOfRosterParticipantIds, loopOutOfRosterCount, loopNotDeployedCount, loopGateRecord, loopEvidenceRecord, loopMergeDecisionRecord, loopMetricsRecord, loopOpenRunCount, loopRemediationBusy, loopRemediationError, loopRemediationResult, loopGovernanceReviewBusy, loopGovernanceReviewError, loopGovernanceReviewResult, loopCanReviewGovernanceAudit, loopRemediationResultSummary, loopRemediationTargetIds, loopCanRunDutyRegistration, nodeEmployeeId, nodeLoopActive, focusLoopParticipant, employeeSpaceLocation } = core
  const { loopGovernanceControlCards, loopGovernanceActionPathCards, loopGovernanceIsolationMatrix, loopGovernanceChecklist, loopGovernanceTodoQueue, loopGovernanceFreshnessCards, loopMissingEvidenceCount, loopStatusLabel, loopParticipantPreview, loopDepartmentCoverage } = gov

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

function loopParticipantList(row: Record<string, unknown> | null, key: string): string {
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

async function runLoopDutyRegistration() {
  if (!loopCanRunDutyRegistration.value) return
  loopRemediationBusy.value = true
  loopRemediationError.value = ''
  loopRemediationResult.value = null
  try {
    const result = await api.adminYuangonOnboardRun({
      pkg_ids: loopRemediationTargetIds.value,
      force: true,
    }) as Record<string, unknown>
    loopRemediationResult.value = result
    if (result.ok !== false) {
      await load()
    }
    await refreshLoopRuntimeStatus()
  } catch (err: unknown) {
    loopRemediationError.value = String((err as { message?: unknown; detail?: unknown })?.message || (err as { message?: unknown; detail?: unknown })?.detail || err || '补登记失败')
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
    }) as Record<string, unknown>
    loopGovernanceReviewResult.value = result
    await refreshLoopRuntimeStatus()
  } catch (err: unknown) {
    loopGovernanceReviewError.value = String((err as { message?: unknown; detail?: unknown })?.message || (err as { message?: unknown; detail?: unknown })?.detail || err || '治理审计复核失败')
  } finally {
    loopGovernanceReviewBusy.value = false
  }
}

  return {
    loopCommandCards,
    loopRosterSeparationCards,
    loopAdminDiagnosis,
    selectedLoopParticipant,
    loopParticipantList,
    selectedLoopTimelineSummary,
    selectedLoopContext,
    runLoopDutyRegistration,
    reviewLoopGovernanceAudit,
  }
}

export type DutyLoopDiagnosis = ReturnType<typeof useDutyLoopDiagnosis>
