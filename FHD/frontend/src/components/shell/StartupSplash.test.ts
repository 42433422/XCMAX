import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import StartupSplash from './StartupSplash.vue'

describe('StartupSplash', () => {
  it('renders version from package.json and mod title', () => {
    const wrapper = mount(StartupSplash, {
      props: {
        visible: true,
        hideChrome: false,
        primaryModName: 'Demo Mod',
        startupModNames: ['Demo Mod'],
        modsLoading: false,
        modsLoadError: null,
        startupProgressPct: 42,
      },
    })
    expect(wrapper.text()).toContain('Demo Mod')
    expect(wrapper.text()).toContain('v10.0.0')
    expect(wrapper.find('.startup-progress-fill').attributes('style')).toContain('42%')
  })

  it('emits skip on pointerdown', async () => {
    const wrapper = mount(StartupSplash, {
      props: {
        visible: true,
        hideChrome: false,
        primaryModName: '',
        startupModNames: [],
        modsLoading: false,
        modsLoadError: null,
        startupProgressPct: 0,
      },
    })
    await wrapper.trigger('pointerdown')
    expect(wrapper.emitted('skip')).toHaveLength(1)
  })
})
