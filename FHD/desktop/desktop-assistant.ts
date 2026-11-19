import { BrowserWindow, app, screen } from 'electron'
import path from 'node:path'
import { desktopInitialUrl } from './desktop-config'
import { desktopRuntime } from './runtime-state'
import { writeBackendLog } from './backend-process'
import { openTrustedAuxiliaryFromHandler } from './window-manager'

const compact = { width: 104, height: 80 }
const panel = { width: 440, height: 640 }

export function desktopAssistantUrl(): string {
  return new URL('/desktop-assistant', desktopInitialUrl()).href
}

function assistantShouldShow(main: BrowserWindow): boolean {
  return desktopRuntime.mainWindow === main && !main.isDestroyed() && !app.isQuitting
    && !app.isHidden?.()
    && desktopRuntime.assistantEnabled && (!main.isVisible() || main.isMinimized())
}

export function resizeDesktopAssistant(win: BrowserWindow, expanded: boolean): void {
  const bounds = win.getBounds()
  const work = screen.getDisplayMatching(bounds).workArea
  const size = expanded ? panel : compact
  const width = Math.min(size.width, work.width)
  const height = Math.min(size.height, work.height)
  const x = Math.max(work.x, Math.min(bounds.x + bounds.width - width, work.x + work.width - width))
  const y = Math.max(work.y, Math.min(bounds.y + bounds.height - height, work.y + work.height - height))
  win.setBounds({ x, y, width, height })
}

export function moveDesktopAssistant(win: BrowserWindow, left: number, top: number): void {
  const { width, height } = win.getBounds()
  const bounds = { x: Math.round(left), y: Math.round(top), width, height }
  const { x, y, width: workWidth, height: workHeight } = screen.getDisplayMatching(bounds).workArea
  win.setPosition(
    Math.max(x, Math.min(bounds.x, x + workWidth - width)),
    Math.max(y, Math.min(bounds.y, y + workHeight - height)),
  )
}

export function syncDesktopAssistant(): void {
  const main = desktopRuntime.mainWindow
  const assistant = desktopRuntime.assistantWindow
  if (!main || !assistantShouldShow(main)) {
    if (assistant?.isVisible()) {
      assistant.webContents.send('xcagi:assistant-hide')
      assistant.hide()
      resizeDesktopAssistant(assistant, false)
    }
    return
  }
  if (assistant) {
    if (desktopRuntime.assistantReady && !assistant.isVisible()) {
      assistant.webContents.send('xcagi:assistant-show')
      assistant.showInactive()
    }
    return
  }

  const ready = desktopRuntime.mainApplicationReady
  if (!ready) return
  void ready.then(() => {
    if (!assistantShouldShow(main) || desktopRuntime.assistantWindow) return
    const work = screen.getDisplayMatching(main.getBounds()).workArea
    const win = new BrowserWindow({
      ...compact,
      x: work.x + work.width - compact.width - 20,
      y: work.y + work.height - compact.height - 20,
      show: false,
      frame: false,
      transparent: true,
      acceptFirstMouse: true,
      alwaysOnTop: true,
      skipTaskbar: true,
      resizable: false,
      fullscreenable: false,
      webPreferences: {
        preload: path.join(__dirname, 'assistant-preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    })
    desktopRuntime.assistantWindow = win
    const url = desktopAssistantUrl()
    win.webContents.setWindowOpenHandler(({ url: target }) => openTrustedAuxiliaryFromHandler(target, win))
    win.webContents.on('will-navigate', (event, target) => {
      event.preventDefault()
      if (target !== url) openTrustedAuxiliaryFromHandler(target, win)
    })
    win.webContents.on('will-redirect', (event, target) => {
      if (target !== url) event.preventDefault()
    })
    win.on('closed', () => {
      desktopRuntime.assistantWindow = null
      desktopRuntime.assistantReady = false
    })
    void win.loadURL(url).then(() => {
      if (!win.isDestroyed()) {
        desktopRuntime.assistantReady = true
        syncDesktopAssistant()
      }
    }).catch(error => {
      if (!win.isDestroyed()) {
        writeBackendLog(`[assistant] window load failed: ${String(error)}\n`)
        win.destroy()
      }
    })
  }).catch(() => undefined)
}
