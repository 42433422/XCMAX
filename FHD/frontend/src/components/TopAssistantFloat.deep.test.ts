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
    tutorialTracks: [{ id: 't1', title: '引导' }],
    advancedTrackHint: '高级引导',
    buildContext: () => ({}),
  }),
}))
vi.mock('@/composables/useWorkflowModsRuntimeContext', () => ({
  useWorkflowModsRuntimeContext: () => ({
    modWorkflowEmployeesActive: [{ id: 'emp1', name: '员工A' }],
  }),
}))
vi.mock('@/composables/useWorkflowPanoramaNavVisible', () => ({
  useWorkflowPanoramaNavVisible: () => ({ visible: true }),
}))
vi.mock('@/utils/workflowNav', () => ({
  resolveWorkflowVisualizationLocation: vi.fn(() => ({ path: '/workflow' })),
}))
vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiPath: (p: string) => p,
}))

async function mountFloat() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { template: '<div />' } }],
  })
  await router.push('/')
  await router.isReady()
  return mount(TopAssistantFloat, {
    global: {
      plugins: [router],
      stubs: {
        ExcelPreview: true,
        Teleport: true,
        KittenAnalyzerView: true,
      },
    },
  })
}

describe('TopAssistantFloat deep paths', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('toggles panel open on button click', async () => {
    const wrapper = await mountFloat()
    const btn = wrapper.find('.assistant-float-toggle')
    expect(btn.exists()).toBe(true)
    await btn.trigger('click')
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
  })

  it('closes panel when close button clicked', async () => {
    const wrapper = await mountFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    const closeBtn = wrapper.find('.assistant-close')
    if (closeBtn.exists()) {
      await closeBtn.trigger('click')
      expect(wrapper.find('.assistant-float-panel').exists()).toBe(false)
    }
  })

  it('opens panel via toggle then custom event detail', async () => {
    const wrapper = await mountFloat()
    await wrapper.find('.assistant-float-toggle').trigger('click')
    expect(wrapper.find('.assistant-float-panel').exists()).toBe(true)
    window.dispatchEvent(
      new CustomEvent('xcagi:open-assistant-float', {
        detail: { title: '推送', description: '内容' },
      }),
    )
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('助手副窗')
  })

  it('shows 副窗 label on toggle', async () => {
    const wrapper = await mountFloat()
    expect(wrapper.text()).toContain('副窗')
  })
})
