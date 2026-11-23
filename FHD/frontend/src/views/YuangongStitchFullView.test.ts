import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

const connection = vi.hoisted(() => ({ stale: false }))
vi.mock('@/composables/useWorkflowEmployeeDesks', async () => {
  const { ref } = await import('vue')
  return { useWorkflowEmployeeDesks: () => ({
    desks: ref([
      { empId: 'emp-001', shortName: '张三', panelTitle: '管理', enabled: true, carrierModId: 'installed-directory-pack',
        snapshot: { authority: 'task-center', officeState: 'idle', stale: connection.stale, visuallyBusy: false } },
      { empId: 'emp-002', shortName: '李四', panelTitle: '工具', enabled: true,
        snapshot: { authority: 'task-center', officeState: 'working', stale: connection.stale, visuallyBusy: !connection.stale } },
      { empId: 'bridge-helper', shortName: '桥接组件', panelTitle: '载体', enabled: true, carrierModId: 'xcagi-office-employee-pack-bridge',
        snapshot: { authority: 'task-center', officeState: 'idle', stale: connection.stale, visuallyBusy: false } },
    ]),
    isBusy: (row: { snapshot?: { visuallyBusy: boolean } }) => Boolean(row.snapshot?.visuallyBusy),
    syncState: ref({ connected: !connection.stale, stale: connection.stale }),
  }) }
})
vi.mock('@/composables/useWorkflowEmployeeRegistrySync', async () => {
  const { ref } = await import('vue')
  return { useWorkflowEmployeeRegistrySync: () => ({ error: ref(''), refresh: vi.fn() }) }
})
vi.mock('@/composables/useResizablePane', () => ({
  useResizablePane: () => ({
    paneStyle: { value: {} },
    startResize: vi.fn(),
    resetSize: vi.fn(),
    stopResize: vi.fn(),
  }),
}))
vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({
    showWorkflowPanoramaNav: { value: true },
  }),
}))
vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: () => ({ name: 'workflow-visualization' }),
}))
vi.mock('@/components/workflow/EnterpriseEstablishmentGraph.vue', () => ({
  default: {
    name: 'EnterpriseEstablishmentGraph',
    template: '<div class="mock-graph" />',
    props: ['desks', 'selectedEmpId', 'isBusy', 'enterpriseStackLabel'],
  },
}))
vi.mock('@/components/workflow/WorkflowEmployeeInspector.vue', () => ({
  default: {
    name: 'WorkflowEmployeeInspector',
    template: '<div class="mock-inspector" />',
    props: ['selectedEmpId', 'desks'],
  },
}))
vi.mock('@/components/PaneResizeHandle.vue', () => ({
  default: {
    name: 'PaneResizeHandle',
    template: '<div class="mock-resize-handle" />',
    props: ['orientation', 'label'],
  },
}))

import YuangongStitchFullView from '@/views/YuangongStitchFullView.vue'

async function mountComponent(query = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  await router.push({ path: '/', query })
  await router.isReady()
  const wrapper = mount(YuangongStitchFullView, {
    global: {
      plugins: [router],
      stubs: { RouterLink: {
        name: 'RouterLink', props: ['to'],
        template: '<a class="router-link"><slot /></a>',
      } },
    },
  })
  return { wrapper, router }
}

describe('YuangongStitchFullView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    connection.stale = false
  })

  it('shows the same allowed directory as the office without rejecting a pack outside the industry stack', async () => {
    const { wrapper } = await mountComponent()
    expect(wrapper.find('.psf-title').text()).toBe('员工图谱')
    for (const department of ['信息技术部', '业务运营部', '综合服务部', '运营管理部']) {
      expect(wrapper.text()).toContain(department)
    }
    expect(wrapper.findAll('.psf-stat-v').map(item => item.text())).toEqual(['2', '2', '1', '1'])
    expect(wrapper.find('[role="status"]').text()).toContain('实时同步')
    expect(wrapper.find('.mock-inspector').exists()).toBe(true)
    expect(wrapper.getComponent({ name: 'EnterpriseEstablishmentGraph' }).props('desks').map((row: { empId: string }) => row.empId)).toEqual(['emp-001', 'emp-002'])
    wrapper.unmount()
  })

  it('preserves the focused employee in graph, inspector and workbench/office links', async () => {
    const { wrapper, router } = await mountComponent({ employee: 'emp-002' })
    const graph = wrapper.getComponent({ name: 'EnterpriseEstablishmentGraph' })
    const inspector = wrapper.getComponent({ name: 'WorkflowEmployeeInspector' })
    expect(graph.props('selectedEmpId')).toBe('emp-002')
    expect(inspector.props('selectedEmpId')).toBe('emp-002')
    graph.vm.$emit('select', 'emp-001')
    await flushPromises()
    expect(router.currentRoute.value.query.employee).toBe('emp-001')
    expect(inspector.props('selectedEmpId')).toBe('emp-001')
    const links = wrapper.findAllComponents({ name: 'RouterLink' })
    expect(links[0].props('to')).toEqual({ name: 'workflow-employee-space', query: { employee: 'emp-001' } })
    expect(links[1].props('to')).toEqual({ name: 'employee-workbench', query: { employee: 'emp-001' } })
    inspector.vm.$emit('update:selectedEmpId', 'emp-002')
    await flushPromises()
    expect(router.currentRoute.value.query.employee).toBe('emp-002')
    wrapper.unmount()
  })

  it('does not count an unverified connection as idle employees', async () => {
    connection.stale = true
    const { wrapper } = await mountComponent()
    expect(wrapper.find('[role="status"]').text()).toContain('待核对')
    expect(wrapper.findAll('.psf-stat-v').map(item => item.text())).toEqual(['2', '2', '0', '0'])
    wrapper.unmount()
  })
})
