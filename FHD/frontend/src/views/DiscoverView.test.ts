import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import DiscoverView from './DiscoverView.vue'

describe('DiscoverView.vue', () => {
  it('mounts discover shell', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/discover', component: DiscoverView }],
    })
    await router.push('/discover')
    await router.isReady()
    const wrapper = mount(DiscoverView, {
      global: { plugins: [router], stubs: { RouterLink: true } },
    })
    expect(wrapper.exists()).toBe(true)
  })
})
