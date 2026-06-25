import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ContractEsignPanel from './ContractEsignPanel.vue'

describe('ContractEsignPanel', () => {
  it('renders the stub banner text', () => {
    const wrapper = mount(ContractEsignPanel)
    expect(wrapper.find('.contract-esign-stub').exists()).toBe(true)
    expect(wrapper.text()).toContain('电子签面板仅在企业运维/客服场景可用')
  })

  it('applies muted class', () => {
    const wrapper = mount(ContractEsignPanel)
    expect(wrapper.find('.contract-esign-stub.muted').exists()).toBe(true)
  })

  it('accepts marketUserId prop without error', () => {
    const wrapper = mount(ContractEsignPanel, {
      props: { marketUserId: 42, username: 'alice', partyA: '甲方', compact: true },
    })
    expect(wrapper.find('.contract-esign-stub').exists()).toBe(true)
  })

  it('emits updated event when triggered manually', () => {
    const wrapper = mount(ContractEsignPanel)
    wrapper.vm.$emit('updated', { id: 1 })
    expect(wrapper.emitted('updated')).toBeTruthy()
    expect((wrapper.emitted('updated')![0][0] as Record<string, unknown>).id).toBe(1)
  })
})
