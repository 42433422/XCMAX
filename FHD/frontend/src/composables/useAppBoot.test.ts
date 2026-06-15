import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('vue-router', () => ({
  useRoute: () => ref({ name: 'chat', meta: {}, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('@/stores/mods', () => ({
  useModsStore: () => ({
    modsForUi: [{ name: 'mod-a' }],
    mods: [],
    fetchMods: vi.fn().mockResolvedValue(undefined),
    hydrateFromLocalStorage: vi.fn(),
  }),
}))

vi.mock('@/stores/workflowAiEmployees', () => ({
  useWorkflowAiEmployeesStore: () => ({
    hydrateFromMods: vi.fn(),
    reloadFromLocalStorage: vi.fn(),
  }),
}))

vi.mock('@/composables/useStartupAuth', () => ({
  useStartupAuth: () => ({
    ensureStartupAuthenticated: vi.fn().mockResolvedValue({ ok: true }),
    runEnterpriseStartupAuth: vi.fn().mockResolvedValue({ ok: true }),
  }),
}))

vi.mock('@/composables/useStartupSplash', () => ({
  STARTUP_MOD_FETCH_CAP_MS: 5000,
  extractModNames: (mods: { name: string }[]) => mods.map((m) => m.name),
  useStartupSplash: () => ({
    startupVisible: ref(false),
    appReady: ref(true),
    startupProgressPct: ref(100),
    startupModPreview: ref([]),
    startupPreviewModNames: ref([]),
    modsLoading: ref(false),
    modsLoadError: ref(''),
    dismissStartupSplashImmediate: vi.fn(),
    loadModsForStartup: vi.fn().mockResolvedValue(undefined),
    completeStartupSplash: vi.fn(),
    skipStartupSplash: vi.fn(),
    runStartupProgressLoop: vi.fn(),
    initStartupAudio: vi.fn(),
    scheduleFailsafe: vi.fn(),
    createMinSplashElapsed: vi.fn(() => () => true),
    teardownOnUnmount: vi.fn(),
    clearFailsafeTimer: vi.fn(),
  }),
}))

vi.mock('@/composables/useAppProMode', () => ({
  useAppProMode: () => ({
    isProMode: ref(false),
    handleToggleProMode: vi.fn(),
    readProModeStateFromDom: vi.fn(),
    syncGlobalProMode: vi.fn(),
    uninstallLegacyDomObserver: vi.fn(),
  }),
}))

vi.mock('@/composables/useAppShellBridge', () => ({
  useAppShellBridge: () => ({ registerShellBridge: vi.fn(), uninstall: vi.fn() }),
}))

vi.mock('@/composables/useXcmaxSync', () => ({
  useXcmaxSync: () => ({ start: vi.fn(), stop: vi.fn() }),
}))

import { useAppBoot } from './useAppBoot'

describe('useAppBoot', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('returns boot API surface', () => {
    const boot = useAppBoot()
    expect(boot.appReady).toBeDefined()
    expect(boot.startupVisible).toBeDefined()
    expect(typeof boot.skipStartupSplash).toBe('function')
  })

  it('primaryModName resolves from mods', () => {
    const boot = useAppBoot()
    expect(boot.primaryModName.value).toBe('mod-a')
  })

  it('hideChrome reflects route meta', () => {
    const boot = useAppBoot()
    expect(boot.hideChrome.value).toBe(false)
  })
})
