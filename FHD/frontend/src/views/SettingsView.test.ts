import { describe, it, expect, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from './SettingsView.vue'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: {} }) }),
  getApiBase: () => '',
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
  appConfirm: vi.fn().mockResolvedValue(true),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', name: 'settings', component: SettingsView }],
  })
}

const globalStubs = {
  RouterLink: true,
  ElButton: true,
  ElInput: true,
  ElSwitch: true,
  ElTabs: true,
  ElTabPane: true,
  ElSelect: true,
  ElOption: true,
  ElForm: true,
  ElFormItem: true,
  ElDivider: true,
  ElAlert: true,
  // The pairing card owns async requests and long-lived timers. Its behavior is
  // covered by MobilePairingQrCard.test.ts; this suite only verifies the
  // settings shell and must not leak that child across the jsdom lifecycle.
  MobilePairingQrCard: true,
}

describe('SettingsView.vue', () => {
  it('shows one admin settings section and preserves expanded details across navigation', async () => {
    vi.stubEnv('VITE_XCMAX_ADMIN_CONSOLE', '1')
    const router = makeRouter()
    await router.push('/settings')
    const wrapper = mount(SettingsView, { global: { plugins: [router], stubs: globalStubs } })
    try {
      await flushPromises()
      expect(wrapper.get('#settings-group-system').isVisible()).toBe(true)
      expect(wrapper.get('#settings-group-intelligence').isVisible()).toBe(false)
      await wrapper.get('a[href="#settings-group-intelligence"]').trigger('click')
      const details = wrapper.get('#settings-model-payment').element as HTMLDetailsElement
      details.open = true
      await wrapper.get('a[href="#settings-group-system"]').trigger('click')
      expect(wrapper.get('#settings-group-intelligence').isVisible()).toBe(false)
      await wrapper.get('a[href="#settings-group-intelligence"]').trigger('click')
      expect(wrapper.get('#settings-group-intelligence').attributes('style')).not.toContain('display: none')
      expect(wrapper.get('#settings-model-payment').element).toBe(details)
      expect(details.open).toBe(true)
    } finally {
      wrapper.unmount()
      vi.unstubAllEnvs()
    }
  })
  it('mounts without throwing', async () => {
    const router = makeRouter()
    await router.push('/settings')
    await router.isReady()
    const wrapper = mount(SettingsView, {
      global: {
        plugins: [router],
        stubs: globalStubs,
      },
    })
    expect(wrapper.exists()).toBe(true)
    wrapper.unmount()
  })

  it('renders settings shell text', async () => {
    const router = makeRouter()
    await router.push('/settings')
    await router.isReady()
    const wrapper = mount(SettingsView, {
      global: {
        plugins: [router],
        stubs: globalStubs,
      },
    })
    expect(wrapper.text().length).toBeGreaterThan(10)
    wrapper.unmount()
  })
})
