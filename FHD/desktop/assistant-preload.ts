import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('xcagiDesktopAssistant', {
  setExpanded: (expanded: boolean) => ipcRenderer.invoke('xcagi:assistant-expand', expanded),
  moveWindow: (x: number, y: number) => ipcRenderer.invoke('xcagi:assistant-move', x, y),
  openMain: () => ipcRenderer.invoke('xcagi:assistant-open-main'),
  onShow: (callback: () => void) => {
    const listener = () => callback()
    ipcRenderer.on('xcagi:assistant-show', listener)
    return () => ipcRenderer.removeListener('xcagi:assistant-show', listener)
  },
  onHide: (callback: () => void) => {
    const listener = () => callback()
    ipcRenderer.on('xcagi:assistant-hide', listener)
    return () => ipcRenderer.removeListener('xcagi:assistant-hide', listener)
  },
})
