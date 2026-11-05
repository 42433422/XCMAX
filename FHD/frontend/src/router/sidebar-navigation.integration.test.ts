import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import App from '@/App.vue'
import router from '@/router'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useIndustryStore } from '@/stores/industry'
import { useModsStore } from '@/stores/mods'
import { resetSidebarNavigationForTests } from '@/utils/sidebarNavigation'

vi.mock('@/views/ChatView.vue', () => ({ default: { template: '<section data-page="chat">Chat page</section>' } }))
vi.mock('@/views/SettingsView.vue', () => ({ default: { template: '<section data-page="settings">Settings page</section>' } }))
vi.mock('@/utils/productSku', () => ({ fetchProductSku: vi.fn().mockResolvedValue('generic'), isEnterpriseEdition: () => false }))
vi.mock('@/composables/useProductFlow', () => ({ shouldRouteToProductOnboarding: () => false }))
vi.mock('@/utils/hostPackOnboardingGate', () => ({ resolveHostPackOnboardingStep: vi.fn().mockResolvedValue(null), shouldRouteToHostPackOnboarding: () => false }))
vi.mock('@/utils/plannerPagePaths', async (importOriginal) => ({ ...await importOriginal<typeof import('@/utils/plannerPagePaths')>(), resolvePlannerChatHomePath: () => '/', resolvePlannerPagePath: (path: string) => path }))
vi.mock('@/utils/desktopShell', async (importOriginal) => ({ ...await importOriginal<typeof import('@/utils/desktopShell')>(), isDesktopShell: () => true }))
vi.mock('@/composables/useAppBoot', () => ({ useAppBoot: () => ({ hideChrome: false, appReady: ref(true), startupVisible: ref(false), startupError: ref(''), startupStage: ref(''), retryStartup: vi.fn(), cancelStartup: vi.fn(), isAdminConsoleSpa: () => false }) }))
vi.mock('@/composables/usePrivateDeliverySync', () => ({ usePrivateDeliverySync: () => undefined }))

let wrapper: VueWrapper | undefined

beforeEach(async () => {
  resetSidebarNavigationForTests()
  localStorage.clear()
  sessionStorage.clear()
  const pinia = createPinia()
  setActivePinia(pinia)
  const account = useAccountProfileStore()
  account.loaded = true
  vi.spyOn(useIndustryStore(), 'initialize').mockResolvedValue()
  useModsStore().isLoaded = true
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ status: 'healthy', version: '1.0.0' }) }))
  await router.replace('/')
  await router.isReady()
  wrapper = mount(App, {
    attachTo: document.body,
    global: {
      plugins: [pinia, router],
      stubs: {
        LegacyFloatPanels: true, AppGlobalProviders: true, VirtualCursorOverlay: true,
        FloatingChatAssistant: true, DocumentPreviewPictureInPicture: true, TopAssistantFloat: true,
        TopQuickNav: true, GlobalTaskCenter: true, VirtualCursor: true, OnboardingTutorial: true,
        TutorialOverlay: true, TutorialTrainingCoach: true, MobileBottomNav: true, DesktopAppUpdatePrompt: true,
      },
    },
  })
  await flushPromises()
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  resetSidebarNavigationForTests()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

function assertLocation(key: 'chat' | 'settings') {
  const path = key === 'chat' ? '/' : '/settings'
  expect(router.currentRoute.value.fullPath).toBe(path)
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(path)
  expect(wrapper!.get('.route-content [data-page]').attributes('data-page')).toBe(key)
  const selected = wrapper!.findAll('.sidebar button[aria-current="page"]')
  expect(selected).toHaveLength(1)
  expect(selected[0].attributes('data-view')).toBe(key)
}

describe('sidebar navigation integration with the application router', () => {
  it('keeps the URL, rendered page and sidebar aligned through 100 switches and history navigation', async () => {
    assertLocation('chat')
    let now = Date.now()
    vi.spyOn(Date, 'now').mockImplementation(() => now)
    for (let i = 0; i < 100; i++) {
      const key = i % 2 === 0 ? 'settings' : 'chat'
      now += 100
      await wrapper!.get(`.sidebar button[data-view="${key}"]`).trigger('click')
      await vi.waitFor(() => assertLocation(key))
    }
    router.back()
    await vi.waitFor(() => assertLocation('settings'))
    router.back()
    await vi.waitFor(() => assertLocation('chat'))
    router.forward()
    await vi.waitFor(() => assertLocation('settings'))
    router.forward()
    await vi.waitFor(() => assertLocation('chat'))
  })
})
