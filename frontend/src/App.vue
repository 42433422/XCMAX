<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useModsStore, CLIENT_MODS_UI_OFF_KEY } from '@/stores/mods'
import { useWorkflowAiEmployeesStore } from '@/stores/workflowAiEmployees'
import { apiFetch, isApiFetchTimeoutError } from '@/utils/apiBase'
import { summarizeModLoadingData } from '@/utils/modLoadingStatus'
import MainLayout from './components/MainLayout.vue'
import ProMode from './components/ProMode.vue'
import GlobalReadTokenPrompt from './fhd/GlobalReadTokenPrompt.vue'
import GlobalWriteTokenPrompt from './fhd/GlobalWriteTokenPrompt.vue'
import AppDialogHost from './components/AppDialogHost.vue'
import GlobalLanGateModal from './components/lan/GlobalLanGateModal.vue'

const route = useRoute()
const router = useRouter()
const modsStore = useModsStore()
const isProMode = ref(false)
const appReady = ref(false)
const startupVisible = ref(true)

/** 过长的启动遮罩会拖慢「可交互」时间；略长于 logo 文案渐显（约 1.65s）即可 */
const STARTUP_SPLASH_MS = 1800
/** 为在关屏前展示 Mod 摘要，最多额外等待 loading-status（避免后端极慢时无限停留） */
const STARTUP_MOD_FETCH_CAP_MS = 4000
/** 无论开屏逻辑是否异常，超时后强制显示主界面，避免永久 opacity:0 白屏 */
const STARTUP_FAILSAFE_MS = 12000
/** 开屏仅拉 loading-status：勿用 180s Mod 超时，后端未起时尽快结束请求并交给开屏 cap / failsafe */
const STARTUP_LOADING_STATUS_TIMEOUT_MS = 12_000

const modsLoading = ref(false)
const modsLoadError = ref(null)
/** 启动页 logo 下方：来自 /api/mods/loading-status */
const startupModPreview = ref([])

