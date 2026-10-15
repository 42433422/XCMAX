import { mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { expect, it, vi } from 'vitest'
import MobileBottomNav from './MobileBottomNav.vue'
const state = vi.hoisted(() => ({ push: vi.fn(), route: null as any }))
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => ({ push: state.push }) }))

it('tracks each primary route, avoids duplicate navigation, and leaves other routes unselected', async () => {
  state.route = reactive({ name: undefined as string | undefined }); state.push.mockClear()
  const wrapper = mount(MobileBottomNav)
  expect(wrapper.get('nav').attributes('aria-label')).toBe('主导航')
  expect(wrapper.find('.active').exists()).toBe(false)
  for (const [index, name] of ['chat', 'discover', 'im', 'mod-store', 'settings'].entries()) {
    await wrapper.findAll('button')[index].trigger('click')
    expect(state.push).toHaveBeenLastCalledWith({ name })
    state.route.name = name; await wrapper.vm.$nextTick()
    expect(wrapper.findAll('[aria-current="page"]')).toHaveLength(1)
    expect(wrapper.findAll('button')[index].classes()).toContain('active')
    state.push.mockClear()
    await wrapper.findAll('button')[index].trigger('click')
    expect(state.push).not.toHaveBeenCalled()
  }
  state.route.name = 'customers'; await wrapper.vm.$nextTick()
  expect(wrapper.find('.active').exists()).toBe(false)
  wrapper.unmount()
})
