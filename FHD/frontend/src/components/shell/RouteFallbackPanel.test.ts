import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import RouteFallbackPanel from './RouteFallbackPanel.vue'

const { push, back } = vi.hoisted(() => ({ push: vi.fn(), back: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push, back }) }))

describe('RouteFallbackPanel', () => {
  beforeEach(() => { push.mockReset(); back.mockReset() })
  it('explains a missing page instead of rendering blank and offers home/back', async () => {
    const wrapper = mount(RouteFallbackPanel, { props: { mode: 'not-found', path: '/users-x' } })
    expect(wrapper.text()).toContain('没有找到这个页面')
    expect(wrapper.text()).toContain('/users-x')
    expect(wrapper.text()).not.toContain('刷新页面')
    const buttons = wrapper.findAll('button')
    await buttons.find((b) => b.text() === '回到首页')!.trigger('click')
    expect(push).toHaveBeenCalledWith('/')
    await buttons.find((b) => b.text() === '返回上一页')!.trigger('click')
    expect(back).toHaveBeenCalled()
    expect(wrapper.emitted('dismiss')).toHaveLength(2)
  })
  it('offers a reload for failed page assets', async () => {
    const assign = vi.fn()
    const original = window.location
    Object.defineProperty(window, 'location', { configurable: true, value: { ...original, assign } })
    const wrapper = mount(RouteFallbackPanel, { props: { mode: 'chunk-error', path: '/delivery-center' } })
    expect(wrapper.text()).toContain('页面资源加载失败')
    await wrapper.findAll('button').find((b) => b.text() === '刷新页面')!.trigger('click')
    expect(assign).toHaveBeenCalledWith(expect.stringMatching(/\/delivery-center$/))
    Object.defineProperty(window, 'location', { configurable: true, value: original })
  })
})
