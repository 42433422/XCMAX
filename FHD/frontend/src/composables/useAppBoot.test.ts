import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, inject, nextTick, ref, type Ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'

const state = await vi.hoisted(async () => {
  const vue = await import('vue')
  return {
    route: vue.reactive({ name: 'chat', fullPath: '/', path: '/', meta: {} as Record<string, unknown>, query: {} }),
    authEpoch: vue.ref(0),
    accountEpoch: vue.ref(0),
    account: vue.reactive({ workspaceReady: true, workspaceHydrationReady: true, sessionCheckUnavailable: false, loaded: true }),
    mods: vue.reactive({ isLoaded: false, clientModsUiOff: false, loadError: null as string | null, initialize: vi.fn() }),
    ensureAuth: vi.fn(),
    router: { isReady: vi.fn(), replace: vi.fn(), push: vi.fn() },
    bridge: {
      installDesktopShellIntegrations: vi.fn(), installSwitchViewBridge: vi.fn(),
      installSandboxBridge: vi.fn(), bindLegacyUploadHooks: vi.fn(), uninstall: vi.fn(),
    },
    sync: { start: vi.fn(), stop: vi.fn() },
    stripModKeys: vi.fn(),
    loadFont: vi.fn(),
  }
})
vi.mock('vue-router', () => ({ useRoute: () => state.route, useRouter: () => state.router }))
vi.mock('@/stores/mods', () => ({ useModsStore: () => state.mods }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => state.account }))
vi.mock('@/stores/workflowAiEmployees', () => ({ useWorkflowAiEmployeesStore: () => ({ stripModWorkflowEmployeeKeys: state.stripModKeys }) }))
vi.mock('@/utils/authSessionCache', () => ({
  getAuthSessionEpoch: () => state.authEpoch.value,
  captureAuthSession: () => {
    const auth = state.authEpoch.value, account = state.accountEpoch.value
    return () => auth === state.authEpoch.value && account === state.accountEpoch.value
  },
}))
vi.mock('@/utils/productReadAccountScope', () => ({ productReadAccountEpoch: state.accountEpoch }))
vi.mock('@/composables/useStartupAuth', () => ({ useStartupAuth: () => ({ ensureStartupAuthenticated: state.ensureAuth }) }))
vi.mock('@/composables/useAppShellBridge', () => ({ useAppShellBridge: () => state.bridge }))
vi.mock('@/composables/useXcmaxSync', () => ({ useXcmaxSync: () => state.sync }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false }))

import { useAppBoot } from './useAppBoot'
import { STARTUP_READY_TIMEOUT_MS, startupPageReadyKey } from './useStartupSplash'

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
async function settle() {
  for (let i = 0; i < 25; i++) { await Promise.resolve(); await nextTick() }
}
let wrapper: VueWrapper | undefined
function mountBoot(viewPending?: Ref<boolean>) {
  let boot!: ReturnType<typeof useAppBoot>
  wrapper = mount(defineComponent({ setup() { boot = useAppBoot(viewPending); return () => h('div') } }))
  return boot
}
function mountBootWithPage(prepare: (signal: AbortSignal) => Promise<void>) {
  let boot!: ReturnType<typeof useAppBoot>
  let registerPage!: (prepare: (signal: AbortSignal) => Promise<void>) => () => void
  let unregisterPage!: () => void
  const Page = defineComponent({ setup() {
    const register = inject(startupPageReadyKey)
    if (!register) throw new Error('missing startup page provider')
    registerPage = register
    unregisterPage = register(prepare)
    return () => h('section')
  } })
  wrapper = mount(defineComponent({ setup() { boot = useAppBoot(); return () => h(Page) } }))
  return { boot, registerPage, unregisterPage }
}
const originalFonts = Object.getOwnPropertyDescriptor(document, 'fonts')

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  state.route.name = 'chat'; state.route.path = '/'; state.route.fullPath = '/'; state.route.meta = {}
  state.authEpoch.value = 0; state.accountEpoch.value = 0
  state.account.workspaceReady = true; state.account.sessionCheckUnavailable = false
  state.account.workspaceHydrationReady = true
  state.mods.isLoaded = false; state.mods.clientModsUiOff = false; state.mods.loadError = null
  state.ensureAuth.mockReset().mockResolvedValue({ ok: true, entitledModIds: ['owned-mod'], accountUsername: 'synthetic-user' })
  state.mods.initialize.mockReset().mockImplementation(async () => { state.mods.isLoaded = true })
  state.router.isReady.mockReset().mockResolvedValue(undefined)
  state.router.replace.mockReset().mockResolvedValue(undefined)
  state.loadFont.mockReset().mockResolvedValue([{ status: 'loaded' }])
  Object.defineProperty(document, 'fonts', { configurable: true, value: { load: state.loadFont } })
})
afterEach(() => {
  wrapper?.unmount(); wrapper = undefined
  vi.useRealTimers()
  if (originalFonts) Object.defineProperty(document, 'fonts', originalFonts)
  else Reflect.deleteProperty(document, 'fonts')
})

