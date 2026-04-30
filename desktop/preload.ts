import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('xcagiDesktop', {
  platform: process.platform,
  versions: process.versions,
  getDataDir: () => ipcRenderer.invoke('xcagi:get-data-dir'),
  checkForUpdates: () => ipcRenderer.invoke('xcagi:check-for-updates'),
  installUpdate: () => ipcRenderer.invoke('xcagi:install-update'),
  onUpdateEvent: (callback: (event: unknown) => void) => {
    const listener = (_event: Electron.IpcRendererEvent, payload: unknown) => callback(payload)
    ipcRenderer.on('xcagi:update-event', listener)
    return () => ipcRenderer.removeListener('xcagi:update-event', listener)
  }
})
