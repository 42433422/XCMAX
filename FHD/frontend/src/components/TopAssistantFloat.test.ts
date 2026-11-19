import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import TopAssistantFloat from './TopAssistantFloat.vue'

vi.mock('@/api/products', () => ({
  default: { searchProducts: vi.fn().mockResolvedValue({ data: [] }) },
}))
vi.mock('@/tutorial/promptAdvancedTutorial', () => ({
  launchAdvancedDriverTour: vi.fn(),
}))
vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({
    tutorialTracks: [],
    advancedTrackHint: '',
    buildContext: () => ({}),
  }),
}))
vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({ modWorkflowEmployeesActive: [] }),
}))
vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({ visible: false }),
}))
vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: vi.fn(),
}))
vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}))

describe('TopAssistantFloat.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the product editor for a desktop query and removes its bridge on unmount', async () => {
    let openProducts!: (query: string) => Promise<void>
    const stop = vi.fn()
    vi.stubGlobal('xcagiDesktop', { onAssistantProductSearch: (callback: typeof openProducts) => { openProducts = callback; return stop } })
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(TopAssistantFloat, {
      global: {
        plugins: [router],
        stubs: {
          ExcelPreview: true,
          Teleport: true,
        },
      },
    })

    expect(wrapper.find('.assistant-float-toggle').exists()).toBe(true)
    expect(wrapper.text()).toContain('副窗')
    await openProducts('part-42')
    await flushPromises()
    expect(wrapper.find('#xcagi-assistant-float-panel').exists()).toBe(true)
    expect(wrapper.get('.product-search-row input').element.value).toBe('part-42')
    wrapper.unmount()
    expect(stop).toHaveBeenCalledOnce()
    vi.unstubAllGlobals()
  })
})