function extractModNames(list) {
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
/** 开屏进度条（主界面 opacity:0 时左下角 progress-panel 不可见，需在遮罩内单独展示） */
const startupProgressPct = ref(0)
let startupProgressRaf = null

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

/** 点击跳过时提前结束「最短开屏」等待，避免 Promise 挂死 */
let resolveStartupMinWait = null
let switchViewEvent = null
let startupRevealTimer = null
let startupFailsafeTimer = null
let startupAudio = null
let startupAudioFallbackPlayed = false
let startupAudioUserGestureHandler = null

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
      if (hint) {
        modsLoadError.value = hint
      }
    } else {
      startupModPreview.value = []
      modsLoadError.value = typeof data.error === 'string' ? data.error : 'Mod 加载失败'
    }
  } catch (error) {
    startupModPreview.value = []
    if (isApiFetchTimeoutError(error)) {
      console.debug(
        '[App] Mod loading-status 超时（后端可能仍在启动），开屏结束后将再试。',
        error
      )
    } else {
      console.warn('[App] Mod loading-status error:', error instanceof Error ? error.message : error)
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
  startupVisible.value = false
  appReady.value = true
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
  startupAudio.play().catch(() => {
    // Autoplay may be blocked; wait for first user gesture.
  })
}

const bindStartupAudioFallback = () => {
  startupAudioUserGestureHandler = () => {
    if (!startupAudio || startupAudioFallbackPlayed) return
    startupAudioFallbackPlayed = true
    startupAudio.play().catch(() => {
      // Ignore playback failure if the environment blocks audio.
    })
    document.removeEventListener('pointerdown', startupAudioUserGestureHandler)
    document.removeEventListener('keydown', startupAudioUserGestureHandler)
  }
  document.addEventListener('pointerdown', startupAudioUserGestureHandler, { once: true })
  document.addEventListener('keydown', startupAudioUserGestureHandler, { once: true })
}

const skipStartupSplash = () => {
  if (!startupVisible.value) return
  completeStartupSplash()
}

const hasLegacyProModeRuntime = () => {
  const legacyToggle = window.__legacyToggleProMode || window.toggleProMode
  return typeof legacyToggle === 'function'
}

const readProModeStateFromDom = () => {
  const overlay = document.getElementById('proModeOverlay')
  const bodyActive = document.body.classList.contains('pro-mode-active')
  const overlayActive = !!overlay?.classList.contains('active')
  const overlayVisible = !!overlay && overlay.style.display !== 'none'
  // Toggle class can lag animation/legacy lifecycle; use overlay/body as single source of truth.
  return bodyActive || (overlayActive && overlayVisible)
}

const syncProModeStateSoon = () => {
  requestAnimationFrame(() => {
    isProMode.value = readProModeStateFromDom()
  })
  setTimeout(() => {
    isProMode.value = readProModeStateFromDom()
  }, 350)
}

const handleToggleProMode = () => {
  const legacyToggle = window.__legacyToggleProMode || window.toggleProMode
  if (typeof legacyToggle === 'function') {
    legacyToggle()
    syncProModeStateSoon()
    return
  }
  isProMode.value = !isProMode.value
}

const syncGlobalProMode = () => {
  const active = !!isProMode.value
  window.__XCAGI_IS_PRO_MODE = active
  window.dispatchEvent(new CustomEvent('xcagi:pro-mode-changed', {
    detail: { isProMode: active }
  }))
}

let proModeObserver = null
let onToggleProModeEvent = null
let onModsVisibilityRetry = null
let onPageShowBfCache = null

onMounted(async () => {
  // 不等待开屏：与侧栏 mount 并行尽早拉 /api/mods*（initialize 内部有 initInFlight 去重）
  void modsStore.initialize()
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

  // 开机动画与主界面就绪不等待 Mod API（后端慢或未启动时仍可进入应用）
  // 注意：preload='metadata' 而非 'auto'，避免大文件下载阻塞首屏渲染
  startupAudio = new Audio('/startup/startup-enter.mp3')
  startupAudio.preload = 'metadata'
  startupAudio.volume = 0.9
  tryPlayStartupAudio()
  bindStartupAudioFallback()
  startupProgressPct.value = 0
  runStartupProgressLoop()

  const minSplashElapsed = new Promise((resolve) => {
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
    console.warn('[App] loadModsForStartup:', e)
  })
  const modWaitOrCap = Promise.race([
    loadStartupMods,
    new Promise((r) => {
      window.setTimeout(r, STARTUP_MOD_FETCH_CAP_MS)
    }),
  ])

  void loadStartupMods.finally(() => {
    modsStore.applyLoadingStatusPreview(startupModPreview.value)
  })

  startupFailsafeTimer = window.setTimeout(() => {
    if (!appReady.value) {
      console.warn(
        '[App] 开屏超时兜底：强制结束启动遮罩（若仍白屏请看控制台其它报错）。'
      )
      completeStartupSplash()
    }
  }, STARTUP_FAILSAFE_MS)

  void (async () => {
    try {
      await Promise.all([minSplashElapsed, modWaitOrCap])
      try {
        modsStore.applyLoadingStatusPreview(startupModPreview.value)
      } catch (e) {
        console.warn('[App] applyLoadingStatusPreview:', e)
      }
    } catch (e) {
      console.error('[App] 开屏等待阶段异常:', e)
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
      console.warn('[App] Mod initialize（开屏后）:', e)
    }
  })()

  const syncProModeFromDom = () => {
    isProMode.value = readProModeStateFromDom()
  }

  window.setProModeEnabled = (enabled) => {
    const shouldEnable = !!enabled
    const active = readProModeStateFromDom()
    if (shouldEnable === active) {
      isProMode.value = active
      return
    }
    if (hasLegacyProModeRuntime()) {
      const legacyToggle = window.__legacyToggleProMode || window.toggleProMode
      legacyToggle()
      syncProModeStateSoon()
    } else {
      isProMode.value = shouldEnable
    }
  }

  onToggleProModeEvent = () => {
    handleToggleProMode()
  }

  window.addEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)

  if (hasLegacyProModeRuntime()) {
    let scheduled = false
    const scheduleSync = () => {
      if (scheduled) return
      scheduled = true
      requestAnimationFrame(() => {
        scheduled = false
        syncProModeFromDom()
      })
    }
    proModeObserver = new MutationObserver(() => {
      scheduleSync()
    })
    proModeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] })
    const overlay = document.getElementById('proModeOverlay')
    if (overlay) {
      proModeObserver.observe(overlay, { attributes: true, attributeFilter: ['class', 'style'] })
    }
  }
  syncProModeFromDom()
  syncGlobalProMode()

  const bindOnce = (id, eventName, handler) => {
    const el = document.getElementById(id)
    if (!el) return
    if (el.getAttribute('data-xcagi-bound') === '1') return
    el.setAttribute('data-xcagi-bound', '1')
    el.addEventListener(eventName, handler)
  }

  const routeName = String(route.name || '')
  const shouldBindLegacyUploadHooks = routeName === 'chat' || routeName === ''
  if (shouldBindLegacyUploadHooks) {
    bindOnce('fileUploadEntry', 'click', () => {
      try {
        if (typeof window.openImportWindow === 'function') {
          console.log('[xcagi] click fileUploadEntry -> openImportWindow()')
          window.openImportWindow()
        } else {
          console.warn('[xcagi] openImportWindow not found on window')
        }
      } catch (err) {
        console.warn('[xcagi] fileUploadEntry click failed:', err)
      }
    })

    bindOnce('chooseFileBtn', 'click', () => {
      const fileInput = document.getElementById('fileInput')
      if (fileInput) fileInput.click()
    })
  }

  switchViewEvent = (event) => {
    const view = event.detail?.view
    if (view) {
      console.log('[App] xcagi:switch-view received, navigating to:', view)
      router.push({ name: view })
    }
  }
  window.addEventListener('xcagi:switch-view', switchViewEvent)
})

