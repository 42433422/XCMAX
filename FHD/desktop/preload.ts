import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('xcagiDesktop', {
  platform: process.platform,
  versions: process.versions,
  getDataDir: () => ipcRenderer.invoke('xcagi:get-data-dir'),
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
  onUpdateEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('xcagi:update-event', listener)
    return () => ipcRenderer.removeListener('xcagi:update-event', listener)
  }
})
