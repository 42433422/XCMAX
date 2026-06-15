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
    switchIndustry: vi.fn().mockResolvedValue(true),
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

  it('toggles dropdown on click', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    expect(wrapper.find('.selector-dropdown').exists()).toBe(false)
    await wrapper.find('.selector-trigger').trigger('click')
    expect(wrapper.find('.selector-dropdown').exists()).toBe(true)
  })

  it('closes dropdown on overlay click', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.find('.selector-trigger').trigger('click')
    expect(wrapper.find('.selector-dropdown').exists()).toBe(true)
    await wrapper.find('.dropdown-overlay').trigger('click')
    expect(wrapper.find('.selector-dropdown').exists()).toBe(false)
  })

  it('shows industry list when expanded', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.find('.selector-trigger').trigger('click')
    const items = wrapper.findAll('.dropdown-item')
    expect(items.length).toBe(2)
  })

  it('marks current industry as active', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.find('.selector-trigger').trigger('click')
    const items = wrapper.findAll('.dropdown-item')
    expect(items[0].classes()).toContain('active')
  })

  it('calls switchIndustry on item click', async () => {
    const wrapper = mount(IndustrySelector, {
      global: { plugins: [createPinia()] },
    })
    await wrapper.find('.selector-trigger').trigger('click')
    const items = wrapper.findAll('.dropdown-item')
    await items[1].trigger('click')
    const { useIndustryStore } = await import('@/stores/industry')
    expect(useIndustryStore().switchIndustry).toHaveBeenCalledWith('attendance')
  })
})
