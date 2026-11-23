import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import EmployeeWorkspaceScene from './EmployeeWorkspaceScene.vue'
const state = vi.hoisted(() => ({ admin: false, loaded: vi.fn() }))
const desks = ref<any[]>([])
const syncState = ref({ connected: true, stale: false, lastVerifiedAt: 1, error: '' })
const departments = ref(Object.fromEntries(['市场营销部', '商务合作部', '数字平台部', '智能应用研发部', '软件研发部', '安全治理部'].map((label, i) => [`dept-${i}`, { label, subzones: { zone: { label: '业务区', ids: [`emp-${i}`] } } }])))
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({ useWorkflowEmployeeDesks: () => ({ desks, syncState, isBusy: (row: any) => !!row.snapshot?.visuallyBusy }) }))
vi.mock('@/composables/useDutyRoster', () => ({ useDutyRoster: () => ({ departments, allPlannedIds: ref(new Set(['emp-0', 'emp-1'])), ensureLoaded: state.loaded, error: ref(null) }) }))
vi.mock('@/composables/useWorkflowEmployeeRegistrySync', () => ({ useWorkflowEmployeeRegistrySync: () => ({ error: ref(''), refresh: vi.fn() }) }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => state.admin }))
vi.mock('@/utils/modWorkflowEmployees', () => ({ isCustomPhaseEmployeeCarrierModId: (id: string) => id === 'custom-phase' }))
vi.mock('@/composables/useLoopRuntimeConsole', () => ({ loopString: (value: unknown) => String(value || '').trim() }))
async function mountScene() {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }, ...['employee-workbench', 'duty-roster-graph', 'workflow-employee-stitch-full'].map(name => ({ path: `/${name}`, name, component: { template: '<div />' } }))] })
  await router.push('/'); await router.isReady()
  const wrapper = mount(EmployeeWorkspaceScene, { global: { plugins: [router], stubs: {
    PixelOfficeScene: { name: 'PixelOfficeScene', props: ['desks', 'zones', 'selectedEmpId'], emits: ['select'], template: '<div><button data-select @click="$emit(\'select\', desks[0]?.empId)">选中员工</button></div>' },
    WorkflowEmployeeInspector: { name: 'WorkflowEmployeeInspector', props: ['desks', 'selectedEmpId'], template: '<aside />' },
  } } }); await flushPromises(); return { wrapper, router }
}
describe('employee office uses the organization and task SSOT', () => {
  beforeEach(() => { state.admin = false; state.loaded.mockReset(); desks.value = []; syncState.value = { connected: true, stale: false, lastVerifiedAt: 1, error: '' } })
  it('preserves four enterprise departments and honours explicit manifest assignment', async () => {
    desks.value = [{ empId: 'custom-worker', shortName: '客服', panelTitle: '客服', enterpriseLayer: 'execution', enabled: true }]
    const { wrapper } = await mountScene(); const zones = wrapper.getComponent({ name: 'PixelOfficeScene' }).props('zones')
    expect(zones.map((zone: any) => zone.label)).toEqual(['信息技术部', '业务运营部', '综合服务部', '运营管理部'])
    expect(zones.find((zone: any) => zone.id === 'execution').employeeIds).toEqual(['custom-worker']); wrapper.unmount()
  })
  it('preserves six admin departments and excludes employees outside the permitted roster', async () => {
    state.admin = true; desks.value = ['emp-0', 'unrelated'].map(empId => ({ empId, shortName: empId, enabled: true }))
    const { wrapper } = await mountScene(); const office = wrapper.getComponent({ name: 'PixelOfficeScene' })
    expect(office.props('zones')).toHaveLength(6); expect(office.props('desks').map((row: any) => row.empId)).toEqual(['emp-0']); expect(state.loaded).toHaveBeenCalledOnce(); wrapper.unmount()
  })
  it('keeps one employee selection in the office, inspector and cross-view links', async () => {
    desks.value = [{ empId: 'emp-0', shortName: '员工', enabled: true }]
    const { wrapper, router } = await mountScene(); await wrapper.get('[data-select]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.employee).toBe('emp-0'); expect(wrapper.getComponent({ name: 'WorkflowEmployeeInspector' }).props('selectedEmpId')).toBe('emp-0')
    expect(wrapper.findAll('a').every(link => link.attributes('href')?.includes('employee=emp-0'))).toBe(true); wrapper.unmount()
  })
  it('shows stale synchronization explicitly and never adds absent employees to the registry', async () => {
    syncState.value = { connected: false, stale: true, lastVerifiedAt: 1, error: '网络断开' }
    const { wrapper } = await mountScene(); expect(wrapper.get('[role="status"]').text()).toBe('状态待核实'); expect(wrapper.get('[role="alert"]').text()).toContain('网络断开')
    expect(wrapper.getComponent({ name: 'PixelOfficeScene' }).props('desks')).toEqual([]); expect(wrapper.text()).toContain('当前企业暂无已安装员工'); wrapper.unmount()
  })
  it('excludes unconfirmed receipts and counts a shared completed task once', async () => {
    const metadata = { employee_assignments: ['emp-0', 'emp-1'].map(employee_id => ({ employee_id, status: 'completed', step_id: employee_id })) }
    const confirmed = { task_id: 'confirmed', status: 'completed', metadata }
    const uncertain = { task_id: 'uncertain', status: 'completed', metadata: { ...metadata, reconciliation_required: true } }
    desks.value = ['emp-0', 'emp-1'].map(empId => ({ empId, shortName: empId, enabled: true, tasks: [confirmed, uncertain] }))
    const { wrapper } = await mountScene()
    expect(wrapper.findAll('.ews-stats > div').find(item => item.text().includes('近期完成任务'))?.get('strong').text()).toBe('1')
    wrapper.unmount()
  })
})
