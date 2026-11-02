import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch, type Ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { useStartupAuth } from '@/composables/useStartupAuth'
import { startupPageReadyKey, useStartupSplash, waitForCriticalFonts } from '@/composables/useStartupSplash'
import { useAppShellBridge } from '@/composables/useAppShellBridge'
import { useXcmaxSync } from '@/composables/useXcmaxSync'
import { getAuthSessionEpoch } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
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

  async function waitForWorkspace(current: () => boolean, signal: AbortSignal) {
    const ready = () => account.workspaceReady && account.workspaceHydrationReady
    await waitUntil(() => ready() || account.sessionCheckUnavailable, signal)
    if (!current()) return false
    if (!ready() || account.sessionCheckUnavailable) {
      throw new Error('工作空间资料未就绪，请重试')
    }
    return true
  }

  function retryStartup() {
    if (publicEntry.value) { splash.dismissStartupSplashImmediate(); return }
    void splash.runStartup(async (current, stage, signal) => {
      stage('正在确认登录和工作空间…')
      const auth = await ensureStartupAuthenticated(current)
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
      await waitForCriticalFonts()
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

  watch(() => [getAuthSessionEpoch(), productReadAccountEpoch.value, publicEntry.value], () => {
    if (publicEntry.value) {
      splash.dismissStartupSplashImmediate()
      xcmaxSync.stop()
    } else {
      xcmaxSync.start()
      if (mounted) retryStartup()
    }
  }, { immediate: true, flush: 'sync' })
  watch(() => route.fullPath, () => {
    if (mounted && splash.startupVisible.value && !publicEntry.value) retryStartup()
  }, { flush: 'sync' })

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
