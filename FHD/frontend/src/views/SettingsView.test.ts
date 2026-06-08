import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SettingsView from './SettingsView.vue'

describe('SettingsView.vue', () => {
  it('mounts without throwing', () => {
    const wrapper = mount(SettingsView, {
      global: {
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