watch(isProMode, () => {
  syncGlobalProMode()
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
  if (proModeObserver) {
    proModeObserver.disconnect()
    proModeObserver = null
  }
  if (onToggleProModeEvent) {
    window.removeEventListener('xcagi:toggle-pro-mode', onToggleProModeEvent)
    onToggleProModeEvent = null
  }
  if (switchViewEvent) {
    window.removeEventListener('xcagi:switch-view', switchViewEvent)
    switchViewEvent = null
  }
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
  if (window.setProModeEnabled) {
    delete window.setProModeEnabled
  }
  if (typeof window.__XCAGI_IS_PRO_MODE !== 'undefined') {
    delete window.__XCAGI_IS_PRO_MODE
  }
})
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
  </div>

  <div class="app-shell" :class="{ 'is-ready': appReady }">
    <div class="transition-overlay" id="transitionOverlay"></div>

    <div class="preview-float-window" id="previewFloatWindow">
    <div class="preview-header">
      <h4><i class="fa fa-television" aria-hidden="true"></i> 媒体预览</h4>
      <button class="preview-close" id="previewCloseBtn" data-close-action="closePreviewWindow">&times;</button>
    </div>
    <div class="preview-content">
      <div class="preview-media" id="previewMedia">
        <div class="preview-placeholder">暂无预览内容</div>
      </div>
    </div>
  </div>

    <div class="progress-panel" id="progressPanel">
    <div class="progress-panel-header">
      <div class="progress-title">任务进度</div>
      <button class="progress-close" id="progressCloseBtn" data-close-action="hideProgress">&times;</button>
    </div>
    <div class="progress-info">
      <span class="progress-status">处理中...</span>
      <span class="progress-percent" id="progressPercent">0%</span>
    </div>
    <div class="progress-bar-wrapper">
      <div class="progress-bar-fill" id="progressBarFill" style="width: 0%;"></div>
    </div>
    <div class="progress-task" id="progressTask">正在初始化任务...</div>
  </div>

    <div class="file-upload-entry" id="fileUploadEntry">
    <span class="entry-icon" aria-hidden="true"><i class="fa fa-folder-open-o"></i></span>
    <span class="entry-text">上传文件</span>
  </div>

    <div class="import-float-window" id="importFloatWindow">
    <div class="import-header">
      <h4><i class="fa fa-folder-open-o" aria-hidden="true"></i> 导入文件</h4>
      <button class="import-close" id="importCloseBtn" data-close-action="closeImportWindow">&times;</button>
    </div>
    <div class="import-content">
      <div class="drop-zone" id="dropZone">
        <div class="drop-zone-icon" aria-hidden="true"><i class="fa fa-folder-open"></i></div>
        <div class="drop-zone-text">拖拽文件到此处或点击选择</div>
        <div class="drop-zone-hint">支持 Excel、CSV、图片等文件</div>
      </div>
      <input type="file" class="file-input" id="fileInput" multiple accept="*/*">
      <div class="import-actions">
        <button class="btn btn-primary" id="chooseFileBtn">选择文件</button>
        <button class="btn btn-success" id="openCameraBtn"><i class="fa fa-camera" aria-hidden="true"></i> 拍照识别</button>
        <button class="btn btn-secondary" id="cancelImportBtn" data-close-action="closeImportWindow">取消</button>
      </div>
      <div class="camera-panel" id="cameraPanel" style="display: none;">
        <video id="cameraVideo" autoplay playsinline></video>
        <canvas id="cameraCanvas" style="display: none;"></canvas>
        <div class="camera-buttons">
          <button class="btn btn-primary" id="capturePhotoBtn">拍照</button>
          <button class="btn btn-secondary" id="closeCameraBtn" data-close-action="closeCamera">关闭</button>
        </div>
      </div>
      <div class="import-progress" id="importProgress">
        <div class="progress-bar-container">
          <div class="progress-bar" id="progressBar"></div>
        </div>
        <div class="progress-text">
          <span id="progressText">读取中...</span>
          <span id="importProgressPercent">0%</span>
        </div>
      </div>
      <div class="import-status" id="importStatus"></div>
    </div>
  </div>

    <div class="import-float-window" id="labelsExportWindow">
    <div class="import-header">
      <h4><i class="fa fa-tag" aria-hidden="true"></i> 商标导出</h4>
      <button class="import-close" id="labelsExportCloseBtn" type="button" title="关闭">&times;</button>
    </div>
    <div class="import-content">
      <div id="labelsExportList" class="labels-export-list">
        <p class="labels-export-hint">加载中...</p>
      </div>
      <div class="import-actions" style="margin-top: 12px;">
        <button class="btn btn-secondary" id="labelsExportCloseBtn2" type="button">关闭</button>
      </div>
    </div>
  </div>

    <div class="import-float-window" id="printPanelWindow">
    <div class="import-header">
      <h4><i class="fa fa-print" aria-hidden="true"></i> 标签打印</h4>
      <button class="import-close" id="printPanelCloseBtn" type="button" title="关闭">&times;</button>
    </div>
    <div class="import-content">
      <div id="printPanelStatus" class="labels-export-hint">正在连接打印机...</div>
      <div id="printPanelProgress" class="print-panel-progress" style="display:none; margin:10px 0;"></div>
      <div id="printPanelResults" class="print-panel-results" style="margin:10px 0; max-height:240px; overflow-y:auto;"></div>
      <div class="import-actions" style="margin-top: 12px;">
        <button class="btn btn-primary" id="printPanelStartBtn" type="button">开始打印</button>
        <button class="btn btn-secondary" id="printPanelCloseBtn2" type="button">关闭</button>
      </div>
    </div>
  </div>

    <div id="labelFloatPreviews" class="label-float-previews hidden" aria-hidden="true"></div>

    <div id="labelPreviewModal" class="label-preview-modal hidden" aria-hidden="true">
    <div class="label-preview-modal-backdrop"></div>
    <div class="label-preview-modal-content">
      <img id="labelPreviewModalImg" src="" alt="标签预览" />
      <div class="label-preview-modal-actions">
        <a id="labelPreviewModalDownload" href="" download="" class="btn btn-primary">下载标签</a>
        <button type="button" class="btn btn-secondary label-preview-modal-close">关闭</button>
      </div>
    </div>
  </div>

    <ProMode v-model="isProMode" />

    <GlobalReadTokenPrompt api-base="" />
    <GlobalWriteTokenPrompt />
    <AppDialogHost />
    <GlobalLanGateModal />

    <MainLayout
      :is-pro-mode="isProMode"
      @toggle-pro-mode="handleToggleProMode"
    >
      <router-view />
    </MainLayout>
  </div>
