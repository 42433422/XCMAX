import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProMode from './ProMode.vue'

describe('ProMode', () => {
  it('renders the legacy pro mode wrapper', () => {
    const wrapper = mount(ProMode, {
      global: {
        stubs: {
          LegacyProMode: { template: '<div class="legacy-pro-mode-stub" />' },
        },
      },
    })
    expect(wrapper.find('.legacy-pro-mode-stub').exists()).toBe(true)
  })

  it('forwards attrs to the legacy component', () => {
    const wrapper = mount(ProMode, {
      attrs: { 'data-test': 'forwarded' },
      global: {
        stubs: {
          LegacyProMode: {
            inheritAttrs: false,
            template: '<div class="legacy-pro-mode-stub" v-bind="$attrs" />',
          },
        },
      },
    })
    expect(wrapper.find('.legacy-pro-mode-stub').attributes('data-test')).toBe('forwarded')
  })
})
