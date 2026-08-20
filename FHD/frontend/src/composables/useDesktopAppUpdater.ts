import { computed, onMounted, onUnmounted, ref } from 'vue'
import { isDesktopShell } from '@/utils/desktopShell'
import { normalizeReleaseMedia, type ReleaseMediaSlide } from '@/utils/releaseMedia'

export type DesktopUpdatePhase = 'idle' | 'available' | 'available-with-error' | 'downloading' | 'downloaded' | 'error'

export interface DesktopUpdateInfo {
  version?: string
  buildSha?: string
  releaseNotes?: string
  releaseName?: string
  path?: string
  releaseMedia?: ReleaseMediaSlide[]
}

export type { ReleaseMediaSlide }

interface UpdateEventPayload {
  type?: string
  data?: unknown
}

const DISMISS_KEY = 'xcagi_desktop_update_dismiss_version'

const phase = ref<DesktopUpdatePhase>('idle')
const updateInfo = ref<DesktopUpdateInfo | null>(null)
const downloadPercent = ref(0)
const errorMessage = ref('')
const modalOpen = ref(false)
const busy = ref(false)
const selfUpdateBlockReason = ref('')

let unsubscribe: (() => void) | undefined
let listeners = 0

/** @internal test helper */
export function __resetDesktopAppUpdaterForTest(): void {
  phase.value = 'idle'
  updateInfo.value = null
  downloadPercent.value = 0
  errorMessage.value = ''
  modalOpen.value = false
  busy.value = false
  selfUpdateBlockReason.value = ''
  unsubscribe?.()
  unsubscribe = undefined
  listeners = 0
}

function versionKey(info: DesktopUpdateInfo | null): string {
  if (!info) return ''
  return `${info.version || ''}@${info.buildSha || ''}`
}

function isDismissed(info: DesktopUpdateInfo | null): boolean {
  if (!info) return false
  try {
    return sessionStorage.getItem(DISMISS_KEY) === versionKey(info)
  } catch {
    return false
  }
}

function applyAvailable(data: DesktopUpdateInfo) {
  const media = normalizeReleaseMedia(data.releaseMedia)
  updateInfo.value = {
    ...data,
    ...(media.length ? { releaseMedia: media } : { releaseMedia: undefined }),
  }
  if (isDismissed(updateInfo.value)) {
    phase.value = 'idle'
    return
  }
  if (phase.value !== 'downloaded' && phase.value !== 'downloading') {
    phase.value = 'available'
  }
  errorMessage.value = ''
}

function onUpdateEvent(raw: unknown) {
  const event = (raw || {}) as UpdateEventPayload
  const type = String(event.type || '')
  const data = (event.data || {}) as DesktopUpdateInfo & {
    message?: string
    percent?: number
    transferred?: number
    total?: number
  }

  if (type === 'update-available') {
    applyAvailable(data)
    return
  }
  if (type === 'update-available-with-error') {
    applyAvailable(data)
    phase.value = 'available-with-error'
    errorMessage.value = String(
      (data as DesktopUpdateInfo & { lastError?: { message?: string } }).lastError?.message || '更新检查出错，请稍后重试',
    )
    return
  }
  if (type === 'download-progress') {
    phase.value = 'downloading'
    const percent = Number(data.percent)
    downloadPercent.value = Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : 0
    return
  }
  if (type === 'update-downloaded') {
    updateInfo.value = { ...(updateInfo.value || {}), ...data }
    phase.value = 'downloaded'
    downloadPercent.value = 100
    busy.value = false
    return
  }
  if (type === 'update-not-available') {
    if (phase.value === 'available' || phase.value === 'idle') {
      phase.value = 'idle'
      updateInfo.value = null
    }
    return
  }
  if (type === 'error') {
    phase.value = updateInfo.value ? 'available-with-error' : 'error'
    errorMessage.value = String(data.message || '更新失败')
    busy.value = false
  }
}

function ensureSubscribed() {
  if (!isDesktopShell() || !window.xcagiDesktop?.onUpdateEvent) return
  if (listeners === 0) {
    unsubscribe = window.xcagiDesktop.onUpdateEvent(onUpdateEvent)
  }
  listeners += 1
}

function releaseSubscribe() {
  listeners = Math.max(0, listeners - 1)
  if (listeners === 0) {
    unsubscribe?.()
    unsubscribe = undefined
  }
}

