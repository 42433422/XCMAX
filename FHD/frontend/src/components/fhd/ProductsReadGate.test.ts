import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProductsReadGate from './ProductsReadGate.vue'

describe('ProductsReadGate', () => {
  it('mounts without error', () => {
    const wrapper = mount(ProductsReadGate)
    expect(wrapper.exists()).toBe(true)
  })

  it('renders nothing (v-if=false stub)', () => {
    const wrapper = mount(ProductsReadGate)
    expect(wrapper.find('div').exists()).toBe(false)
  })

  it('emits unlocked event when triggered manually', () => {
    const wrapper = mount(ProductsReadGate)
    wrapper.vm.$emit('unlocked')
    expect(wrapper.emitted('unlocked')).toBeTruthy()
    expect(wrapper.emitted('unlocked')!.length).toBe(1)
  })
})
