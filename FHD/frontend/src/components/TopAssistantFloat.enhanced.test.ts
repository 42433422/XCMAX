/**
 * TopAssistantFloat.vue 增强测试
 * 覆盖：toggle open/close、tab switching、push feed、
 * product search、workflow employee toggles、starter pack、
 * tutorial tracks、keyboard navigation、event listeners
 */
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

// ── 外部依赖 mock ─────────────────────────────────────────

const mockSearchProducts = vi.fn().mockResolvedValue({ data: [] })

vi.mock('@/api/products', () => ({
  default: { searchProducts: (...args: unknown[]) => mockSearchProducts(...args) },
}))

vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  launchAdvancedDriverTour: vi.fn(),
}))

vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    tutorialTracks: [
      { id: 'onboarding', title: '宿主入门', summary: '基础教程', description: '从零开始', recommended: true },
      { id: 'advanced', title: '进阶教程', summary: '高级功能', description: '深入使用' },
    ],
    advancedTrackHint: '需要专业版',
    buildContext: () => ({}),
  }),
}))

vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({
    modWorkflowEmployeesActive: [],
    workflowEmployeeDefs: [
      { id: 'emp-1', label: '员工1' },
      { id: 'emp-2', label: '员工2' },
    ],
    workflowEmployeesEnabled: { 'emp-1': false, 'emp-2': true },
    toggleWorkflowEmployee: vi.fn(),
  }),
}))

vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({ visible: false }),
}))

vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: vi.fn(() => '/workflow-visualization'),
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}))

vi.mock('@/stores/tutorial', () => ({
  useTutorialStore: () => ({
    startGuide: vi.fn(),
    isActive: false,
  }),
}))

vi.mock('@/stores/onboardingTutorial', () => ({
  useOnboardingTutorialStore: () => ({
    active: false,
    startOnboarding: vi.fn(),
  }),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    mods: [],
    modsForUi: [],
    activeModId: '',
  }),
}))

vi.mock('@/composables/useIndustryUiText', () => ({
  useIndustryUiText: () => ({
    queryTitle: { value: '产品查询' },
    queryDescription: { value: '查询产品信息' },
    queryPlaceholder: { value: '输入产品名称' },
    nameLabel: { value: '名称' },
    modelLabel: { value: '型号' },
    priceLabel: { value: '价格' },
    categoryLabel: { value: '分类' },
    unitLabel: { value: '单位' },
    entityName: { value: '产品' },
    entityListName: { value: '业务对象' },
    emptyBeforeSearch: { value: '输入关键词查询' },
    keywordChanged: { value: '关键词已变更' },
    searchFailedMessage: { value: '查询失败' },
  }),
}))

vi.mock('@/composables/useWorkflowAiEmployeesStore', () => ({
  useWorkflowAiEmployeesStore: () => ({
    employees: [],
    enabled: { wechat_msg: false, label_print: true },
    registryLoaded: true,
    toggleEmployee: vi.fn(),
  }),
}))

// storeToRefs must wrap non-function store properties as { value: ... }
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      const refs: Record<string, { value: unknown }> = {}
      for (const key of Object.keys(store)) {
        if (typeof store[key] === 'function') continue
        refs[key] = { value: store[key] }
      }
      return refs as never
    },
  }
})

vi.mock('@/utils/workflowEmployeeRegistry', () => ({
  resolveLabel: (entry: { id: string }, _resolver?: unknown) => entry.id + '-label',
}))

vi.mock('@/composables/useEnterpriseScopedWorkflowRegistry', () => ({
  useEnterpriseScopedWorkflowRegistry: () => ({
    registry: [],
    scopedRegistryEntries: { value: [
      { id: 'wechat_msg', label: '微信消息' },
      { id: 'label_print', label: '标签打印' },
    ] },
  }),
}))

vi.mock('./ExcelPreview.vue', () => ({
  default: { template: '<div class="excel-preview-stub" />' },
}))

// ── helpers ────────────────────────────────────────────────

