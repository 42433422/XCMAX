import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const toggleMock = vi.fn()
const registryEntriesRef = ref<Array<{ id: string; label_zh?: string; label_en?: string }>>([])
const registryLoadedRef = ref(true)
const enabledRef = ref<Record<string, boolean>>({})

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    toggle: toggleMock,
    registryEntries: registryEntriesRef,
    registryLoaded: registryLoadedRef,
    enabled: enabledRef,
  }),
}))

const ctxRef = ref({
  clientModsUiOff: false,
  modsDisabledByServer: false,
  isModsListLoaded: true,
})
const modWorkflowEmployeesActiveRef = ref(false)

vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({
    ctx: ctxRef,
    modWorkflowEmployeesActive: modWorkflowEmployeesActiveRef,
  }),
}))

vi.mock('@/composables/useWorkflowEmployeeRegistrySync', () => ({
  useWorkflowEmployeeRegistrySync: vi.fn(),
}))

vi.mock('@/utils/workflowEmployeeRegistry', () => ({
  resolveLabel: (entry: { label_zh?: string; label_en?: string }, _fn: unknown) =>
    entry.label_zh || entry.label_en || '未命名',
}))

vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: () => ({ name: 'workflow-visualization' }),
}))

const showWorkflowPanoramaNavRef = ref(true)
vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({
    showWorkflowPanoramaNav: showWorkflowPanoramaNavRef,
  }),
}))

import WorkflowEmployeeSelectPanel from './WorkflowEmployeeSelectPanel.vue'

function mountPanel(props: Record<string, unknown> = {}) {
  return mount(WorkflowEmployeeSelectPanel, {
    props,
    global: {
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('WorkflowEmployeeSelectPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    registryEntriesRef.value = []
    registryLoadedRef.value = true
    enabledRef.value = {}
    ctxRef.value = {
      clientModsUiOff: false,
      modsDisabledByServer: false,
      isModsListLoaded: true,
    }
    modWorkflowEmployeesActiveRef.value = false
    showWorkflowPanoramaNavRef.value = true
  })

  it('renders the section container', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-section').exists()).toBe(true)
  })

  it('renders default heading', () => {
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-heading').text()).toBe('工作流员工选择')
  })

  it('renders custom heading when provided', () => {
    const wrapper = mountPanel({ heading: '自定义标题' })
    expect(wrapper.find('.workflow-employee-heading').text()).toBe('自定义标题')
  })

  it('renders panorama link when visible', () => {
    const wrapper = mountPanel({ showPanoramaLink: true })
    expect(wrapper.find('.workflow-employee-visual-link').exists()).toBe(true)
  })

  it('hides panorama link when showPanoramaLink is false', () => {
    const wrapper = mountPanel({ showPanoramaLink: false })
    expect(wrapper.find('.workflow-employee-visual-link').exists()).toBe(false)
  })

  it('hides panorama link when showWorkflowPanoramaNav is false and prop not set', () => {
    showWorkflowPanoramaNavRef.value = false
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-visual-link').exists()).toBe(false)
  })

  it('shows hint when clientModsUiOff is true', () => {
    ctxRef.value.clientModsUiOff = true
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-hint').text()).toContain('原版模式')
  })

  it('shows hint when modsDisabledByServer is true', () => {
    ctxRef.value.modsDisabledByServer = true
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-hint').text()).toContain('XCAGI_DISABLE_MODS')
  })

  it('shows hint when mods list not loaded', () => {
    ctxRef.value.isModsListLoaded = false
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-hint').text()).toContain('同步扩展列表')
  })

  it('shows hint when registry not loaded', () => {
    registryLoadedRef.value = false
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-hint').text()).toContain('加载工作流员工注册表')
  })

  it('shows hint when no employees in registry', () => {
    registryEntriesRef.value = []
    registryLoadedRef.value = true
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-hint').text()).toContain('未加载任何工作流员工')
  })

  it('renders employee rows when registry has entries', () => {
    registryEntriesRef.value = [
      { id: 'e1', label_zh: '员工1' },
      { id: 'e2', label_zh: '员工2' },
    ]
    const wrapper = mountPanel()
    expect(wrapper.findAll('.workflow-employee-row')).toHaveLength(2)
  })

  it('renders employee label from registry', () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '测试员工' }]
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-label').text()).toBe('测试员工')
  })

  it('toggles employee when row is clicked', async () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '员工1' }]
    const wrapper = mountPanel()
    await wrapper.find('.workflow-employee-row').trigger('click')
    expect(toggleMock).toHaveBeenCalledWith('e1')
  })

  it('marks toggle as active when employee is enabled', () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '员工1' }]
    enabledRef.value = { e1: true }
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-toggle').classes()).toContain('active')
  })

  it('does not mark toggle as active when employee is disabled', () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '员工1' }]
    enabledRef.value = {}
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-toggle').classes()).not.toContain('active')
  })

  it('sets aria-pressed=true when employee is enabled', () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '员工1' }]
    enabledRef.value = { e1: true }
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-row').attributes('aria-pressed')).toBe('true')
  })

  it('sets aria-pressed=false when employee is disabled', () => {
    registryEntriesRef.value = [{ id: 'e1', label_zh: '员工1' }]
    enabledRef.value = {}
    const wrapper = mountPanel()
    expect(wrapper.find('.workflow-employee-row').attributes('aria-pressed')).toBe('false')
  })

  it('shows panorama link title based on modWorkflowEmployeesActive', () => {
    modWorkflowEmployeesActiveRef.value = true
    const wrapper = mountPanel({ showPanoramaLink: true })
    expect(wrapper.find('.workflow-employee-visual-link').attributes('title')).toContain('已安装工作流员工')
  })

  it('shows different panorama link title when no active mods', () => {
    modWorkflowEmployeesActiveRef.value = false
    const wrapper = mountPanel({ showPanoramaLink: true })
    expect(wrapper.find('.workflow-employee-visual-link').attributes('title')).toContain('工作流执行逻辑')
  })
})
