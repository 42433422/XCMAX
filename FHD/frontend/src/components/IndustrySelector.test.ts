import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import IndustrySelector from './IndustrySelector.vue'

vi.mock('@/stores/industry', () => ({
  useIndustryStore: vi.fn().mockReturnValue({
    industries: [
      { id: 'paint', name: '涂料' },
      { id: 'attendance', name: '考勤' },
    ],
    currentIndustryId: 'paint',
    currentIndustry: { id: 'paint', name: '涂料' },
    currentConfig: { units: { primary: '桶' } },
    isLoaded: true,
    initialize: vi.fn().mockResolvedValue(undefined),
  }),
}))

describe('IndustrySelector', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders current industry name', () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.text()).toContain('涂料')
  })

  it('renders primary unit', () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.text()).toContain('桶')
  })

  it('renders as readonly (no dropdown)', () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.classes()).toContain('is-readonly')
    expect(wrapper.find('.selector-dropdown').exists()).toBe(false)
  })

  it('does not toggle dropdown on click (readonly)', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.find('.selector-trigger').trigger('click')
    expect(wrapper.find('.selector-dropdown').exists()).toBe(false)
  })

  it('shows lock icon indicating readonly', () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.find('.lock-icon').exists()).toBe(true)
  })

  it('shows admin tooltip', () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.attributes('title')).toContain('行业由管理员设置')
  })

  it('shows loading text when current industry is null', async () => {
    const { useIndustryStore } = await import('@/stores/industry')
    useIndustryStore.mockReturnValueOnce({
      industries: [],
      currentIndustryId: '',
      currentIndustry: null,
      currentConfig: null,
      isLoaded: false,
      initialize: vi.fn().mockResolvedValue(undefined),
    })
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.text()).toContain('加载中...')
  })

  it('hides unit badge when primary unit is empty', async () => {
    const { useIndustryStore } = await import('@/stores/industry')
    useIndustryStore.mockReturnValueOnce({
      industries: [],
      currentIndustryId: 'paint',
      currentIndustry: { id: 'paint', name: '涂料' },
      currentConfig: { units: { primary: '' } },
      isLoaded: true,
      initialize: vi.fn().mockResolvedValue(undefined),
    })
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.find('.industry-unit').exists()).toBe(false)
  })

  it('calls initialize on mount when not loaded', async () => {
    const { useIndustryStore } = await import('@/stores/industry')
    const initialize = vi.fn().mockResolvedValue(undefined)
    useIndustryStore.mockReturnValueOnce({
      industries: [],
      currentIndustryId: '',
      currentIndustry: null,
      currentConfig: null,
      isLoaded: false,
      initialize,
    })
    await mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await vi.waitFor(() => expect(initialize).toHaveBeenCalled())
  })
})
