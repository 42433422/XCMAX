import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import EmployeeWorkspaceView from './EmployeeWorkspaceView.vue'
const state = vi.hoisted(() => ({ admin: false, loaded: vi.fn() }))
const desks = ref<any[]>([])
const syncState = ref({ connected: true, stale: false, lastVerifiedAt: 1, error: '' })
const departments = ref(Object.fromEntries(['市场营销部', '商务合作部', '数字平台部', '智能应用研发部', '软件研发部', '安全治理部'].map((label, i) => [`dept-${i}`, { label, subzones: { zone: { label: '业务区', ids: [`emp-${i}`] } } }])))
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({
  useWorkflowEmployeeDesks: () => ({ desks, syncState }),
  resolveDeskStatusLine: (row: { snapshot?: { stage: string } }) => row.snapshot?.stage || '暂无快照',
}))
vi.mock('@/composables/useDutyRoster', () => ({ useDutyRoster: () => ({ departments, allPlannedIds: ref(new Set(['emp-0', 'emp-1'])), ensureLoaded: state.loaded, error: ref(null) }) }))
vi.mock('@/composables/useWorkflowEmployeeRegistrySync', () => ({ useWorkflowEmployeeRegistrySync: () => ({ error: ref(''), refresh: vi.fn() }) }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => state.admin }))
vi.mock('@/utils/modWorkflowEmployees', () => ({ isCustomPhaseEmployeeCarrierModId: (id: string) => id === 'custom-phase' }))
vi.mock('@/composables/useLoopRuntimeConsole', () => ({ loopString: (value: unknown) => String(value || '').trim() }))
async function mountScene() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/workflow-employee-space', name: 'workflow-employee-space', component: EmployeeWorkspaceView },
    { path: '/employee-workbench', name: 'employee-workbench', component: { template: '<div />' } },
  ] })
  await router.push('/workflow-employee-space'); await router.isReady()
  const wrapper = mount({ template: '<router-view v-slot="{ Component, route }"><keep-alive><component :is="Component" :key="route.fullPath" /></keep-alive></router-view>' }, {
    global: { plugins: [router], stubs: {
      PixelOfficeScene: { name: 'PixelOfficeScene', props: ['desks', 'zones', 'selectedEmpId'], emits: ['select'], template: '<section><slot /><button data-select @click="$emit(\'select\', desks[0]?.empId)">选中员工</button></section>' },
      ElDialog: { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<section v-if="modelValue" role="dialog" :aria-label="title"><slot/><button data-close @click="$emit(\'update:modelValue\', false)">关闭</button></section>' },
    } },
  }); await flushPromises(); return { wrapper, router }
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
  it('opens employee details across desktop route remounts and closes back to the office', async () => {
    desks.value = [{ empId: 'emp-0', shortName: '客服', enabled: true, enterpriseLayer: 'execution',
      snapshot: { stage: '正在核对订单' }, tasks: [{ task_id: 'task-1', title: '核对订单', status: 'running', metadata: { employee_id: 'emp-0' } }] }]
    const { wrapper, router } = await mountScene()
    const office = wrapper.getComponent({ name: 'PixelOfficeScene' })
    expect([...wrapper.get('.page-content').element.children]).toEqual([office.element])
    expect(office.attributes('data-tour')).toBe('employee-workspace-desks')
    expect(wrapper.find('aside, [role="dialog"]').exists()).toBe(false)
    await office.get('[data-select]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.employee).toBe('emp-0')
    const panel = wrapper.get('[role="dialog"]')
    expect(panel.attributes('aria-label')).toBe('客服')
    expect(panel.text()).toContain('正在核对订单')
    expect(panel.get('a').attributes('href')).toBe('/employee-workbench?employee=emp-0&task=task-1')
    await panel.get('[data-close]').trigger('click'); await flushPromises()
    expect(router.currentRoute.value.query.employee).toBeUndefined()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('shows stale synchronization explicitly and never adds absent employees to the registry', async () => {
    syncState.value = { connected: false, stale: true, lastVerifiedAt: 1, error: '网络断开' }
    const { wrapper } = await mountScene()
    const office = wrapper.getComponent({ name: 'PixelOfficeScene' })
    expect(office.get('[role="alert"]').text()).toContain('网络断开')
    expect(office.props('desks')).toEqual([])
    wrapper.unmount()
  })
})
