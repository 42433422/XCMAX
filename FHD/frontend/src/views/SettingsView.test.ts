import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
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
