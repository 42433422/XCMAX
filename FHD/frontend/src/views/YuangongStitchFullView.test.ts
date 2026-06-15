import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// Mock heavy dependencies
vi.mock('@/composables/useWorkflowEmployeeDesks', () => ({
  useWorkflowEmployeeDesks: () => ({
    desks: { value: [
      { empId: 'emp-001', shortName: '张三', panelTitle: '管理', enabled: true, snapshot: { visuallyBusy: false } },
      { empId: 'emp-002', shortName: '李四', panelTitle: '工具', enabled: true, snapshot: { visuallyBusy: true } },
    ] },
    isBusy: (row: any) => Boolean(row.snapshot?.visuallyBusy),
  }),
}))
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
vi.mock('@/utils/workflowEmployeeScope', () => ({
  workflowRegistryEntryBelongsToStack: () => true,
}))
vi.mock('@/utils/enterpriseModStackApi', () => ({
  resolveEnterpriseModStack: vi.fn().mockResolvedValue(null),
}))
vi.mock('@/utils/platformShellApi', () => ({
  fetchEmployeePlannerStatus: vi.fn().mockResolvedValue({}),
}))
vi.mock('@/utils/officeToolDeskRows', () => ({
  buildOfficeToolDeskRows: () => [],
  resolveOfficeInstalledPackIds: () => [],
}))
vi.mock('@/components/workflow/EnterpriseEstablishmentGraph.vue', () => ({
  default: { name: 'EnterpriseEstablishmentGraph', template: '<div class="mock-graph" />', props: ['desks', 'selectedEmpId', 'isBusy', 'enterpriseStackLabel'] },
}))
vi.mock('@/components/workflow/WorkflowEmployeeInspector.vue', () => ({
  default: { name: 'WorkflowEmployeeInspector', template: '<div class="mock-inspector" />', props: ['selectedEmpId', 'desks'] },
}))
vi.mock('@/components/PaneResizeHandle.vue', () => ({
  default: { name: 'PaneResizeHandle', template: '<div class="mock-resize-handle" />', props: ['orientation', 'label'] },
}))

import YuangongStitchFullView from '@/views/YuangongStitchFullView.vue'

function mountComponent() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { name: 'workflow-employee-space', path: '/workflow/employee-space', component: { template: '<div />' } },
    ],
  })
  return mount(YuangongStitchFullView, {
    global: {
      plugins: [router],
      stubs: {
        RouterLink: {
          name: 'RouterLink',
          props: ['to'],
          template: '<a class="router-link" :href="typeof to === \'string\' ? to : to.name"><slot /></a>',
        },
      },
    },
  })
}

describe('YuangongStitchFullView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the page container', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.page-view').exists()).toBe(true)
  })

  it('renders the page title', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('员工工作流全景')
  })

  it('renders the description', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('四部门节点图')
  })

  it('renders stats section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.psf-stats').exists()).toBe(true)
  })

  it('renders total count stat', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('总工位')
  })

  it('renders enabled count stat', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('已托管')
  })

  it('renders busy count stat', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('工作中')
  })

  it('renders idle count stat', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('待命')
  })

  it('renders the monitor section', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.psf-monitor').exists()).toBe(true)
  })

  it('renders EnterpriseEstablishmentGraph', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.mock-graph').exists()).toBe(true)
  })

  it('renders WorkflowEmployeeInspector', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.mock-inspector').exists()).toBe(true)
  })

  it('renders back link text', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('返回员工空间')
  })

  it('renders PaneResizeHandle', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.mock-resize-handle').exists()).toBe(true)
  })

  it('renders stat values as numbers', () => {
    const wrapper = mountComponent()
    const statValues = wrapper.findAll('.psf-stat-v')
    expect(statValues.length).toBe(4)
    for (const sv of statValues) {
      expect(!isNaN(Number(sv.text())) || sv.text() === '0').toBe(true)
    }
  })

  it('renders workflow visualization nav link text when visible', () => {
    const wrapper = mountComponent()
    expect(wrapper.text()).toContain('流程全景说明')
  })
})
