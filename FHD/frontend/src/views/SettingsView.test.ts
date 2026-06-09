import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from './SettingsView.vue'

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', name: 'settings', component: SettingsView }],
  })
}

describe('SettingsView.vue', () => {
  it('mounts without throwing', async () => {
    const router = makeRouter()
    await router.push('/settings')
    await router.isReady()
    const wrapper = mount(SettingsView, {
      global: {
        plugins: [router],
        stubs: {
          RouterLink: true,
          ElButton: true,
          ElInput: true,
          ElSwitch: true,
          ElTabs: true,
          ElTabPane: true,
        },
      },
    })
    expect(wrapper.exists()).toBe(true)
  })
})