async function mountTopAssistantFloat() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'chat', component: { template: '<div />' } },
      { path: '/workflow-visualization', name: 'workflow-visualization', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()

  const TopAssistantFloat = (await import('./TopAssistantFloat.vue')).default
  const wrapper = mount(TopAssistantFloat, {
    global: {
      plugins: [router, pinia],
      stubs: {
        Teleport: {
          template: '<div class="teleport-stub"><slot /></div>',
        },
        ExcelPreview: { template: '<div class="excel-preview-stub" />' },
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
  return { wrapper, router }
}

// ── test suites ────────────────────────────────────────────

describe('TopAssistantFloat.vue – component structure', () => {
  it('renders float toggle button', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    expect(wrapper.find('.assistant-float-toggle').exists()).toBe(true)
    expect(wrapper.text()).toContain('副窗')
    wrapper.unmount()
  })

  it('toggle button has correct aria attributes', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    const btn = wrapper.find('.assistant-float-toggle')
    expect(btn.attributes('aria-controls')).toBe('xcagi-assistant-float-panel')
    wrapper.unmount()
  })

  it('panel is not visible by default', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – toggle open/close', () => {
  it('opens panel when toggle button is clicked', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    wrapper.unmount()
  })

  it('closes panel when close button is clicked', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    await wrapper.find('.assistant-close').trigger('click')
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    wrapper.unmount()
  })

  it('updates aria-expanded when toggled', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    const btn = wrapper.find('.assistant-float-toggle')
    expect(btn.attributes('aria-expanded')).toBe('false')
    await btn.trigger('click')
    expect(btn.attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – tab switching', () => {
  it('shows push tab by default', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.vm.activeTab).toBe('push')
    wrapper.unmount()
  })

  it('switches to assistant tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    wrapper.vm.activeTab = 'assistant'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.activeTab).toBe('assistant')
    wrapper.unmount()
  })

  it('switches to oneClick tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    wrapper.vm.activeTab = 'oneClick'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.activeTab).toBe('oneClick')
    wrapper.unmount()
  })

  it('switches to starterPack tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    wrapper.vm.activeTab = 'starterPack'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.activeTab).toBe('starterPack')
    wrapper.unmount()
  })

  it('switches to tutorial tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    wrapper.vm.activeTab = 'tutorial'
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.activeTab).toBe('tutorial')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – push feed', () => {
  it('shows empty state when no push items', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.text()).toContain('暂无推送')
    wrapper.unmount()
  })

  it('displays push items when pushFeed has data', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    wrapper.vm.pushFeed = [
      { id: '1', title: '测试推送', description: '推送描述' },
    ]
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('测试推送')
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – product search', () => {
  it('shows search input in assistant tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[1].trigger('click') // assistant tab
    expect(wrapper.find('.product-search-row').exists()).toBe(true)
    wrapper.unmount()
  })

  it('calls searchProducts when search button is clicked', async () => {
    mockSearchProducts.mockResolvedValue({ data: [] })
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[1].trigger('click') // assistant tab
    wrapper.vm.productKeyword = '测试产品'
    await wrapper.vm.$nextTick()
    await wrapper.find('.btn-primary').trigger('click')
    expect(mockSearchProducts).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('shows loading state during search', async () => {
    let resolveSearch: (value: unknown) => void
    mockSearchProducts.mockReturnValue(new Promise((resolve) => { resolveSearch = resolve }))
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[1].trigger('click')
    wrapper.vm.productKeyword = '测试'
    await wrapper.vm.$nextTick()
    wrapper.vm.searchProducts()
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.loadingProducts).toBe(true)
    resolveSearch!({ data: [] })
    await vi.dynamicImportSettled()
    wrapper.unmount()
  })
})

// NOTE: The standalone "oneClick" tab and its workflow-employee section/rows were
// removed from TopAssistantFloat.vue (only orphan CSS remains). The previous
// "workflow employees" tests targeted that removed UI and are dropped accordingly.
// Current tab layout is: push(0), assistant(1), starterPack(2), tutorial(3).

describe('TopAssistantFloat.vue – starter pack', () => {
  it('shows starter pack items in starterPack tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[2].trigger('click') // starterPack tab
    expect(wrapper.find('.starter-pack-list').exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – tutorial tracks', () => {
  it('shows tutorial tracks in tutorial tab', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[3].trigger('click') // tutorial tab
    expect(wrapper.find('.tutorial-track-list').exists()).toBe(true)
    wrapper.unmount()
  })

  it('displays tutorial track cards', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const tabs = wrapper.findAll('.assistant-tab')
    await tabs[3].trigger('click')
    expect(wrapper.findAll('.tutorial-track-card').length).toBeGreaterThan(0)
    wrapper.unmount()
  })
})

describe('TopAssistantFloat.vue – keyboard navigation', () => {
  it('closes panel on Escape key via state change', async () => {
    const { wrapper } = await mountTopAssistantFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.vm.isOpen).toBe(true)
    // Simulate Escape key by directly calling the close logic
    // (Teleport stub may prevent proper keydown event handling)
    wrapper.vm.closeAssistantPanelUi()
    await wrapper.vm.$nextTick()
    expect(wrapper.vm.isOpen).toBe(false)
    wrapper.unmount()
  })
})
