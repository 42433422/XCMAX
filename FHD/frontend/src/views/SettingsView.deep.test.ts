import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
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
      const activeModId = ref('')
      const clientModsUiOff = ref(false)
      const loadError = ref('')
      const isLoaded = ref(true)
      const modRoutes = ref([])
      return {
        mods,
        activeModId,
        clientModsUiOff,
        loadError,
        isLoaded,
        modRoutes,
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

const globalStubs = {
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

const i18nMock = {
  install(app: { config: { globalProperties: Record<string, unknown> } }) {
    app.config.globalProperties.$t = (k: string) => k
  },
}

function mountSettings() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/settings', component: SettingsView }],
  })
  return router.push('/settings').then(() =>
    router.isReady().then(() =>
      mount(SettingsView, {
        global: {
          plugins: [router, i18nMock],
          stubs: globalStubs,
          mocks: { $t: (k: string) => k },
        },
      }),
    ),
  )
}

describe('SettingsView deep', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('mounts and renders settings content', async () => {
    const wrapper = await mountSettings()
    expect(wrapper.exists()).toBe(true)
    expect(wrapper.find('#view-settings').exists()).toBe(true)
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
