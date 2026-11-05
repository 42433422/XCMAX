import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { useLoopRuntimeConsole } from './useLoopRuntimeConsole'

const mocks = vi.hoisted(() => ({ status: vi.fn(), hasRoute: vi.fn() }))
vi.mock('@/api/xcmaxMarketProxy', () => ({ default: { selfMaintenanceRuntimeStatus: mocks.status } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ hasRoute: mocks.hasRoute }) }))
const employeeIds = ['worker-scout', 'worker-fix', 'worker-review', 'worker-qa', 'worker-verify', 'worker-ops', 'worker-other']
const wrappers: VueWrapper[] = []
function setup(management = false, focused = '') {
  let api!: ReturnType<typeof useLoopRuntimeConsole>
  const wrapper = mount(defineComponent({ setup() {
    api = useLoopRuntimeConsole({ plannedIds: ref(new Set(employeeIds)), visualizedEmployeeCount: ref(7), totalCount: ref(5),
      routeFocusedEmployeeId: ref(focused), showManagementLoopPanels: ref(management) })
    return () => null
  } }))
  wrappers.push(wrapper)
  return { api, wrapper }
}
function valid(extra: Record<string, unknown> = {}) {
  return { schema_version: 'self_maintenance_runtime.v1', contract: { required_top_level: ['evidence'] }, evidence: {},
    contract_validation: { surface_readiness: { employee_space: { ok: true } } }, ...extra }
}
beforeEach(() => { vi.useFakeTimers(); mocks.status.mockReset().mockResolvedValue(valid()); mocks.hasRoute.mockReset().mockReturnValue(true) })
afterEach(() => { wrappers.splice(0).forEach((w) => w.unmount()); vi.useRealTimers() })

describe('runtime console lifecycle and routing', () => {
  it('refreshes only a management console, clears failed snapshots, and cancels polling on unmount', async () => {
    const passive = setup()
    expect(mocks.status).not.toHaveBeenCalled()
    expect(passive.api.loopStatusLabel.value).toBe('待连接')
    const { api, wrapper } = setup(true)
    await flushPromises()
    expect(mocks.status).toHaveBeenCalledWith(40)
    expect(api.loopStatusLabel.value).toBe('待命')
    mocks.status.mockRejectedValueOnce(new Error('offline'))
    await vi.advanceTimersByTimeAsync(30000)
    expect(api.loopRuntime.value).toBeNull()
    expect(api.loopGovernanceBridge.value).toMatchObject({ actionExecutable: false, actionStatus: 'requires_check' })
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(60000)
    expect(mocks.status).toHaveBeenCalledTimes(2)
  })
  it('uses graph governance and employee routes, with safe fallback when the route is unavailable', () => {
    const { api } = setup(true, 'worker-qa')
    expect(api.panoramaLocation.value).toEqual({ name: 'duty-roster-graph', query: { view: 'department' } })
    api.loopRuntime.value = valid({ ui_bridge: { target_employee_ids: ['worker-fix'], primary_view: 'hub' },
      contract_status: { primary_route: { surface: 'duty_roster_graph', view: 'client' } } })
    expect(api.dutyRosterGovernanceLocation.value).toEqual({ name: 'duty-roster-graph', query: { view: 'hub', employee: 'worker-fix' } })
    expect(api.loopRuntimePrimaryRouteLocation.value).toEqual({ name: 'duty-roster-graph', query: { view: 'client', employee: 'worker-fix' } })
    expect(api.loopRuntimePrimaryRouteLabel.value).toBe('打开编制图谱')
    expect(api.dutyRosterEmployeeLocation(' worker-qa ')).toEqual({ name: 'duty-roster-graph', query: { view: 'hub', employee: 'worker-qa' } })
    mocks.hasRoute.mockReturnValue(false)
    const fallback = setup().api
    fallback.loopRuntime.value = valid({ contract_status: { primary_route: { surface: 'duty_roster_graph' } } })
    for (const target of [fallback.panoramaLocation, fallback.dutyRosterLoopLocation, fallback.dutyRosterDepartmentLocation,
      fallback.dutyRosterGovernanceLocation, fallback.loopRuntimePrimaryRouteLocation]) expect(target.value).toEqual({ name: 'workflow-employee-stitch-full' })
    expect(fallback.dutyRosterEmployeeLocation('')).toEqual({ name: 'workflow-employee-stitch-full' })
  })
  it.each([
    [{ surface: 'employee_space', employee_id: 'worker-fix' }, { query: { employee: 'worker-fix' } }, '定位员工空间'],
    [{ surface: 'employee_space', label: 'Investigate' }, { query: { employee: 'worker-qa' } }, 'Investigate'],
    [{ surface: 'unknown' }, { name: 'duty-roster-graph', query: { view: 'department' } }, '打开完整 Loop'],
  ])('resolves contract primary action %j', (primary_route, target, label) => {
    const { api } = setup(false, 'worker-qa')
    api.loopRuntime.value = valid({ contract_validation: { contract_status: { primary_route } } })
    expect(api.loopRuntimePrimaryRouteLocation.value).toEqual(target)
    expect(api.loopRuntimePrimaryRouteLabel.value).toBe(label)
  })
})

