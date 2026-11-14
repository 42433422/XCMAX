import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('xcagiDesktop', {
  platform: process.platform,
  versions: process.versions,
  getDataDir: () => ipcRenderer.invoke('xcagi:get-data-dir'),
  getAppIdentity: () => ipcRenderer.invoke('xcagi:get-app-identity'),
  consumeBootstrapSessionHint: () => ipcRenderer.invoke('xcagi:consume-bootstrap-session-hint'),
  exportSupportBundle: () => ipcRenderer.invoke('xcagi:export-support-bundle'),
  checkForUpdates: () => ipcRenderer.invoke('xcagi:check-for-updates'),
  getUpdateStatus: () => ipcRenderer.invoke('xcagi:get-update-status'),
  downloadUpdate: () => ipcRenderer.invoke('xcagi:download-update'),
  installUpdate: () => ipcRenderer.invoke('xcagi:install-update'),
  getPairingQrPayload: () => ipcRenderer.invoke('xcagi:pairing-qr'),
  openKellaiDesktop: () => ipcRenderer.invoke('xcagi:open-kellai-desktop'),
  setBadge: (count: number) => ipcRenderer.invoke('xcagi:set-badge', count),
  showNotification: (title: string, body: string) =>
    ipcRenderer.invoke('xcagi:show-notification', { title, body }),
  offlineQuery: (params: unknown) => ipcRenderer.invoke('xcagi:offline-query', params),
  secureGet: (key: string) => ipcRenderer.invoke('xcagi:secure-get', key),
  secureSet: (key: string, value: string) => ipcRenderer.invoke('xcagi:secure-set', key, value),
  secureDelete: (key: string) => ipcRenderer.invoke('xcagi:secure-delete', key),
  secureList: () => ipcRenderer.invoke('xcagi:secure-list'),
  clipboardReadText: () => ipcRenderer.invoke('xcagi:clipboard-read-text'),
  clipboardWriteText: (text: string) => ipcRenderer.invoke('xcagi:clipboard-write-text', text),
  openPath: (target: string) => ipcRenderer.invoke('xcagi:open-path', target),
  getAutoLaunch: () => ipcRenderer.invoke('xcagi:get-auto-launch'),
  setAutoLaunch: (enabled: boolean) => ipcRenderer.invoke('xcagi:set-auto-launch', enabled),
  consumeDeepLink: () => ipcRenderer.invoke('xcagi:consume-deep-link'),
  reportError: (payload: { type: string; error: string; stack?: string }) =>
    ipcRenderer.invoke('xcagi:report-error', payload),
  consumeReleaseNotes: () => ipcRenderer.invoke('xcagi:consume-release-notes'),
  captureScreenshot: () => ipcRenderer.invoke('xcagi:capture-screenshot'),
  openWindow: (url?: string) => ipcRenderer.invoke('xcagi:open-window', { url }),
  onDeepLink: (callback: (url: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, url: string) => callback(url)
    ipcRenderer.on('xcagi:deep-link', listener)
    return () => ipcRenderer.removeListener('xcagi:deep-link', listener)
  },
  onScreenshotCaptured: (callback: (result: { ok: boolean; path?: string; error?: string }) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, result: { ok: boolean; path?: string; error?: string }) =>
      callback(result)
    ipcRenderer.on('xcagi:screenshot-captured', listener)
    return () => ipcRenderer.removeListener('xcagi:screenshot-captured', listener)
  },
  onVoiceInvoke: (callback: () => void) => {
    const listener = () => callback()
    ipcRenderer.on('xcagi:voice-invoke', listener)
    return () => ipcRenderer.removeListener('xcagi:voice-invoke', listener)
  },
  onUpdateEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('xcagi:update-event', listener)
    return () => ipcRenderer.removeListener('xcagi:update-event', listener)
  },
  /** 后端健康状态（unhealthy / restarting / ready）：渲染端据此恢复请求，不整页刷新。 */
  onBackendHealth: (callback: (state: string) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: { state?: string }) => callback(String(payload?.state || ''))
    ipcRenderer.on('xcagi:backend-health', listener)
    return () => ipcRenderer.removeListener('xcagi:backend-health', listener)
  }
})

// 渲染进程错误遥测：全局捕获 window.onerror / unhandledrejection，失败静默。
// 通过 ipcRenderer 直连上报通道，避免依赖页面上下文注入的时序问题。
const reportRendererError = (payload: { type: string; error: string; stack?: string; source?: string }) => {
  void ipcRenderer.invoke('xcagi:report-error', payload).catch(() => undefined)
}

function usableText(value: unknown): string {
  const text = typeof value === 'string' ? value.trim() : ''
  return text && text !== 'unknown' ? text : ''
}

function stackLine(stack?: string): string {
  if (!stack) return ''
  const line = stack.split('\n').map(part => part.trim()).find(Boolean) || ''
  return line.replace(/^Error:\s*/, '')
}

function describeFault(value: unknown): { error: string; stack?: string } {
  if (value instanceof Error) {
    const stack = value.stack
    return { error: usableText(value.message) || usableText(value.name) || stackLine(stack), stack }
  }
  if (value && typeof value === 'object') {
    const record = value as { message?: unknown; name?: unknown; stack?: unknown }
    const stack = typeof record.stack === 'string' ? record.stack : undefined
    const error = usableText(record.message) || usableText(record.name) || stackLine(stack)
    if (error || stack) return { error, stack }
  }
  if (typeof value === 'string') return { error: usableText(value) }
  if (value == null) return { error: '' }
  try {
    return { error: JSON.stringify(value) }
  } catch {
    return { error: String(value) }
  }
}

function resourceTarget(event: Event): string {
  const target = event.target
  if (!target || target === window) return ''
  const element = target as { tagName?: string; src?: string; href?: string }
  const tag = element.tagName || target.constructor?.name || 'resource'
  const url = element.src || element.href || ''
  return url ? `${tag} ${url}` : tag
}

window.addEventListener(
  'error',
  (event) => {
    const described = describeFault(event.error)
    const location = [event.filename, event.lineno, event.colno].filter((part) => part !== undefined && part !== '').join(':')
    reportRendererError({
      type: 'renderer:error',
      error: described.error || usableText(event.message) || resourceTarget(event) || 'renderer error without message',
      stack: described.stack,
      source: location || undefined,
    })
  },
  true,
)

window.addEventListener(
  'unhandledrejection',
  (event) => {
    const described = describeFault(event.reason)
    reportRendererError({
      type: 'renderer:unhandledrejection',
      error: described.error || 'unhandled rejection without reason',
      stack: described.stack,
    })
  },
  true,
)
