import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import GlobalReadTokenPrompt from './GlobalReadTokenPrompt.vue'

describe('GlobalReadTokenPrompt', () => {
  it('mounts without error', () => {
    const wrapper = mount(GlobalReadTokenPrompt)
    expect(wrapper.exists()).toBe(true)
  })

  it('renders nothing (v-if=false stub)', () => {
    const wrapper = mount(GlobalReadTokenPrompt)
    expect(wrapper.find('div').exists()).toBe(false)
  })

  it('has empty template output (only v-if comment)', () => {
    const wrapper = mount(GlobalReadTokenPrompt)
    expect(wrapper.find('div').exists()).toBe(false)
  })
})
