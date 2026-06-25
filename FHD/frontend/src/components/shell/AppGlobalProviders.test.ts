import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AppGlobalProviders from './AppGlobalProviders.vue'

describe('AppGlobalProviders', () => {
  function mountComponent(props: Record<string, unknown> = {}) {
    return mount(AppGlobalProviders, {
      props,
      global: {
        stubs: {
          AppDialogHost: { template: '<div class="app-dialog-host-stub" />' },
          GlobalLanGateModal: { template: '<div class="global-lan-gate-modal-stub" />' },
        },
      },
    })
  }

  it('always renders AppDialogHost', () => {
    const wrapper = mountComponent({ showLanGate: false })
    expect(wrapper.find('.app-dialog-host-stub').exists()).toBe(true)
  })

  it('does not render GlobalLanGateModal when showLanGate is false', () => {
    const wrapper = mountComponent({ showLanGate: false })
    expect(wrapper.find('.global-lan-gate-modal-stub').exists()).toBe(false)
  })

  it('renders GlobalLanGateModal when showLanGate is true', () => {
    const wrapper = mountComponent({ showLanGate: true })
    expect(wrapper.find('.global-lan-gate-modal-stub').exists()).toBe(true)
  })

  it('toggles GlobalLanGateModal when showLanGate prop changes', async () => {
    const wrapper = mountComponent({ showLanGate: false })
    expect(wrapper.find('.global-lan-gate-modal-stub').exists()).toBe(false)
    await wrapper.setProps({ showLanGate: true })
    expect(wrapper.find('.global-lan-gate-modal-stub').exists()).toBe(true)
    await wrapper.setProps({ showLanGate: false })
    expect(wrapper.find('.global-lan-gate-modal-stub').exists()).toBe(false)
  })
})