describe('runtime evidence and governance', () => {
  it('separates known employees from external participants and preserves role and audit evidence', () => {
    const { api } = setup()
    api.loopRuntime.value = valid({ participants: [{ employee_id: 'worker-scout', role: 'scout' }, { id: 'worker-fix', stage_labels: ['修复'] },
      { id: 'worker-review', stages: ['review'] }, { id: 'outside-vendor' }, {}],
      evidence: { nested: [null, 42, { actor: 'worker-qa' }, 'worker-verify and ignored-id'] }, memory: { assignee: 'worker-ops' },
      run_timelines: [{ items: [{ actor: 'outside-tool' }, { assignee: 'worker-fix' }] }],
      governance_audit: { last: { target_employee_ids: ['worker-qa', ''], onboard_summary: { onboarded: '2', skipped: 1, failed: 0 } } },
      ui_bridge: { blocked_employee_ids: ['worker-qa', ''] }, active_gates: { blocking_keys: ['review', ''] } })
    expect(api.loopParticipantIds.value).toEqual(employeeIds.slice(0, 6))
    expect(api.loopOutOfRosterParticipantIds.value).toEqual(['outside-vendor', 'outside-tool'])
    expect(api.loopOutOfRosterCount.value).toBe(2)
    expect(api.loopParticipantDisplay('worker-fix')).toBe('worker-fix · 修复')
    expect(api.loopParticipantDisplay('worker-ops')).toBe('worker-ops')
    expect(api.loopGovernanceAuditLastTargets.value).toEqual(['worker-qa'])
    expect(api.loopGovernanceAuditLastSummary.value).toBe('onboarded 2 · skipped 1 · failed 0')
    expect(api.loopBridgeBlockedEmployeeIds.value).toEqual(['worker-qa'])
    expect(api.loopActiveGateBlockingKeys.value).toEqual(['review'])
    expect(api.loopRoleGroups.value.map((g) => [g.key, g.workers.length])).toEqual([['scout', 1], ['fix', 1], ['review', 1], ['other', 3]])
    expect(api.loopGovernanceBridge.value).toMatchObject({ actionStatus: 'enforced', actionRequiresAdmin: true })
    expect(api.loopDiagnosis.value.title).toBe('发现非编制参与者')
  })
  it('honors explicit backend alignment, blocked gates, registration remediation, and incomplete audit summaries', () => {
    const { api } = setup()
    api.loopRuntime.value = valid({ roster_alignment: { planned_count: 10, in_roster_count: 3, in_deployed_count: 2,
      not_deployed_count: 1, not_deployed_ids: ['worker-fix', ''], out_of_roster_ids: [], out_of_roster_count: 0,
      gate: { action: 'hold' }, remediation: { target_employee_ids: ['worker-fix', ''], title: '登记缺失', detail: '需管理员登记。', action: 'register' } },
      governance_audit: { last: { onboard_summary: { onboarded: 'invalid' } } },
      active_gates: { items: [{ key: 'roster', blocking: true, reason: 'not registered' }, { name: 'review', ok: true }] } })
    expect(api.loopGovernanceAuditLastSummary.value).toBe('')
    expect(api.loopOutOfRosterParticipantIds.value).toEqual([])
    expect(api.loopDiagnosis.value).toMatchObject({ tone: 'bad', title: '登记缺失', detail: '需管理员登记。 目标：worker-fix', actions: ['register', '确认上岗员工和商店员工隔离'] })
    expect(api.loopGovernanceBridge.value).toMatchObject({ actionStatus: 'requires_action', actionExecutable: true, actionRequiresAdmin: true })
    expect(api.loopIsolationCards.value.find((c) => c.key === 'not-deployed')).toMatchObject({ value: '1', sub: 'worker-fix', tone: 'bad' })
    expect(api.loopEmployeeSeparationMatrix.value.find((c) => c.key === 'not-deployed')).toMatchObject({ sub: 'worker-fix', tone: 'bad' })
    expect(api.loopActiveGateCards.value).toEqual([
      { key: 'roster', label: 'roster', value: '阻断', sub: 'not registered', tone: 'bad' },
      { key: 'review', label: 'review', value: '放行', sub: 'policy clear', tone: 'ok' }])
  })
  it.each(['scout', 'fix', 'review', 'qa', 'verify', 'ops', 'other'])('groups %s employee work by semantic role', (role) => {
    const { api } = setup()
    api.loopRuntime.value = valid({ participants: [{ id: `worker-${role}`, role }] })
    expect(api.loopRoleGroups.value).toEqual([{ key: role, label: expect.any(String), workers: [`worker-${role} · ${role}`] }])
    expect(api.loopDiagnosis.value).toMatchObject({ tone: 'ok', title: 'Loop 边界正常' })
    expect(api.loopGovernanceBridge.value).toMatchObject({ actionStatus: '就绪', actionExecutable: false })
  })
  it('renders live run progress without inventing events and uses error status to block worker cards', () => {
    const { api } = setup(false, 'worker-fix')
    api.loopRuntime.value = valid({ participants: [{ id: 'worker-fix', role: 'fix' }], evidence: { open_run_ids: ['run-1'] },
      run_timelines: [{ run_id: 'run-1', items: [{ label: 'repair', actor: 'worker-fix', status: 'failed', at: '2026-10-15' }, {}] }] })
    expect(api.loopStatusLabel.value).toBe('运行中')
    expect(api.loopDiagnosis.value).toMatchObject({ tone: 'run', title: '上岗员工正在参与自维护' })
    expect(api.loopGovernanceBridge.value).toMatchObject({ actionStatus: '运行中', actionExecutable: false })
    expect(api.loopFocusedWorkerTaskCard.value).toMatchObject({ id: 'worker-fix', tone: 'bad', latestStatus: 'failed' })
    expect(api.loopPipelineStages.value.find((s) => s.key === 'repair')).toMatchObject({ tone: 'bad', count: 1, workers: ['worker-fix'] })
    expect(api.loopWorkOrderCards.value[0]).toMatchObject({ tone: 'bad', workers: ['worker-fix'], stepCount: 2 })
  })
})

