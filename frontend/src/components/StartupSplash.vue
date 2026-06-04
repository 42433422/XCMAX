<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore, CLIENT_MODS_UI_OFF_KEY } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { useAppAuth } from '@/composables/useAppAuth'
import { apiFetch, isApiFetchTimeoutError } from '@/utils/apiBase'
import { summarizeModLoadingData } from '@/utils/modLoadingStatus'

const route = useRoute()
const router = useRouter()
const modsStore = useModsStore()
const { ensureAuthenticated } = useAppAuth()

const emit = defineEmits<{ shellReady: [] }>()

const startupVisible = ref(true)
const appReady = ref(false)
const modsLoading = ref(false)
const modsLoadError = ref<string | null>(null)
const startupModPreview = ref<any[]>([])
const startupProgressPct = ref(0)

const isSandboxMode = new URLSearchParams(window.location.search).has('sandbox')

if (isSandboxMode) {
  startupVisible.value = false
  appReady.value = true
}

const STARTUP_SPLASH_MS = 1800
const STARTUP_MOD_FETCH_CAP_MS = 4000
const STARTUP_FAILSAFE_MS = 12000
const STARTUP_LOADING_STATUS_TIMEOUT_MS = 12_000

function extractModNames(list: any[]) {
  const rows = Array.isArray(list) ? list : []
  const names = rows
    .map((m) => {
      const name = String(m?.name || '').trim()
      const id = String(m?.id || '').trim()
      return name || id
    })
    .filter(Boolean)
  return Array.from(new Set(names))
}

const startupPreviewModNames = computed(() => extractModNames(startupModPreview.value))
const startupStoreModNames = computed(() => extractModNames(modsStore.modsForUi))
const startupModNames = computed(() => {
  if (startupPreviewModNames.value.length > 0) return startupPreviewModNames.value
  return startupStoreModNames.value
})
const primaryModName = computed(() => startupModNames.value[0] || '')

let splashFinishOnce = false
let startupProgressRaf: number | null = null
let resolveStartupMinWait: (() => void) | null = null
let startupRevealTimer: number | null = null
let startupFailsafeTimer: number | null = null
let startupAudio: HTMLAudioElement | null = null
let startupAudioFallbackPlayed = false
let startupAudioUserGestureHandler: (() => void) | null = null

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

const loadModsForStartup = async () => {
  if (typeof localStorage !== 'undefined' && localStorage.getItem(CLIENT_MODS_UI_OFF_KEY) === '1') {
    startupModPreview.value = []
    modsLoading.value = false
    return
  }
  modsLoading.value = true
  modsLoadError.value = null
  try {
    const response = await apiFetch('/api/mods/loading-status', {
      timeoutMs: STARTUP_LOADING_STATUS_TIMEOUT_MS,
    })
    if (!response.ok) {
      startupModPreview.value = []
      return
    }
    const data = await response.json()
    if (data.success) {
      const d = data.data || {}
      const raw = d.mods
      startupModPreview.value = Array.isArray(raw) ? raw : []
      const hint = summarizeModLoadingData(d)
      if (hint) modsLoadError.value = hint
    } else {
      startupModPreview.value = []
      modsLoadError.value = typeof data.error === 'string' ? data.error : 'Mod 加载失败'
    }
  } catch (error) {
    startupModPreview.value = []
    if (isApiFetchTimeoutError(error)) {
      console.debug('[StartupSplash] Mod loading-status 超时', error)
    } else {
      console.warn('[StartupSplash] Mod loading-status error:', error instanceof Error ? error.message : error)
    }
  } finally {
    modsLoading.value = false
    if (startupVisible.value) {
      startupProgressPct.value = Math.max(startupProgressPct.value, 72)
    }
  }
}

