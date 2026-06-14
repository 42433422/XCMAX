import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({ success: true, data: [] }) }),
  DEFAULT_MOD_API_TIMEOUT_MS: 30000,
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
  appConfirm: vi.fn().mockResolvedValue(true),
}))

const mountableViews = [
  'AdminEntitlementsView',
  'WechatContactsView',
]

describe('zero-coverage views mount', () => {
  for (const name of mountableViews) {
    it(`${name} imports and mounts`, async () => {
      setActivePinia(createPinia())
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: '/', component: { template: '<div />' } }],
      })
      const mod = await import(`./${name}.vue`)
      const wrapper = mount(mod.default, {
        global: {
          plugins: [router],
          stubs: {
            RouterLink: true,
            DataTable: true,
            Modal: true,
            ConfirmDialog: true,
            HostModBridgeView: true,
            ElButton: true,
            ElInput: true,
            ElTabs: true,
            ElTabPane: true,
            ElSelect: true,
            ElOption: true,
            ElForm: true,
            ElFormItem: true,
            ElSwitch: true,
            ElAlert: true,
            ElCard: true,
            ElTag: true,
            ElDivider: true,
            KittenAnalyzerView: true,
            AIOpenPanel: true,
          },
          mocks: { $t: (k: string) => k },
        },
      })
      expect(wrapper.exists()).toBe(true)
    })
  }
})