describe('workspace startup readiness', () => {
  it('keeps verified workspace data while waiting for the latest hydration', async () => {
    state.account.workspaceHydrationReady = false
    const boot = mountBoot()
    await settle()
    expect(state.account.workspaceReady).toBe(true)
    expect(boot.startupVisible.value).toBe(true)
    expect(boot.appReady.value).toBe(false)
    expect(state.mods.initialize).not.toHaveBeenCalled()
    state.account.workspaceHydrationReady = true
    await settle()
    expect(boot.appReady.value).toBe(true)
  })
  it('waits for authentication while keeping the view mounted underneath', async () => {
    const auth = deferred<{ ok: boolean; entitledModIds: string[] }>()
    state.ensureAuth.mockReturnValue(auth.promise)
    const boot = mountBoot()
    expect(wrapper!.exists()).toBe(true)
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupVisible.value).toBe(true)
    expect(state.mods.initialize).not.toHaveBeenCalled()
    auth.resolve({ ok: true, entitledModIds: [] })
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('waits for current workspace hydration within authenticated startup', async () => {
    const hydration = deferred()
    state.account.workspaceReady = false
    state.ensureAuth.mockImplementation(async () => {
      await hydration.promise
      state.account.workspaceReady = true
      return { ok: true, entitledModIds: [] }
    })
    const boot = mountBoot()
    await settle()
    expect(boot.appReady.value).toBe(false)
    hydration.resolve()
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('waits for a superseding profile hydration after the auth helper has returned', async () => {
    state.account.workspaceReady = false
    const boot = mountBoot()
    await settle()
    expect(state.ensureAuth).toHaveBeenCalled()
    expect(state.mods.initialize).not.toHaveBeenCalled()
    expect(boot.startupError.value).toBe('')
    state.account.workspaceReady = true
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it.each(['ready', 'unavailable'] as const)('rechecks the latest workspace after page data finishes: %s', async outcome => {
    const page = deferred()
    const prepare = vi.fn(() => page.promise)
    const { boot } = mountBootWithPage(prepare)
    await settle()
    expect(prepare).toHaveBeenCalledOnce()
    state.account.workspaceHydrationReady = false
    page.resolve()
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupVisible.value).toBe(true)
    expect(boot.startupError.value).toBe('')
    if (outcome === 'ready') state.account.workspaceHydrationReady = true
    else state.account.sessionCheckUnavailable = true
    await settle()
    expect(boot.appReady.value).toBe(outcome === 'ready')
    if (outcome === 'unavailable') expect(boot.startupError.value).toContain('工作空间资料未就绪')
    else expect(boot.startupError.value).toBe('')
  })

  it('ignores a removed page rejection and waits for its newly registered replacement', async () => {
    const oldPage = deferred(), newPage = deferred()
    const prepareOld = vi.fn(() => oldPage.promise)
    const prepareNew = vi.fn(() => newPage.promise)
    const { boot, registerPage, unregisterPage } = mountBootWithPage(prepareOld)
    await settle()
    expect(prepareOld).toHaveBeenCalledOnce()
    unregisterPage()
    registerPage(prepareNew)
    oldPage.reject(new Error('retired page data failed'))
    await settle()
    expect(prepareNew).toHaveBeenCalledOnce()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupError.value).toBe('')
    newPage.resolve()
    await settle()
    expect(boot.appReady.value).toBe(true)
    expect(boot.startupVisible.value).toBe(false)
  })

  it('keeps an error from a still-registered page actionable', async () => {
    const page = deferred()
    const prepare = vi.fn(() => page.promise)
    const { boot } = mountBootWithPage(prepare)
    await settle()
    expect(prepare).toHaveBeenCalledOnce()
    page.reject(new Error('current page data failed'))
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupVisible.value).toBe(true)
    expect(boot.startupError.value).toContain('current page data failed')
  })

  it('reports a swallowed session check failure while waiting for hydration', async () => {
    state.account.workspaceReady = false
    const boot = mountBoot()
    await settle()
    state.account.sessionCheckUnavailable = true
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupError.value).toBeTruthy()
    expect(state.mods.initialize).not.toHaveBeenCalled()
  })

  it.each(['timeout', 'cancel'] as const)('retires pending hydration on %s and ignores its late readiness', async (action) => {
    state.account.workspaceReady = false
    const boot = mountBoot()
    await settle()
    if (action === 'timeout') await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    else await boot.cancelStartup()
    expect(boot.startupError.value).toBeTruthy()
    state.account.workspaceReady = true
    await settle()
    expect(state.mods.initialize).not.toHaveBeenCalled()
    expect(boot.appReady.value).toBe(false)
  })

  it('does not let a retired hydration signal skip the new account authentication or hydration', async () => {
    state.account.workspaceReady = false
    const auth = deferred<{ ok: boolean; entitledModIds: string[] }>()
    state.ensureAuth.mockResolvedValueOnce({ ok: true, entitledModIds: ['old-mod'] }).mockReturnValueOnce(auth.promise)
    const boot = mountBoot()
    await settle()
    state.accountEpoch.value++
    await settle()
    state.account.workspaceReady = true
    await settle()
    expect(state.mods.initialize).not.toHaveBeenCalled()
    expect(boot.appReady.value).toBe(false)
    state.account.workspaceReady = false
    auth.resolve({ ok: true, entitledModIds: ['current-mod'] })
    await settle()
    expect(state.mods.initialize).not.toHaveBeenCalled()
    state.account.workspaceReady = true
    await settle()
    expect(state.mods.initialize).toHaveBeenCalledWith(true, expect.objectContaining({ entitledModIds: ['current-mod'] }))
    expect(boot.appReady.value).toBe(true)
  })

  it('waits for verified Mod initialization and preserves the auth entitlement contract', async () => {
    const mods = deferred()
    state.mods.initialize.mockImplementation(async () => { await mods.promise; state.mods.isLoaded = true })
    const boot = mountBoot()
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(state.mods.initialize).toHaveBeenCalledWith()
    mods.resolve()
    await settle()
    expect(state.mods.initialize).toHaveBeenCalledWith(true, expect.objectContaining({
      entitledModIds: ['owned-mod'], accountUsername: 'synthetic-user',
    }))
    expect(boot.appReady.value).toBe(true)
    expect(boot.startupVisible.value).toBe(false)
  })

  it('waits for the critical icon font after data is ready', async () => {
    const font = deferred<unknown[]>()
    state.loadFont.mockReturnValue(font.promise)
    const boot = mountBoot()
    await settle()
    expect(state.mods.isLoaded).toBe(true)
    expect(state.loadFont).toHaveBeenCalled()
    expect(boot.appReady.value).toBe(false)
    font.resolve([{ status: 'loaded' }])
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('keeps a resolved data and font startup protected until the current view resolves', async () => {
    const pending = ref(true)
    const boot = mountBoot(pending)
    await settle()
    expect(state.loadFont).toHaveBeenCalled()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupVisible.value).toBe(true)
    pending.value = false
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('does not release a timed out startup when its view resolves late', async () => {
    const pending = ref(true)
    const boot = mountBoot(pending)
    await settle()
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(boot.startupError.value).toBeTruthy()
    pending.value = false
    await settle()
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupError.value).toBeTruthy()
  })

  it('retires the pending-view listener on cancel and waits again on retry', async () => {
    const removeListener = vi.spyOn(AbortSignal.prototype, 'removeEventListener')
    const pending = ref(true)
    const boot = mountBoot(pending)
    try {
      await settle()
      boot.cancelStartup()
      await settle()
      expect(removeListener).toHaveBeenCalledWith('abort', expect.any(Function))
      pending.value = false
      await settle()
      expect(boot.appReady.value).toBe(false)
      pending.value = true
      boot.retryStartup()
      await settle()
      expect(boot.appReady.value).toBe(false)
      pending.value = false
      await settle()
      expect(boot.appReady.value).toBe(true)
    } finally { removeListener.mockRestore() }
  })

  it.each(['workspace', 'session', 'mods'] as const)('does not treat a swallowed %s failure as readiness', async (failure) => {
    if (failure === 'workspace') state.account.workspaceReady = false
    if (failure === 'session') state.account.sessionCheckUnavailable = true
    if (failure === 'mods') state.mods.initialize.mockResolvedValue(undefined)
    const boot = mountBoot()
    await settle()
    if (failure === 'workspace') {
      expect(boot.startupError.value).toBe('')
      await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    }
    expect(boot.appReady.value).toBe(false)
    expect(boot.startupVisible.value).toBe(true)
    expect(boot.startupError.value).toBeTruthy()
  })

  it('shows an initialization error and retries the required work', async () => {
    state.mods.initialize.mockRejectedValueOnce(new Error('synthetic backend failure'))
    const boot = mountBoot()
    await settle()
    expect(boot.startupError.value).toContain('synthetic backend failure')
    expect(boot.appReady.value).toBe(false)
    boot.retryStartup()
    await settle()
    expect(boot.startupError.value).toBe('')
    expect(boot.appReady.value).toBe(true)
  })

  it('keeps a timeout actionable when the old font request later completes', async () => {
    const font = deferred<unknown[]>()
    state.loadFont.mockReturnValue(font.promise)
    const boot = mountBoot()
    await settle()
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(boot.startupError.value).toBeTruthy()
    expect(boot.appReady.value).toBe(false)
    font.resolve([{ status: 'loaded' }])
    await settle()
    expect(boot.startupError.value).toBeTruthy()
    expect(boot.appReady.value).toBe(false)
    state.loadFont.mockResolvedValue([{ status: 'loaded' }])
    boot.retryStartup()
    await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('only releases the newest of consecutive retries', async () => {
    const first = deferred<unknown[]>(), second = deferred<unknown[]>(), latest = deferred<unknown[]>()
    state.loadFont.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise).mockReturnValueOnce(latest.promise)
    const boot = mountBoot()
    await settle()
    boot.retryStartup(); await settle()
    boot.retryStartup(); await settle()
    first.resolve([{ status: 'loaded' }]); second.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(false)
    latest.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it.each(['auth', 'account'] as const)('retires old %s scope work and waits for the new session', async (scope) => {
    const old = deferred<unknown[]>(), current = deferred<unknown[]>()
    state.loadFont.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const boot = mountBoot()
    await settle()
    if (scope === 'auth') state.authEpoch.value++
    else state.accountEpoch.value++
    expect(boot.appReady.value).toBe(false)
    await settle()
    old.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(false)
    current.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('does not use an old authenticated result after an account switch', async () => {
    const old = deferred<{ ok: boolean; entitledModIds: string[] }>()
    const current = deferred<{ ok: boolean; entitledModIds: string[] }>()
    state.ensureAuth.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const boot = mountBoot()
    await settle()
    state.accountEpoch.value++
    await settle()
    old.resolve({ ok: true, entitledModIds: ['old-mod'] })
    await settle()
    expect(state.mods.initialize).not.toHaveBeenCalled()
    expect(boot.appReady.value).toBe(false)
    current.resolve({ ok: true, entitledModIds: ['current-mod'] })
    await settle()
    expect(state.mods.initialize).toHaveBeenCalledWith(true, expect.objectContaining({ entitledModIds: ['current-mod'] }))
    expect(boot.appReady.value).toBe(true)
  })

  it('drains a previous account Mod request before accepting the new account result', async () => {
    const old = deferred(), current = deferred()
    let forced = 0
    state.mods.initialize.mockImplementation(async (force?: boolean) => {
      if (force) {
        forced++
        await (forced === 1 ? old.promise : current.promise)
      } else if (forced === 1) await old.promise
      state.mods.isLoaded = true
    })
    const boot = mountBoot()
    await settle()
    state.accountEpoch.value++
    await settle()
    old.resolve(); await settle()
    expect(forced).toBe(2)
    expect(boot.appReady.value).toBe(false)
    current.resolve(); await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('honors publicAccess metadata even with normal chrome', async () => {
    state.route.name = 'public-preview'; state.route.meta = { publicAccess: true }
    const boot = mountBoot()
    await settle()
    expect(boot.appReady.value).toBe(true)
    expect(state.ensureAuth).not.toHaveBeenCalled()
  })

  it.each(['login', 'lan-gate', 'product-onboarding'])('allows the public %s route without protected startup', async (name) => {
    state.route.name = name; state.route.meta = { hideChrome: true, publicAccess: true }
    const boot = mountBoot()
    await settle()
    expect(boot.appReady.value).toBe(true)
    expect(boot.startupVisible.value).toBe(false)
    expect(state.ensureAuth).not.toHaveBeenCalled()
    expect(state.mods.initialize).not.toHaveBeenCalled()
  })

  it('retires pending work on login and starts a fresh gate on return', async () => {
    const old = deferred<unknown[]>(), current = deferred<unknown[]>()
    state.loadFont.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const boot = mountBoot()
    await settle()
    state.route.name = 'login'; state.route.meta = { hideChrome: true }
    await settle()
    expect(boot.startupVisible.value).toBe(false)
    state.route.meta = {}; state.route.name = 'chat'
    await settle()
    old.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(false)
    current.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(true)
  })

  it('cancels protected startup without a late successful release', async () => {
    const font = deferred<unknown[]>()
    state.loadFont.mockReturnValue(font.promise)
    const boot = mountBoot()
    await settle()
    boot.cancelStartup()
    await settle()
    expect(state.router.replace).toHaveBeenCalled()
    font.resolve([{ status: 'loaded' }]); await settle()
    expect(boot.appReady.value).toBe(false)
  })

  it('installs shell integrations once and cleans up when unmounted', async () => {
    const font = deferred<unknown[]>()
    state.loadFont.mockReturnValue(font.promise)
    const boot = mountBoot()
    await settle()
    expect(state.bridge.installDesktopShellIntegrations).toHaveBeenCalledOnce()
    expect(state.bridge.installSwitchViewBridge).toHaveBeenCalledOnce()
    wrapper!.unmount(); wrapper = undefined
    font.resolve([{ status: 'loaded' }]); await settle()
    await vi.advanceTimersByTimeAsync(STARTUP_READY_TIMEOUT_MS)
    expect(boot.appReady.value).toBe(false)
    expect(state.bridge.uninstall).toHaveBeenCalledOnce()
    expect(state.sync.stop).toHaveBeenCalled()
  })
})
