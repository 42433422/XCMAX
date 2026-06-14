import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import KittenAnalyzerView from './KittenAnalyzerView.vue'

vi.mock('@/composables/useKittenVizEmployees', () => ({
  useKittenVizEmployees: () => ({
    employees: [],
    selectedVizEmployee: { pkgId: '' },
    vizInstalledCount: 0,
    vizLoading: false,
    onVizEmployeeSelect: vi.fn(),
  }),
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
}))
vi.mock('@/api/core', () => ({
  buildFullApiUrl: (p: string) => p,
}))

describe('KittenAnalyzerView.vue', () => {
  it('mounts shell with title', () => {
    const wrapper = mount(KittenAnalyzerView, {
      global: {
        stubs: {
          KittenChartPanel: true,
          KittenLauncherIcon: true,
          KittenVizEmployeeStrip: true,
        },
      },
    })
    expect(wrapper.find('.kitten-shell').exists()).toBe(true)
    expect(wrapper.text()).toContain('智慧分析')
  })

  it('emits back on header button', async () => {
    const wrapper = mount(KittenAnalyzerView, {
      global: {
        stubs: {
          KittenChartPanel: true,
          KittenLauncherIcon: true,
          KittenVizEmployeeStrip: true,
        },
      },
    })
    await wrapper.find('.kitten-back').trigger('click')
    expect(wrapper.emitted('back')).toBeTruthy()
  })
})
