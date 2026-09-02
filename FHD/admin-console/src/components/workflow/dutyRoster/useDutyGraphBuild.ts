/**
 * 节点图构建（hub/部门/分区/客户端车间）、重建 watch 与统计条。
 *
 * 由 DutyRosterGraphPanel.vue 原文机械切分而来（行为保持不变）。
 */
import { computed, watch, nextTick } from 'vue'
import type { DutyRosterState } from './useDutyRosterState'
import type { EmpRow } from './dutyRosterTypes'
import type { DutyLoopCore } from './useDutyLoopCore'
import type { DutyData } from './useDutyRosterData'
type DutyFitView = (opts?: { padding?: number; maxZoom?: number; duration?: number; nodes?: string[] }) => void | Promise<boolean>
import { YUANGON_PKG_ROLE_LABELS, SIX_LINE_DEPARTMENTS, DEPARTMENT_ORDER, DEPARTMENT_COLORS } from '@host/domain/yuangonDutyRoster'
import { clientWorkshopNodeId, listClientWorkshops } from '@host/domain/clientWorkshops'
import { computeAutoLayout, computeGridLayout } from '@host/composables/useAutoLayout'
import type { Node, Edge } from '@vue-flow/core'
import { createDutyRosterLayout } from './dutyRosterLayout'
import { ALL_PLANNED_IDS, CRAFT_PIPELINE_ORDER, AREA_COLORS, ALL_AREAS, isVirtualEmployee, isDutyGraphMember, CENTER_ID, CLIENT_CENTER_ID, NODE_W, WORKSHOP_NODE_W, WORKSHOP_NODE_H, HEALTH_COLOR, RUN_STATUS_COLOR, LLM_ACT_COLOR } from './dutyRosterConstants'
export function useDutyGraphBuild(s: DutyRosterState, core: DutyLoopCore, data: DutyData, ctx: { fitView: DutyFitView; syncEmployeeRouteQuery: (employeeId?: string | null) => void }) {
  const { employees, missingLocalPackIds, healthMap, depsMap, loading, loadingP2, error, loadWarning, llmStatusMap, llmFernetConfigured, llmStatusFailed, empLlmMap, viewMode, showGapPanel, gapFocusHint, autoRefresh, countdown, capabilityMap, capLoading, runNodeStatusMap, loopRuntimeStatus, showStatsDetail, showMoreActions, detailCollapsed, empCapabilityViewMap, showNoKeyPanel, noKeyLoading, noKeyError, noKeyData, noKeyBusyRow, showAllHandsPanel, allHandsBusy, allHandsError, allHandsReport, allHandsWithResearch, allHandsExpanded, allHandsPlainOpen, allHandsPlainText, allHandsPlainLoading, allHandsPlainReqGen, allHandsMeetingMinutes, allHandsMeetingMinutesEmail, allHandsSessionId, allHandsQuestion, allHandsProgress, showRunPanel, runTargetId, runTaskBrief, runInputJson, runIncludeDependencies, runAllowHighRisk, runMaxConcurrency, runBusy, runError, latestRun, flowNodes, flowEdges, taskBrief, taskInputJson, dispatchConfirmHighRisk, taskRunning, taskResult, taskError, showDispatch, selectedEmp, selectedWorkshop, workshopRouteCopied, execItems, execTotal, execLoading, execLoadingMore, execError, onDutyEmployees, healthLevel, empAreaColor, llmActLevel, anyProviderHasUsableKey, runStatusLevel, capabilityLevel, capabilityColor, capabilityLabel, isDeployedDutyRosterRow } = s
  const { fitView, syncEmployeeRouteQuery } = ctx
  const { loopRuntimeTimer, refreshLoopRuntimeStatus, loopParticipantIdSet, loopParticipantById, loopParticipantIds, loopUiBridgeRecord, loopGovernanceAuditRecord, loopCurrentGovernanceGateRecord, loopGovernanceAuditSummary, loopGovernanceAuditLast, loopGovernanceAuditLastTargets, loopGovernanceAuditLastSummary, loopRuntimeSchemaVersion, loopRuntimeContractRecord, loopRuntimeContractValidationRecord, loopRuntimeSurfaceReadinessCards, loopRuntimeContractRequiredFields, loopRuntimeContractMissingFields, loopRuntimeContractMissingNested, loopRuntimeSurfaceReadiness, loopRuntimeSurfaceReadinessOk, loopRuntimeSurfaceMissing, loopRuntimeSurfaceIncidents, loopRuntimeSurfaceIncident, loopRuntimeSurfaceIncidentSummary, loopRuntimeContractStatus, loopRuntimeContractPrimaryRoute, loopRuntimePrimaryRouteLocation, loopRuntimePrimaryRouteLabel, loopRuntimeContractOk, loopDutyRosterBridgeRecord, loopGovernanceActionRecord, loopGovernanceAllowedSurfaces, loopGovernanceActionAllowedInDutyGraph, loopBridgePrimaryEmployeeId, loopBridgeIsolationIds, loopRosterAlignment, loopRosterGateRecord, loopRosterRemediationRecord, loopRawParticipantIds, loopOutOfRosterParticipantIds, loopOutOfRosterCount, loopNotDeployedCount, loopGateRecord, loopEvidenceRecord, loopMergeDecisionRecord, loopMetricsRecord, loopOpenRunCount, loopRemediationBusy, loopRemediationError, loopRemediationResult, loopGovernanceReviewBusy, loopGovernanceReviewError, loopGovernanceReviewResult, loopCanReviewGovernanceAudit, loopRemediationResultSummary, loopRemediationTargetIds, loopCanRunDutyRegistration, nodeEmployeeId, nodeLoopActive, focusLoopParticipant, employeeSpaceLocation } = core
  const { buildRosterEmployeeRows, load, butlerEmployeeRow, seedVirtualEmployees, loadPhase2, loadCapabilities, startAutoRefresh, stopAutoRefresh } = data
  const { applyDepartmentLayout, applyLayout, applyAreaLayout } = createDutyRosterLayout(flowNodes, flowEdges)

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
        markerEnd: { type: 'arrowclosed', color: '#4ade80' } as unknown as Edge['markerEnd'],
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
        markerEnd: { type: 'arrowclosed', color: '#818cf8' } as unknown as Edge['markerEnd'],
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
        markerEnd: { type: 'arrowclosed', color: '#4ade80' } as unknown as Edge['markerEnd'],
      })
    }
  }

  return edges
}


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
  nextTick(() => { fitView(fitOpts) })
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

  return {
    buildHubGraph,
    deptNodeId,
    flattenDeptMemberIds,
    buildDepartmentGraph,
    buildAreaGraph,
    buildCraftPipelineEdgesForDept,
    buildDepEdges,
    buildClientWorkshopGraph,
    stats,
  }
}

export type DutyGraphBuild = ReturnType<typeof useDutyGraphBuild>