function completeStartupSplash() {
  if (splashFinishOnce) return
  splashFinishOnce = true
  if (startupFailsafeTimer != null) {
    window.clearTimeout(startupFailsafeTimer)
    startupFailsafeTimer = null
  }
  stopStartupProgressLoop()
  startupProgressPct.value = 100
  if (startupRevealTimer) {
    window.clearTimeout(startupRevealTimer)
    startupRevealTimer = null
  }
  if (resolveStartupMinWait) {
    resolveStartupMinWait()
    resolveStartupMinWait = null
  }
  void ensureAuthenticated()
    .catch(() => false)
    .finally(() => {
      startupVisible.value = false
      appReady.value = true
      emit('shellReady')
    })
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

const tryPlayStartupAudio = () => {
  if (!startupAudio || startupAudioFallbackPlayed) return
  startupAudio.play().catch(() => {})
}

const bindStartupAudioFallback = () => {
  startupAudioUserGestureHandler = () => {
    if (!startupAudio || startupAudioFallbackPlayed) return
    startupAudioFallbackPlayed = true
    startupAudio.play().catch(() => {})
    document.removeEventListener('pointerdown', startupAudioUserGestureHandler!)
    document.removeEventListener('keydown', startupAudioUserGestureHandler!)
  }
  document.addEventListener('pointerdown', startupAudioUserGestureHandler, { once: true })
  document.addEventListener('keydown', startupAudioUserGestureHandler, { once: true })
}

const skipStartupSplash = () => {
  if (!startupVisible.value) return
  completeStartupSplash()
}

onMounted(async () => {
  void modsStore.initialize()

  startupAudio = new Audio('/startup/startup-enter.mp3')
  startupAudio.preload = 'metadata'
  startupAudio.volume = 0.9
  tryPlayStartupAudio()
  bindStartupAudioFallback()
  startupProgressPct.value = 0
  runStartupProgressLoop()

  const minSplashElapsed = new Promise<void>((resolve) => {
    resolveStartupMinWait = () => {
      resolveStartupMinWait = null
      resolve()
    }
    startupRevealTimer = window.setTimeout(() => {
      startupRevealTimer = null
      resolveStartupMinWait = null
      resolve()
    }, STARTUP_SPLASH_MS)
  })

  const loadStartupMods = loadModsForStartup().catch((e) => {
    console.warn('[StartupSplash] loadModsForStartup:', e)
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

  startupFailsafeTimer = window.setTimeout(() => {
    if (!appReady.value) {
      console.warn('[StartupSplash] 开屏超时兜底：强制结束启动遮罩')
      completeStartupSplash()
    }
  }, STARTUP_FAILSAFE_MS)

  void (async () => {
    try {
      await Promise.all([minSplashElapsed, modWaitOrCap])
      try {
        modsStore.applyLoadingStatusPreview(startupModPreview.value)
      } catch (e) {
        console.warn('[StartupSplash] applyLoadingStatusPreview:', e)
      }
    } catch (e) {
      console.error('[StartupSplash] 开屏等待阶段异常:', e)
    } finally {
      if (startupFailsafeTimer != null) {
        window.clearTimeout(startupFailsafeTimer)
        startupFailsafeTimer = null
      }
      completeStartupSplash()
    }
    try {
      await modsStore.initialize()
      if (modsStore.clientModsUiOff) {
        useWorkflowAiEmployeesStore().stripModWorkflowEmployeeKeys()
      }
    } catch (e) {
      console.warn('[StartupSplash] Mod initialize（开屏后）:', e)
    }
  })()
})

onBeforeUnmount(() => {
  if (startupRevealTimer) {
    window.clearTimeout(startupRevealTimer)
    startupRevealTimer = null
  }
  if (startupFailsafeTimer != null) {
    window.clearTimeout(startupFailsafeTimer)
    startupFailsafeTimer = null
  }
  stopStartupProgressLoop()
  if (startupAudioUserGestureHandler) {
    document.removeEventListener('pointerdown', startupAudioUserGestureHandler)
    document.removeEventListener('keydown', startupAudioUserGestureHandler)
    startupAudioUserGestureHandler = null
  }
  if (startupAudio) {
    startupAudio.pause()
    startupAudio.currentTime = 0
    startupAudio = null
  }
})

defineExpose({ startupVisible, appReady, skipStartupSplash })
</script>

<template>
  <div
    class="startup-splash"
    :class="{ hide: !startupVisible }"
    aria-label="初始化动画，点击跳过"
    title="点击屏幕快速进入"
    @pointerdown.stop="skipStartupSplash"
  >
    <div class="startup-splash-inner">
      <div class="startup-logo-wrap">
        <img class="startup-logo-base" src="/startup/xc-logo-base.jpg" alt="XC logo" />
        <img class="startup-logo-text" src="/startup/xc-logo-text.jpg" alt="XC logo with text" />
      </div>
      <div v-if="primaryModName" class="startup-mod-title">
        {{ primaryModName }}
      </div>
      <div v-if="startupVisible" class="startup-mod-chips-wrap">
        <template v-if="startupModNames.length > 1">
          <div class="startup-mod-chips-hint">已加载扩展包</div>
          <div class="startup-mod-chips">
            <span
              v-for="modName in startupModNames"
              :key="modName"
              class="startup-mod-chip"
            >
              {{ modName }}
            </span>
          </div>
        </template>
        <div v-else class="startup-mod-status">
          <div v-if="primaryModName" class="mod-loaded">
            <i class="fa fa-check-circle" aria-hidden="true"></i>
            <span>当前扩展包：{{ primaryModName }}</span>
          </div>
          <div v-else-if="modsLoading" class="mod-loading">
            <i class="fa fa-spinner fa-spin" aria-hidden="true"></i>
            <span>正在加载扩展包...</span>
          </div>
          <div v-else-if="modsLoadError" class="mod-error">
            <i class="fa fa-exclamation-circle" aria-hidden="true"></i>
            <span>扩展包加载异常</span>
          </div>
          <div v-else class="mod-loading">
            <i class="fa fa-circle-o-notch fa-spin" aria-hidden="true"></i>
            <span>正在初始化...</span>
          </div>
        </div>
      </div>
      <div v-if="startupVisible" class="startup-progress-wrap" aria-hidden="true">
        <div class="startup-progress-track">
          <div
            class="startup-progress-fill"
            :style="{ width: `${startupProgressPct}%` }"
          ></div>
        </div>
      </div>
    </div>
    <div class="startup-version" aria-label="当前版本">v7.0.0</div>
  </div>
</template>

<style>
.startup-splash {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  background:
    radial-gradient(circle at 28% 20%, rgba(255, 255, 255, 0.9), transparent 30%),
    linear-gradient(135deg, #edf5fb 0%, #e7eef6 48%, #eef3f8 100%);
  opacity: 1;
  visibility: visible;
  transition: opacity 360ms ease, visibility 0s linear 360ms;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
  overflow: hidden;
}

.startup-splash::before,
.startup-splash::after {
  content: "";
  position: absolute;
  pointer-events: none;
  display: none;
}

.startup-splash::before {
  width: min(760px, 74vw);
  aspect-ratio: 1;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(24, 144, 255, 0.13) 0%, rgba(34, 211, 238, 0.08) 34%, transparent 68%);
  filter: blur(10px);
  animation: startupAuraPulse 3600ms ease-in-out infinite;
}

.startup-splash::after {
  inset: 0;
  background:
    linear-gradient(115deg, transparent 0%, rgba(255, 255, 255, 0.26) 42%, transparent 58%),
    radial-gradient(circle at 70% 72%, rgba(34, 211, 238, 0.09), transparent 24%);
  transform: translateX(-18%);
  animation: startupBackdropSheen 5200ms ease-in-out infinite;
}

.startup-splash.hide {
  opacity: 0;
  visibility: hidden;
  pointer-events: none;
}

.startup-splash-inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  max-width: min(480px, 92vw);
  padding: 0 var(--app-space-md);
  position: relative;
  z-index: 1;
  animation: startupContentEnter 520ms cubic-bezier(0.2, 0.8, 0.2, 1) both;
}

.startup-version {
  position: absolute;
  left: 24px;
  bottom: 20px;
  z-index: 1;
  padding: 7px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(23, 32, 51, 0.56);
  background: rgba(255, 255, 255, 0.46);
  border: 1px solid rgba(255, 255, 255, 0.64);
  box-shadow:
    0 8px 20px rgba(15, 76, 129, 0.07),
    inset 0 1px 0 rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(12px);
  pointer-events: none;
  user-select: none;
  -webkit-user-select: none;
}

.startup-logo-wrap {
  width: min(380px, 68vw);
  aspect-ratio: 1 / 1;
  position: relative;
  display: grid;
  place-items: center;
  border-radius: 28px;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.9) 0%, rgba(248, 251, 255, 0.76) 100%);
  border: 1px solid rgba(255, 255, 255, 0.78);
  box-shadow:
    0 20px 50px rgba(15, 76, 129, 0.12),
    0 8px 18px rgba(15, 76, 129, 0.06),
    inset 0 1px 0 rgba(255, 255, 255, 0.95);
  overflow: hidden;
  animation: none;
}