</template>

<style>
.app-shell {
  opacity: 0;
  transition: opacity 320ms ease;
  background: #ffffff;
}

.app-shell.is-ready {
  opacity: 1;
}

.startup-splash {
  position: fixed;
  inset: 0;
  z-index: 10000;
  display: grid;
  place-items: center;
  background: #ffffff;
  opacity: 1;
  visibility: visible;
  transition: opacity 360ms ease, visibility 0s linear 360ms;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
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
  padding: 0 12px;
}

.startup-logo-wrap {
  width: min(420px, 72vw);
  aspect-ratio: 1 / 1;
  position: relative;
}

.startup-logo-wrap img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: contain;
  user-select: none;
  -webkit-user-drag: none;
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
  }
  to {
    opacity: 1;
  }
}

.startup-mod-title {
  font-size: 24px;
  font-weight: 700;
  color: #262626;
  text-align: center;
  margin-top: 16px;
  animation: fadeIn 800ms ease 600ms forwards;
  opacity: 0;
}

.startup-progress-wrap {
  width: 100%;
  max-width: min(420px, 92vw);
  margin-top: 8px;
  animation: fadeIn 500ms ease 200ms forwards;
  opacity: 0;
}

.startup-progress-track {
  height: 4px;
  border-radius: 999px;
  background: rgba(0, 0, 0, 0.08);
  overflow: hidden;
}

.startup-progress-fill {
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, #1890ff 0%, #69c0ff 100%);
  transition: width 120ms ease-out;
}

.startup-mod-chips-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-width: min(420px, 92vw);
}

.startup-mod-chips-hint {
  font-size: 12px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #8c8c8c;
}

.startup-mod-chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.startup-mod-chip {
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  color: #262626;
  background: linear-gradient(180deg, #f5f5f5 0%, #ebebeb 100%);
  border: 1px solid #d9d9d9;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.startup-mod-status {
  text-align: center;
  font-size: 14px;
  color: #666;
  min-height: 28px;
}

.mod-loading,
.mod-loaded,
.mod-error {
  display: flex;
  align-items: center;
  gap: 8px;
  animation: fadeIn 300ms ease;
}

.mod-loading i {
  color: #1890ff;
}

.mod-loaded i {
  color: #52c41a;
}

.mod-error i {
  color: #ff4d4f;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>
