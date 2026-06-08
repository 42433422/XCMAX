import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isPlatformShellModeEnabled } from '@/constants/platformShellMode'
import { isClientModeTiersUiEnabled } from '@/constants/clientModeTiers'
import { useStartupAuth } from '@/composables/useStartupAuth'
import {
  STARTUP_MOD_FETCH_CAP_MS,
  useStartupSplash,
  extractModNames,
} from '@/composables/useStartupSplash'
import { useAppProMode } from '@/composables/useAppProMode'
import { useAppShellBridge } from '@/composables/useAppShellBridge'
import { isDesktopShell } from '@/utils/desktopShell'

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
  const skipSplashByUrl =
    typeof window !== 'undefined' &&
    new URLSearchParams(window.location.search).has('nosplash')

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

  const shouldSkipSplashVisual = () =>
    isSandboxMode ||
    skipSplashByUrl ||
    isDesktopShell() ||
    isPlatformShellModeEnabled() ||
    isAdminConsoleSpa() ||
    isPublicEntryRoute()

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

    if (!shouldSkipSplashVisual()) {
      initStartupAudio(startupPublicUrl)
    }
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
      modsStore.applyLoadingStatusPreview(startupModPreview.value)
    })

    const finishSplash = () => completeStartupSplash(ensureStartupAuthenticated)
    scheduleFailsafe(finishSplash)

    void (async () => {
      if (shouldSkipSplashVisual()) return
      try {
        const authResult = await ensureStartupAuthenticated().catch(() => ({
          ok: false,
          entitledModIds: [] as string[],
        }))
        await minSplashElapsed

        await modWaitOrCap
        try {
          modsStore.applyLoadingStatusPreview(startupModPreview.value)
        } catch (e) {
          console.warn('[useAppBoot] applyLoadingStatusPreview:', e)
        }

        try {
          const { isSunbirdAccountUsername } = await import('@/constants/accountModBinding')
          await modsStore.initialize(true, {
            entitledModIds: authResult.entitledModIds,
            forceFromEntitlements:
              authResult.ok &&
              (isSunbirdAccountUsername(authResult.accountUsername) ||
                authResult.entitledModIds.length > 0),
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
