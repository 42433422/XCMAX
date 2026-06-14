import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
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

  it('renders float toggle button', async () => {
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
  })
})
