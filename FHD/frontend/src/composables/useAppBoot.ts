import { computed, nextTick, onBeforeUnmount, onMounted, provide, readonly, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { useStartupAuth } from '@/composables/useStartupAuth'
import { startupReadyKey, startupPageReadyKey, useStartupSplash, waitForCriticalFonts } from '@/composables/useStartupSplash'
import { useAppShellBridge } from '@/composables/useAppShellBridge'
import { useXcmaxSync } from '@/composables/useXcmaxSync'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { buildLoginLocation } from '@/utils/startupRedirect'

export function useAppBoot(viewPending: Ref<boolean> = ref(false)) {
  const route = useRoute()
  const router = useRouter()
  const modsStore = useModsStore()
  const account = useAccountProfileStore()
  const hideChrome = computed(() => route.meta?.hideChrome === true)
  const publicEntry = computed(() => route.meta?.publicAccess === true || hideChrome.value ||
    ['login', 'lan-gate', 'product-onboarding'].includes(String(route.name || '')))
  const splash = useStartupSplash()
  provide(startupReadyKey, readonly(splash.appReady))
  const pagePreparations = new Set<(signal: AbortSignal) => Promise<void>>()
  provide(startupPageReadyKey, prepare => {
    const owner = String(route.name || route.path)
    const prepareCurrentPage = (signal: AbortSignal) => owner === String(route.name || route.path)
      ? prepare(signal) : Promise.resolve()
    pagePreparations.add(prepareCurrentPage)
    return () => pagePreparations.delete(prepareCurrentPage)
  })
  // The existing auth helper owns login redirection. Release the mask only after that route is active.
  const { ensureStartupAuthenticated } = useStartupAuth({
    router, modsStore, dismissStartupSplashImmediate: () => {},
  })
  const shellBridge = useAppShellBridge(router)
  const xcmaxSync = useXcmaxSync()
  let mounted = false

  async function waitUntil(ready: () => boolean, signal: AbortSignal) {
    await nextTick()
    if (ready() || signal.aborted) return
    await new Promise<void>(resolve => {
      const finish = () => { stop(); signal.removeEventListener('abort', finish); resolve() }
      const stop = watch(ready, done => { if (done) finish() }, { flush: 'post' })
      signal.addEventListener('abort', finish, { once: true })
    })
  }

  function pause(ms: number, signal: AbortSignal): Promise<void> {
    if (ms <= 0 || signal.aborted) return Promise.resolve()
    return new Promise(resolve => {
      const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve() }
      const timer = setTimeout(finish, ms)
      signal.addEventListener('abort', finish, { once: true })
    })
  }

  async function waitForWorkspace(current: () => boolean, signal: AbortSignal) {
    // A failed session probe is not a hydrated workspace. Retry the profile
    // read; if it stays unreachable, say so — never the workspace-not-ready text.
    const ready = () => account.workspaceReady && account.workspaceHydrationReady
    let retries = 0
    while (current() && !signal.aborted) {
      if (ready()) return true
      if (!account.sessionCheckUnavailable) {
        await waitUntil(() => ready() || account.sessionCheckUnavailable, signal)
        if (!current() || signal.aborted) return false
        continue
      }
      await pause(Math.min(400 * 2 ** retries++, 30_000), signal)
      if (!current() || signal.aborted) return false
      try { await account.refreshFromServer() } catch { /* the store records the outage */ }
    }
    return false
  }

  async function authenticate(current: () => boolean, signal: AbortSignal) {
    let attempt = 0
    while (current() && !signal.aborted) {
      const auth = await ensureStartupAuthenticated(current)
      if (!auth.unavailable || !current() || signal.aborted) return auth
      await pause(Math.min(500 * 2 ** attempt++, 30_000), signal)
      if (!current() || signal.aborted) return auth
    }
    return { ok: false, entitledModIds: [], unavailable: true }
  }

  function retryStartup() {
    if (publicEntry.value) { splash.dismissStartupSplashImmediate(); return }
    void splash.runStartup(async (current, stage, signal) => {
      stage('正在确认登录和工作空间…')
      let fontError: unknown
      const fontsReady = waitForCriticalFonts().catch(error => { fontError = error })
      const auth = await authenticate(current, signal)
      if (!current()) return
      if (!auth.ok) throw new Error('登录未确认，请返回登录后重试')
      // Another mount-time profile refresh can supersede the helper's request.
      // Its early return does not mean the current workspace has finished hydrating.
      if (!await waitForWorkspace(current, signal)) return
      stage('正在准备侧栏…')
      // Drain any mount-time initialization before requesting this account's own result.
      // A shared request from an earlier account must not satisfy a new startup attempt.
      await modsStore.initialize()
      if (!current()) return
      await modsStore.initialize(true, {
        entitledModIds: auth.entitledModIds,
        forceFromEntitlements: auth.entitledModIds.length > 0,
        accountUsername: auth.accountUsername,
      })
      if (!current()) return
      if (!modsStore.isLoaded) throw new Error(modsStore.loadError || '侧栏配置未就绪，请重试')
      if (modsStore.clientModsUiOff) useWorkflowAiEmployeesStore().stripModWorkflowEmployeeKeys()
      stage('正在准备图标和页面…')
      await fontsReady
      if (fontError) throw fontError
      // Keep the route mounted while blocked: its onMounted hooks must be able to finish.
      await waitUntil(() => !viewPending.value, signal)
      stage('正在读取当前页面…')
      for (const prepare of pagePreparations) {
        if (!current()) return
        try { await prepare(signal) }
        catch (error) { if (pagePreparations.has(prepare)) throw error }
      }
      if (!await waitForWorkspace(current, signal)) return
      await nextTick()
    })
  }

  async function cancelStartup() {
    splash.cancelStartup()
    const target = buildLoginLocation(window.location, import.meta.env.BASE_URL)
    try {
      await router.replace({ ...target, query: { ...target.query, error: '工作台准备已取消，请重新登录' } })
    } catch {
      // Keep recovery visible when navigation itself fails.
    }
  }

  // Scope-generation bumps and in-splash route changes must not restart this gate.
  // Those restarts kept the overlay up while chat assets loaded, then a slow
  // hydration was treated as logout. A real login/logout still changes the auth epoch.
  watch(() => [getAuthSessionEpoch(), publicEntry.value], () => {
    if (publicEntry.value) {
      splash.dismissStartupSplashImmediate()
      xcmaxSync.stop()
    } else {
      xcmaxSync.start()
      if (mounted) retryStartup()
    }
  }, { immediate: true, flush: 'sync' })

  watch(splash.appReady, ready => {
    const root = document.getElementById('app')
    if (root) root.dataset.startupReady = String(ready)
    if (ready) {
      performance.mark?.('workspace_ready')
      window.dispatchEvent(new Event('xcagi:startup-ready'))
    }
  }, { flush: 'post' })

  const onVisibility = () => {
    if (document.visibilityState === 'visible' && splash.appReady.value && !publicEntry.value && !modsStore.isLoaded) {
      void modsStore.initialize()
    }
  }
  const onPageShow = (event: PageTransitionEvent) => {
    if (event.persisted && !publicEntry.value) retryStartup()
  }

  onMounted(() => {
    mounted = true
    retryStartup()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pageshow', onPageShow)
    shellBridge.installDesktopShellIntegrations()
    shellBridge.installSwitchViewBridge()
    shellBridge.installSandboxBridge(new URLSearchParams(window.location.search).has('sandbox'))
    shellBridge.bindLegacyUploadHooks(String(route.name || ''))
  })

  onBeforeUnmount(() => {
    mounted = false
    document.removeEventListener('visibilitychange', onVisibility)
    window.removeEventListener('pageshow', onPageShow)
    shellBridge.uninstall()
    xcmaxSync.stop()
    splash.teardownOnUnmount()
  })

  return { hideChrome, ...splash, retryStartup, cancelStartup, isAdminConsoleSpa }
}