describe('runtime contract diagnostics', () => {
  it('explains missing contracts and routes surface incidents to the governance surface', () => {
    const { api } = setup()
    api.loopRuntime.value = valid({ contract: { required_top_level: ['missing', ''], surfaces: ['employee_space', ''] },
      contract_validation: { surface_readiness: { employee_space: { ok: false, missing: ['participants', ''], action: 'repair' },
        duty_roster_graph: { ok: true } }, missing_nested: ['participants.id', ''],
      surface_incidents: [{ surface: 'employee_space', title: 'Repair binding', target_surface: 'duty_roster_graph' }, { surface: 'other' }],
      surface_incident_summary: { total: 1, surfaces: ['employee_space', ''] } } })
    expect(api.loopStatusLabel.value).toBe('Contract 异常')
    expect(api.loopRuntimeContractMissingFields.value).toEqual(['missing'])
    expect(api.loopRuntimeContractMissingNested.value).toEqual(['participants.id'])
    expect(api.loopDiagnosis.value.detail).toContain('缺字段：missing')
    expect(api.loopRuntimeTruthCards.value.find((c) => c.key === 'incident-summary')).toMatchObject({ sub: 'surfaces=employee_space', tone: 'warn' })
    expect(api.loopRuntimeTruthCards.value.find((c) => c.key === 'surface-ready')).toMatchObject({ sub: 'repair · participants', tone: 'bad' })
    expect(api.loopRuntimeSurfaceReadinessCards.value.map((c) => [c.key, c.stateLabel, c.tone])).toEqual([
      ['employee_space', '异常', 'bad'], ['duty_roster_graph', '就绪', 'ok'], ['self_evolution_loop_runtime', '未知', 'warn']])
    expect(api.loopWorkspaceActionCards.value[0]).toMatchObject({ title: 'Repair binding', cta: '去编制图谱处理', tone: 'bad' })
  })
  it('accepts backend validation evidence and explicit governance action capabilities', () => {
    const { api } = setup()
    api.loopRuntime.value = valid({ contract_validation: { ok: false, missing_fields: ['server-field', ''], surface_readiness: {} },
      ui_bridge: { title: 'Review roster', primary_surface: 'duty_roster_graph', detail: 'Audit needed',
        governance_action: { label: 'Audit', status: 'blocked', executable: false, requires_admin: true } } })
    expect(api.loopRuntimeContractMissingFields.value).toEqual(['server-field'])
    expect(api.loopGovernanceBridge.value).toMatchObject({ title: 'Review roster', actionLabel: 'Audit', actionStatus: 'blocked', actionExecutable: false, actionRequiresAdmin: true })
  })
  it.each([
    [{}, '待命'], [{ should_run: true }, '达到阈值'], [{ reason: 'cooldown' }, '冷却中'],
  ])('keeps a valid idle runtime status truthful for %j', (current_gate, expected) => {
    const { api } = setup()
    api.loopRuntime.value = valid({ current_gate })
    expect(api.loopStatusLabel.value).toBe(expected)
    expect(api.loopDiagnosis.value.title).toBe('本轮未看到编制员工参与')
    expect(api.loopGovernanceBridge.value.actionStatus).toBe('waiting')
  })
})
