import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import ModStore from './ModStore.vue'

const { fetchMarketCatalog } = vi.hoisted(() => ({
  fetchMarketCatalog: vi.fn().mockResolvedValue({
    mods: [{ id: 'mod-a', name: 'Mod A', category: 'workflow' }],
    categories: ['workflow'],
  }),
}))

vi.mock('@/utils/apiBase', () => ({
  apiFetch: vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
  DEFAULT_MOD_API_TIMEOUT_MS: 30000,
}))
vi.mock('@/api/modStore', () => ({
  fetchMarketCatalog,
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

function mountModStore() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/mod-store', component: ModStore }],
  })
  return router.push('/mod-store').then(() =>
    router.isReady().then(() =>
      mount(ModStore, {
        global: {
          plugins: [router],
          stubs: { Modal: true, ModDetails: true, RouterLink: true },
        },
      }),
    ),
  )
}

describe('ModStore deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads catalog on mount', async () => {
    const wrapper = await mountModStore()
    await vi.waitFor(() => expect(fetchMarketCatalog).toHaveBeenCalled(), { timeout: 3000 })
    expect(wrapper.find('.mod-store').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 员工市场')
  })

  it('shows market title and shell', async () => {
    const wrapper = await mountModStore()
    expect(wrapper.text()).toMatch(/市场|Mod|员工/)
  })
})
