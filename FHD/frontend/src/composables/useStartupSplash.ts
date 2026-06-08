import { ref, computed } from 'vue'
import { isApiFetchTimeoutError } from '@/utils/apiBase'
import { fetchModLoadingStatusShared } from '@/utils/modLoadingStatusShared'
import { summarizeModLoadingData } from '@/utils/modLoadingStatus'
import { CLIENT_MODS_UI_OFF_KEY } from '@/stores/mods'

export const STARTUP_SPLASH_MS = 1200
export const STARTUP_MOD_FETCH_CAP_MS = 2500
export const STARTUP_FAILSAFE_MS = 6000
export const STARTUP_AUTH_TIMEOUT_MS = 8_000

export function extractModNames(list: unknown[]) {
  const rows = Array.isArray(list) ? list : []
  const names = rows
    .map((m) => {
      const row = m as { name?: string; id?: string }
      const name = String(row?.name || '').trim()
      const id = String(row?.id || '').trim()
      return name || id
    })
    .filter(Boolean)
  return Array.from(new Set(names))
}

export function useStartupSplash() {
  const startupVisible = ref(true)
  const appReady = ref(false)
  const startupProgressPct = ref(0)
  const startupModPreview = ref<unknown[]>([])
  const modsLoading = ref(false)
  const modsLoadError = ref<string | null>(null)

  let splashFinishOnce = false
  let startupProgressRaf: number | null = null
  let resolveStartupMinWait: (() => void) | null = null
  let startupMinWaitTimer: ReturnType<typeof window.setTimeout> | null = null
  let startupFailsafeTimer: ReturnType<typeof window.setTimeout> | null = null
  let startupAudio: HTMLAudioElement | null = null
  let startupAudioFallbackPlayed = false
  let startupAudioUserGestureHandler: (() => void) | null = null

  const startupPreviewModNames = computed(() => extractModNames(startupModPreview.value))

  function stopStartupProgressLoop() {
    if (startupProgressRaf != null) {
      cancelAnimationFrame(startupProgressRaf)
      startupProgressRaf = null
    }
  }

  function runStartupProgressLoop() {
    const t0 = performance.now()
    const tick = () => {
      if (!startupVisible.value) {
        stopStartupProgressLoop()
        return
      }
      const elapsed = performance.now() - t0
      const linear = Math.min(1, elapsed / STARTUP_SPLASH_MS)
      const eased = 1 - (1 - linear) ** 2
      const pct = Math.min(88, Math.round(eased * 88))
      if (pct > startupProgressPct.value) {
        startupProgressPct.value = pct
      }
      startupProgressRaf = requestAnimationFrame(tick)
    }
    startupProgressRaf = requestAnimationFrame(tick)
  }

  function finishStartupUi() {
    startupVisible.value = false
    appReady.value = true
  }

  function clearStartupTimers() {
    if (startupFailsafeTimer != null) {
      window.clearTimeout(startupFailsafeTimer)
      startupFailsafeTimer = null
    }
    if (startupMinWaitTimer) {
      window.clearTimeout(startupMinWaitTimer)
      startupMinWaitTimer = null
    }
    if (resolveStartupMinWait) {
      resolveStartupMinWait()
      resolveStartupMinWait = null
    }
  }

  function dismissStartupSplashImmediate() {
    finishStartupUi()
    stopStartupProgressLoop()
    startupProgressPct.value = 100
    if (splashFinishOnce) return
    splashFinishOnce = true
    clearStartupTimers()
  }

  async function loadModsForStartup() {
    if (typeof localStorage !== 'undefined' && localStorage.getItem(CLIENT_MODS_UI_OFF_KEY) === '1') {
      startupModPreview.value = []
      modsLoading.value = false
      return
    }
    modsLoading.value = true
    modsLoadError.value = null
    try {
      const d = await fetchModLoadingStatusShared()
      if (!d) {
        startupModPreview.value = []
        return
      }
      const raw = (d as { mods?: unknown }).mods
      startupModPreview.value = Array.isArray(raw) ? raw : []
      const hint = summarizeModLoadingData(d)
      if (hint) {
        modsLoadError.value = hint
      }
    } catch (error) {
      startupModPreview.value = []
      if (isApiFetchTimeoutError(error)) {
        console.debug(
          '[useStartupSplash] Mod loading-status 超时（后端可能仍在启动），开屏结束后将再试。',
          error
        )
      } else {
        console.warn(
          '[useStartupSplash] Mod loading-status error:',
          error instanceof Error ? error.message : error
        )
      }
    } finally {
      modsLoading.value = false
      if (startupVisible.value) {
        startupProgressPct.value = Math.max(startupProgressPct.value, 72)
      }
    }
  }

  function teardownStartupAudio() {
    startupAudioFallbackPlayed = true
    if (startupAudio) {
      startupAudio.pause()
      startupAudio.currentTime = 0
    }
    if (startupAudioUserGestureHandler) {
      document.removeEventListener('pointerdown', startupAudioUserGestureHandler)
      document.removeEventListener('keydown', startupAudioUserGestureHandler)
      startupAudioUserGestureHandler = null
    }
  }

  function completeStartupSplash(ensureStartupAuthenticated: () => Promise<unknown>) {
    const firstRun = !splashFinishOnce
    if (firstRun) {
      splashFinishOnce = true
      clearStartupTimers()
      stopStartupProgressLoop()
      startupProgressPct.value = 100
    } else {
      finishStartupUi()
      return
    }
    const authTimeout = new Promise((resolve) => {
      window.setTimeout(() => resolve({ ok: false, entitledModIds: [] }), STARTUP_AUTH_TIMEOUT_MS)
    })
    void Promise.race([ensureStartupAuthenticated(), authTimeout])
      .catch(() => ({ ok: false, entitledModIds: [] }))
      .finally(finishStartupUi)
    teardownStartupAudio()
  }

  function tryPlayStartupAudio() {
    if (!startupAudio || startupAudioFallbackPlayed) return
    startupAudio.play().catch(() => {
      /* autoplay may be blocked */
    })
  }

  function bindStartupAudioFallback() {
    startupAudioUserGestureHandler = () => {
      if (!startupAudio || startupAudioFallbackPlayed) return
      startupAudioFallbackPlayed = true
      startupAudio.play().catch(() => {
        /* ignore */
      })
      if (startupAudioUserGestureHandler) {
        document.removeEventListener('pointerdown', startupAudioUserGestureHandler)
        document.removeEventListener('keydown', startupAudioUserGestureHandler)
      }
    }
    if (startupAudioUserGestureHandler) {
      document.addEventListener('pointerdown', startupAudioUserGestureHandler, { once: true })
      document.addEventListener('keydown', startupAudioUserGestureHandler, { once: true })
    }
  }

  function initStartupAudio(startupPublicUrl: (fileName: string) => string) {
    startupAudio = new Audio(startupPublicUrl('startup-enter.mp3'))
    startupAudio.preload = 'metadata'
    startupAudio.volume = 0.9
    startupAudio.addEventListener(
      'error',
      () => {
        startupAudio = null
      },
      { once: true }
    )
    tryPlayStartupAudio()
    bindStartupAudioFallback()
  }

  function skipStartupSplash(complete: () => void) {
    if (!startupVisible.value) return
    complete()
  }

  function scheduleFailsafe(complete: () => void) {
    startupFailsafeTimer = window.setTimeout(() => {
      if (!appReady.value) {
        console.warn('[useStartupSplash] 开屏超时兜底：强制结束启动遮罩。')
        complete()
      }
    }, STARTUP_FAILSAFE_MS)
  }

  function createMinSplashElapsed() {
    return new Promise<void>((resolve) => {
      resolveStartupMinWait = () => {
        resolveStartupMinWait = null
        resolve()
      }
      startupMinWaitTimer = window.setTimeout(() => {
        startupMinWaitTimer = null
        resolveStartupMinWait = null
        resolve()
      }, STARTUP_SPLASH_MS)
    })
  }

  function teardownOnUnmount() {
    clearStartupTimers()
    stopStartupProgressLoop()
    teardownStartupAudio()
    if (startupAudio) {
      startupAudio = null
    }
  }

  return {
    startupVisible,
    appReady,
    startupProgressPct,
    startupModPreview,
    startupPreviewModNames,
    modsLoading,
    modsLoadError,
    loadModsForStartup,
    dismissStartupSplashImmediate,
    completeStartupSplash,
    skipStartupSplash,
    runStartupProgressLoop,
    initStartupAudio,
    scheduleFailsafe,
    createMinSplashElapsed,
    teardownOnUnmount,
    getFailsafeTimer: () => startupFailsafeTimer,
    clearFailsafeTimer: () => {
      if (startupFailsafeTimer != null) {
        window.clearTimeout(startupFailsafeTimer)
        startupFailsafeTimer = null
      }
    },
  }
}
