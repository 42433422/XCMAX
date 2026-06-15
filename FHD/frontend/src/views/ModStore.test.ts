import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ModStore from './ModStore.vue'

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  getApiBase: () => '',
  DEFAULT_MOD_API_TIMEOUT_MS: 90_000,
}))
vi.mock('@/api/modStore', () => ({
  fetchMarketCatalog: vi.fn().mockResolvedValue({ mods: [], categories: [] }),
  installHostFoundation: vi.fn().mockResolvedValue({ success: true }),
  reloadEmployeePacks: vi.fn().mockResolvedValue({ success: true }),
}))
vi.mock('@/utils/platformShellApi', () => ({
  fetchDeliverableStatus: vi.fn().mockResolvedValue({ ok: true, deliverable: true }),
  fetchIndustryBaseline: vi.fn().mockResolvedValue({ industries: [] }),
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
  appConfirm: vi.fn().mockResolvedValue(true),
}))
vi.mock('@/composables/useTutorialCatalog', () => ({
  useTutorialCatalog: () => ({ registerTour: vi.fn() }),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/mod-store', name: 'mod-store', component: ModStore }],
  })
}

describe('ModStore.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('mounts store shell', async () => {
    const router = makeRouter()
    await router.push('/mod-store')
    await router.isReady()
    const wrapper = mount(ModStore, {
      global: {
        plugins: [router],
        stubs: {
          Modal: true,
          ModDetails: true,
          RouterLink: true,
        },
      },
    })
    expect(wrapper.find('.mod-store').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 员工市场')
  })
})
