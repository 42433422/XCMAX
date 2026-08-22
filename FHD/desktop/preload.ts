import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('xcagiDesktop', {
  platform: process.platform,
  versions: process.versions,
  getDataDir: () => ipcRenderer.invoke('xcagi:get-data-dir'),
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
  }
})

// 渲染进程错误遥测：全局捕获 window.onerror / unhandledrejection，失败静默。
// 通过 ipcRenderer 直连上报通道，避免依赖页面上下文注入的时序问题。
const reportRendererError = (payload: { type: string; error: string; stack?: string }) => {
  void ipcRenderer.invoke('xcagi:report-error', payload).catch(() => undefined)
}

window.addEventListener(
  'error',
  (event) => {
    const err = event.error
    reportRendererError({
      type: 'renderer:error',
      error: err instanceof Error ? err.message : String(event.message || 'unknown'),
      stack: err instanceof Error ? err.stack : undefined,
    })
  },
  true,
)

window.addEventListener(
  'unhandledrejection',
  (event) => {
    const reason = event.reason
    reportRendererError({
      type: 'renderer:unhandledrejection',
      error: reason instanceof Error ? reason.message : String(reason),
      stack: reason instanceof Error ? reason.stack : undefined,
    })
  },
  true,
)