async function syncUpdateStatusFromHost() {
  if (!isDesktopShell()) return
  try {
    const identity = await window.xcagiDesktop?.getAppIdentity?.()
    const install = identity?.install
    if (install?.canSelfUpdate === false) {
      selfUpdateBlockReason.value = install.reason || '当前不是“应用程序”目录中的正式安装副本，请安装到 /Applications/XCAGI.app 后再更新。'
    }
  } catch {
    // Identity is advisory for the UI. The main process remains the authority.
  }
  try {
    const status = await window.xcagiDesktop?.getUpdateStatus?.()
    if (status?.type) {
      onUpdateEvent(status)
    }
  } catch {
    /* ignore */
  }
  // 刷新页面后主进程可能已检过更新但事件丢失；主动再查一次（有则发 update-available）
  try {
    await window.xcagiDesktop?.checkForUpdates?.()
  } catch {
    /* ignore */
  }
}

export function useDesktopAppUpdater() {
  onMounted(() => {
    ensureSubscribed()
    void syncUpdateStatusFromHost()
  })

  onUnmounted(() => {
    releaseSubscribe()
  })

  const badgeVisible = computed(
    () =>
      isDesktopShell() &&
      (phase.value === 'available' ||
        phase.value === 'available-with-error' ||
        phase.value === 'downloading' ||
        phase.value === 'downloaded') &&
      Boolean(updateInfo.value?.version),
  )

  const badgeLabel = computed(() => {
    const version = updateInfo.value?.version || ''
    if (phase.value === 'downloading') {
      return `下载中 ${Math.round(downloadPercent.value)}%`
    }
    if (phase.value === 'downloaded') {
      return `重启以更新 ${version}`
    }
    return version ? `可更新 ${version}` : '可更新'
  })

  const notesText = computed(() => {
    const notes = String(updateInfo.value?.releaseNotes || '').trim()
    if (notes) return notes
    const version = updateInfo.value?.version || ''
    const sha = updateInfo.value?.buildSha || ''
    return [
      version ? `版本 ${version}` : '有新版本可用',
      sha ? `构建 ${sha.slice(0, 12)}` : '',
      '',
      '• 更新桌面壳与本地后端',
      '• 业务数据与已安装 Mod 保留在本机目录',
      '• 更新完成后应用将重新加载进入新版本',
    ]
      .filter(Boolean)
      .join('\n')
  })

  const mediaSlides = computed(() => normalizeReleaseMedia(updateInfo.value?.releaseMedia))
  const isSelfUpdateSupported = computed(() => !selfUpdateBlockReason.value)

  function openModal() {
    modalOpen.value = true
  }

  function closeModal() {
    modalOpen.value = false
  }

  function dismiss() {
    const key = versionKey(updateInfo.value)
    if (key) {
      try {
        sessionStorage.setItem(DISMISS_KEY, key)
      } catch {
        /* ignore */
      }
    }
    phase.value = 'idle'
    modalOpen.value = false
  }

  async function startDownload() {
    if (selfUpdateBlockReason.value) {
      errorMessage.value = selfUpdateBlockReason.value
      return
    }
    if (!window.xcagiDesktop?.downloadUpdate) {
      errorMessage.value = '当前环境不支持下载更新'
      return
    }
    busy.value = true
    errorMessage.value = ''
    phase.value = 'downloading'
    try {
      await window.xcagiDesktop.downloadUpdate()
    } catch (e) {
      busy.value = false
      phase.value = 'available'
      errorMessage.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function installAndReload() {
    if (selfUpdateBlockReason.value) {
      errorMessage.value = selfUpdateBlockReason.value
      return
    }
    if (!window.xcagiDesktop?.installUpdate) {
      errorMessage.value = '当前环境不支持安装更新'
      return
    }
    busy.value = true
    errorMessage.value = ''
    try {
      await window.xcagiDesktop.installUpdate()
    } catch (e) {
      busy.value = false
      phase.value = 'downloaded'
      errorMessage.value = e instanceof Error ? e.message : String(e)
    }
  }

  async function primaryAction() {
    if (phase.value === 'downloaded') {
      await installAndReload()
      return
    }
    await startDownload()
  }

  return {
    phase,
    updateInfo,
    downloadPercent,
    errorMessage,
    modalOpen,
    busy,
    badgeVisible,
    badgeLabel,
    notesText,
    mediaSlides,
    selfUpdateBlockReason,
    isSelfUpdateSupported,
    openModal,
    closeModal,
    dismiss,
    primaryAction,
    startDownload,
    installAndReload,
  }
}
