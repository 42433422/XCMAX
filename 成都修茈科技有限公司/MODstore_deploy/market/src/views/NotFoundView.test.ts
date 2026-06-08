import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import NotFoundView from './NotFoundView.vue'

describe('NotFoundView', () => {
  it('renders 404 and message', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(NotFoundView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('404')
    expect(wrapper.text()).toContain('抱歉，您访问的页面不存在')
    expect(wrapper.find('.btn-home').exists()).toBe(true)
  })
})
