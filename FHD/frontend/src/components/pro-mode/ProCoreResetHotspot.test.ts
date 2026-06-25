import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ProCoreResetHotspot from './ProCoreResetHotspot.vue'

describe('ProCoreResetHotspot', () => {
  it('renders the hotspot container', () => {
    const wrapper = mount(ProCoreResetHotspot)
    expect(wrapper.find('.pro-core-reset-hotspot').exists()).toBe(true)
  })

  it('renders the reset icon and label', () => {
    const wrapper = mount(ProCoreResetHotspot)
    expect(wrapper.find('.hotspot-icon').text()).toBe('↻')
    expect(wrapper.find('.hotspot-label').text()).toBe('重置')
  })

  it('applies default scale=1 to style', () => {
    const wrapper = mount(ProCoreResetHotspot)
    expect(wrapper.find('.pro-core-reset-hotspot').attributes('style')).toContain('scale(1)')
  })

  it('applies provided scale to style', () => {
    const wrapper = mount(ProCoreResetHotspot, { props: { scale: 2 } })
    expect(wrapper.find('.pro-core-reset-hotspot').attributes('style')).toContain('scale(2)')
  })

  it('emits click event when hotspot is clicked', async () => {
    const wrapper = mount(ProCoreResetHotspot)
    await wrapper.find('.pro-core-reset-hotspot').trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
    expect(wrapper.emitted('click')!.length).toBe(1)
  })

  it('emits click event on each click', async () => {
    const wrapper = mount(ProCoreResetHotspot)
    await wrapper.find('.pro-core-reset-hotspot').trigger('click')
    await wrapper.find('.pro-core-reset-hotspot').trigger('click')
    expect(wrapper.emitted('click')!.length).toBe(2)
  })

  it('positions hotspot at center via translate(-50%, -50%)', () => {
    const wrapper = mount(ProCoreResetHotspot)
    expect(wrapper.find('.pro-core-reset-hotspot').attributes('style')).toContain('translate(-50%, -50%)')
  })
})
