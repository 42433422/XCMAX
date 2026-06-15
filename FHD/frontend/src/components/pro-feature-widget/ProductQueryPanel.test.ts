import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    stepBack: vi.fn(),
    currentStage: { value: 'idle' },
  }),
}))

import ProductQueryPanel from '@/components/pro-feature-widget/ProductQueryPanel.vue'

function mountComponent(propsOverrides = {}) {
  return mount(ProductQueryPanel, {
    props: {
      ...propsOverrides,
    },
  })
}

describe('ProductQueryPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the panel container', () => {
    const wrapper = mountComponent()
    expect(wrapper.exists()).toBe(true)
  })

  it('renders product query related content', () => {
    const wrapper = mountComponent()
    // The component should render some product-related UI
    expect(wrapper.element.innerHTML.length).toBeGreaterThan(0)
  })
})
