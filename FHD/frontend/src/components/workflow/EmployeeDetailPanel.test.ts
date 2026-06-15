import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/composables/useProMode', () => ({
  useProMode: () => ({
    stepBack: vi.fn(),
    currentStage: { value: 'idle' },
  }),
}))

import EmployeeDetailPanel from '@/components/workflow/EmployeeDetailPanel.vue'

function mountComponent(propsOverrides = {}) {
  return mount(EmployeeDetailPanel, {
    props: {
      ...propsOverrides,
    },
  })
}

describe('EmployeeDetailPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders the panel container', () => {
    const wrapper = mountComponent()
    expect(wrapper.exists()).toBe(true)
  })

  it('renders employee detail content', () => {
    const wrapper = mountComponent()
    expect(wrapper.element.innerHTML.length).toBeGreaterThan(0)
  })
})
