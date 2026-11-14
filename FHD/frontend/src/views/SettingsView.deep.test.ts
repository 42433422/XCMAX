import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
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
vi.mock('@/composables/useCoreNavLabel', () => ({
  useCoreNavLabel: (k: string) => k,
}))
vi.mock('@/composables/useWorkMode', () => ({
  useWorkMode: () => ({ workMode: { value: 'standard' }, setWorkMode: vi.fn() }),
}))
vi.mock('@/stores/mods', async () => {
  const { ref } = await import('vue')
  return {
    useModsStore: () => {
      const mods = ref([])
      return {
        mods,
        activeModId: ref(''),
        clientModsUiOff: ref(false),
        loadError: ref(''),
        isLoaded: ref(true),
        modRoutes: ref([]),
        modsForUi: mods,
      }
    },
  }
})
vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    profile: { value: null },
    isLoggedIn: { value: false },
    loading: { value: false },
    refresh: vi.fn(),
  }),
}))

enableAutoUnmount(afterEach)

const globalStubs = {
  MobilePairingQrCard: true, // Its request/timer lifecycle has its own component tests.
  RouterLink: true,
  ElButton: { template: '<button><slot /></button>' },
  ElInput: { template: '<input />' },
  ElSwitch: { template: '<input type="checkbox" />' },
  ElTabs: { template: '<div class="el-tabs"><slot /></div>' },
  ElTabPane: { template: '<div class="el-tab-pane"><slot /></div>' },
  ElSelect: { template: '<select><slot /></select>' },
  ElOption: { template: '<option><slot /></option>' },
  ElForm: { template: '<form><slot /></form>' },
  ElFormItem: { template: '<div><slot /></div>' },
  ElDivider: true,
  ElAlert: true,
  ElCard: { template: '<div class="el-card"><slot /></div>' },
  ElTag: { template: '<span><slot /></span>' },
}

async function mountSettings() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: SettingsView }],
  })
  await router.push('/settings')
  await router.isReady()
  const wrapper = mount(SettingsView, {
    global: { plugins: [router], stubs: globalStubs },
  })
  await flushPromises()
  return wrapper
}

describe('SettingsView deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    // api/core uses fetch, not apiFetch. Resolve its reads before jsdom teardown
    // instead of leaving real failed requests and retry timers behind.
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async () => new Response(JSON.stringify({
      success: true, data: {}, preferences: { assistantName: 'Settings test', aiMode: 'online' },
    }), { headers: { 'Content-Type': 'application/json' } })))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('mounts and renders settings content', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('#view-settings').exists()).toBe(true)
    expect(localStorage.getItem('assistantName')).toBe('Settings test')
  })

  it('contains settings profile section', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.find('.settings-profile').exists()).toBe(true)
  })

  it('survives remount with persisted prefs', async () => {
    localStorage.setItem('xcagi_sidebar_theme', 'dark')
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
  })
})