.startup-logo-wrap::before,
.startup-logo-wrap::after {
  content: "";
  position: absolute;
  pointer-events: none;
  display: none;
}

.startup-logo-wrap::before {
  inset: 10%;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(34, 211, 238, 0.22) 0%, rgba(24, 144, 255, 0.1) 42%, transparent 70%);
  filter: blur(8px);
}

.startup-logo-wrap::after {
  inset: -35%;
  background: linear-gradient(115deg, transparent 34%, rgba(255, 255, 255, 0.58) 48%, transparent 62%);
  transform: translateX(-42%) rotate(8deg);
  animation: startupLogoSheen 2200ms ease-out 260ms both;
}

.startup-logo-wrap img {
  position: absolute;
  inset: 8%;
  width: 84%;
  height: 84%;
  object-fit: contain;
  user-select: none;
  -webkit-user-drag: none;
  z-index: 1;
}

.startup-logo-base {
  opacity: 1;
}

.startup-logo-text {
  opacity: 0;
  animation: startupTextFadeIn 1200ms ease 450ms forwards;
}

@keyframes startupTextFadeIn {
  from {
    opacity: 0;
    transform: translateY(6px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.startup-mod-title {
  font-size: 24px;
  font-weight: 700;
  color: #172033;
  text-align: center;
  margin-top: 10px;
  letter-spacing: -0.02em;
  animation: startupSoftEnter 800ms ease 600ms forwards;
  opacity: 0;
}

.startup-progress-wrap {
  width: 100%;
  max-width: min(420px, 84vw);
  margin-top: 10px;
  animation: startupSoftEnter 500ms ease 200ms forwards;
  opacity: 0;
}

.startup-progress-track {
  height: 5px;
  border-radius: 999px;
  background: rgba(15, 76, 129, 0.1);
  overflow: hidden;
  box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
}

.startup-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #0b63ce 0%, #12bde6 62%, #62d9ff 100%);
  transition: width 120ms ease-out;
  animation: none;
  box-shadow: none;
}

.startup-mod-chips-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: min(420px, 92vw);
  animation: startupSoftEnter 600ms ease 420ms both;
}

.startup-mod-chips-hint {
  font-size: var(--app-font-size-caption);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: rgba(23, 32, 51, 0.55);
}

.startup-mod-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.startup-mod-chip {
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: 999px;
  font-size: 13px;
  color: #172033;
  background: rgba(255, 255, 255, 0.68);
  border: 1px solid rgba(255, 255, 255, 0.78);
  box-shadow:
    0 8px 20px rgba(15, 76, 129, 0.09),
    inset 0 1px 0 rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.startup-mod-status {
  text-align: center;
  font-size: var(--app-font-size-body);
  color: rgba(23, 32, 51, 0.66);
  min-height: 28px;
}

.mod-loading,
.mod-loaded,
.mod-error {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.54);
  border: 1px solid rgba(255, 255, 255, 0.72);
  box-shadow: 0 8px 20px rgba(15, 76, 129, 0.07);
  backdrop-filter: blur(12px);
  animation: fadeIn 300ms ease;
}

.mod-loading i {
  color: var(--app-accent, #1890ff);
}

.mod-loaded i {
  color: #36b35f;
}

.mod-error i {
  color: #ff4d4f;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes startupContentEnter {
  from {
    opacity: 0;
    transform: translateY(14px) scale(0.985);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes startupSoftEnter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes startupLogoSheen {
  from { transform: translateX(-42%) rotate(8deg); }
  to { transform: translateX(42%) rotate(8deg); }
}

@keyframes startupAuraPulse {
  0%, 100% {
    opacity: 0.72;
    transform: scale(0.96);
  }
  50% {
    opacity: 1;
    transform: scale(1.04);
  }
}

@keyframes startupBackdropSheen {
  0%, 100% {
    opacity: 0.52;
    transform: translateX(-18%);
  }
  50% {
    opacity: 0.85;
    transform: translateX(8%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .startup-splash {
    transition-duration: 1ms;
  }

  .startup-splash::before,
  .startup-splash::after,
  .startup-logo-wrap,
  .startup-logo-wrap::after,
  .startup-logo-text,
  .startup-mod-title,
  .startup-progress-wrap,
  .startup-progress-fill,
  .startup-mod-chips-wrap,
  .mod-loading,
  .mod-loaded,
  .mod-error {
    animation: none;
  }

  .startup-logo-text,
  .startup-mod-title,
  .startup-progress-wrap {
    opacity: 1;
    transform: none;
  }
}
</style>
