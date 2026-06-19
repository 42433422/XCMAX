import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isPlatformShellModeEnabled } from '@/constants/platformShellMode'
import { isClientModeTiersUiEnabled } from '@/constants/clientModeTiers'
import { useStartupAuth, type StartupAuthResult } from '@/composables/useStartupAuth'
import {
  STARTUP_MOD_FETCH_CAP_MS,
  useStartupSplash,
  extractModNames,
} from '@/composables/useStartupSplash'
import { useAppProMode } from '@/composables/useAppProMode'
import { useAppShellBridge } from '@/composables/useAppShellBridge'
import { useXcmaxSync } from '@/composables/useXcmaxSync'

function startupPublicUrl(fileName: string) {
  const base = String(import.meta.env.BASE_URL || '/')
  return `${base}startup/${fileName}`.replace(/([^:]\/)\/+/g, '$1')
}

export function useAppBoot() {
  const route = useRoute()
  const router = useRouter()
  const modsStore = useModsStore()

  const isSandboxMode =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).has('sandbox')
  const hideChrome = computed(() => route.meta?.hideChrome === true)

  function isPublicEntryRoute(r = route) {
    const name = String(r?.name || '')
    return (
      name === 'login' ||
      name === 'lan-gate' ||
      name === 'product-onboarding' ||
      r?.meta?.hideChrome === true
    )
  }

  /** 产品决策：取消开屏加载动画，启动后直接进主界面（仍保留 Mod/鉴权初始化） */
  const shouldSkipSplashVisual = () => true

  const splash = useStartupSplash()
  const {
    startupVisible,
    appReady,
    startupProgressPct,
    startupModPreview,
    startupPreviewModNames,
    modsLoading,
    modsLoadError,
    dismissStartupSplashImmediate,
    loadModsForStartup,
    completeStartupSplash,
    skipStartupSplash,
    runStartupProgressLoop,
    initStartupAudio,
    scheduleFailsafe,
    createMinSplashElapsed,
    teardownOnUnmount,
    clearFailsafeTimer,
  } = splash

  const startupStoreModNames = computed(() => extractModNames(modsStore.modsForUi))
  const startupModNames = computed(() => {
    if (startupPreviewModNames.value.length > 0) return startupPreviewModNames.value
    return startupStoreModNames.value
  })
  const primaryModName = computed(() => startupModNames.value[0] || '')

  const proMode = useAppProMode(modsStore, router, route)
  const { isProMode, handleToggleProMode, readProModeStateFromDom, syncGlobalProMode } = proMode

  const { ensureStartupAuthenticated, runEnterpriseStartupAuth } = useStartupAuth({
    router,
    modsStore,
    dismissStartupSplashImmediate,
  })

  const shellBridge = useAppShellBridge(router, proMode)
  const xcmaxSync = useXcmaxSync()

  let onModsVisibilityRetry: (() => void) | null = null
  let onPageShowBfCache: ((e: PageTransitionEvent) => void) | null = null

  if (shouldSkipSplashVisual()) {
    dismissStartupSplashImmediate()
  }

  watch(
    () => route.name,
    () => {
      if (isPublicEntryRoute()) {
        dismissStartupSplashImmediate()
        xcmaxSync.stop()
      } else {
        xcmaxSync.start()
      }
    },
    { immediate: true }
  )

  onMounted(async () => {
    if (isPublicEntryRoute()) {
      dismissStartupSplashImmediate()
    }

    if (shouldSkipSplashVisual()) {
      dismissStartupSplashImmediate()
      void router.isReady().then(() => runEnterpriseStartupAuth(isPublicEntryRoute))
    }

    if (shouldSkipSplashVisual()) {
      void modsStore.initialize(true)
    }

    onModsVisibilityRetry = () => {
      if (document.visibilityState !== 'visible') return
      if (!modsStore.isLoaded) void modsStore.initialize()
    }
    document.addEventListener('visibilitychange', onModsVisibilityRetry)

    onPageShowBfCache = (e) => {
      if (!e.persisted) return
      if (modsStore.clientModsUiOff) return
      void modsStore.initialize(true)
    }
    window.addEventListener('pageshow', onPageShowBfCache)

    /* v8 ignore start -- shouldSkipSplashVisual 恒为 true（产品决策取消开屏动画），此分支不可达 */
    if (!shouldSkipSplashVisual()) {
      initStartupAudio(startupPublicUrl)
    }
    /* v8 ignore end */
    startupProgressPct.value = 0
    runStartupProgressLoop()

    const minSplashElapsed = createMinSplashElapsed()
    const loadStartupMods = loadModsForStartup().catch((e) => {
      console.warn('[useAppBoot] loadModsForStartup:', e)
    })
    const modWaitOrCap = Promise.race([
      loadStartupMods,
      new Promise<void>((r) => {
        window.setTimeout(r, STARTUP_MOD_FETCH_CAP_MS)
      }),
    ])

    void loadStartupMods.finally(() => {
      modsStore.applyLoadingStatusPreview(
        startupModPreview.value as Array<{ id: string; name?: string; version?: string }>
      )
    })

    const finishSplash = () => completeStartupSplash(ensureStartupAuthenticated)
    scheduleFailsafe(finishSplash)

    void (async () => {
      if (shouldSkipSplashVisual()) return
      /* v8 ignore start -- shouldSkipSplashVisual 恒为 true，return 后代码不可达 */
      try {
        const authResult: StartupAuthResult = await ensureStartupAuthenticated().catch(() => ({
          ok: false,
          entitledModIds: [] as string[],
        }))
        await minSplashElapsed

        await modWaitOrCap
        try {
          modsStore.applyLoadingStatusPreview(
            startupModPreview.value as Array<{ id: string; name?: string; version?: string }>
          )
        } catch (e) {
          console.warn('[useAppBoot] applyLoadingStatusPreview:', e)
        }

        try {
          await modsStore.initialize(true, {
            entitledModIds: authResult.entitledModIds,
            forceFromEntitlements:
              authResult.ok && authResult.entitledModIds.length > 0,
            accountUsername: authResult.accountUsername,
          })
          if (modsStore.clientModsUiOff) {
            useWorkflowAiEmployeesStore().stripModWorkflowEmployeeKeys()
          }
        } catch (e) {
          console.warn('[useAppBoot] Mod initialize（开屏）:', e)
        }
      } catch (e) {
        console.error('[useAppBoot] 开屏等待阶段异常:', e)
      } finally {
        clearFailsafeTimer()
        finishSplash()
      }
      /* v8 ignore end */
    })()

    shellBridge.installProModeBridge()
    proMode.installLegacyDomObserver()
    if (!isClientModeTiersUiEnabled()) {
      proMode.enforceClientNormalModeBaseline()
    } else {
      isProMode.value = readProModeStateFromDom()
      syncGlobalProMode()
    }

    shellBridge.installSwitchViewBridge()
    shellBridge.installSandboxBridge(isSandboxMode)
    shellBridge.bindLegacyUploadHooks(String(route.name || ''))
  })

  onBeforeUnmount(() => {
    if (onModsVisibilityRetry) {
      document.removeEventListener('visibilitychange', onModsVisibilityRetry)
      onModsVisibilityRetry = null
    }
    if (onPageShowBfCache) {
      window.removeEventListener('pageshow', onPageShowBfCache)
      onPageShowBfCache = null
    }
    proMode.uninstallLegacyDomObserver()
    shellBridge.uninstall()
    xcmaxSync.stop()
    teardownOnUnmount()
  })

  return {
    hideChrome,
    startupVisible,
    appReady,
    startupProgressPct,
    startupModNames,
    primaryModName,
    modsLoading,
    modsLoadError,
    isProMode,
    handleToggleProMode,
    startupPublicUrl,
    skipStartupSplash: () => skipStartupSplash(() => completeStartupSplash(ensureStartupAuthenticated)),
    isAdminConsoleSpa,
  }
}
