'use strict'
// XCAGI 桌面客户端（精简）：加载 XCAGI 工作台 Web 面，作为干净构建链的可安装产物。
// 全产品线 v10 锁：版本恒 10.0.0（见 package.json / FHD/VERSION.md）。
const { app, BrowserWindow, shell, Menu, ipcMain, dialog, session } = require('electron')
const path = require('path')

const HOME_URL = process.env.XCAGI_DESKTOP_URL || 'https://xiu-ci.com/market/'
const APP_VERSION = app.getVersion()
const DOWNLOAD_TIMEOUT_MS = 30_000
const pendingDownloads = new Map()

function sanitizeDownloadFileName(filename) {
  const base = path.basename(String(filename || '').trim())
  const cleaned = base.replace(/[<>:"/\\|?*\x00-\x1F]/g, '_').replace(/\s+/g, ' ').trim()
  return cleaned || 'XCAGI-download'
}

function assertSafeDownloadUrl(rawUrl) {
  let parsed
  try {
    parsed = new URL(String(rawUrl || ''))
  } catch {
    throw new Error('下载地址无效')
  }
  const isLocalDev = ['localhost', '127.0.0.1', '::1'].includes(parsed.hostname)
  if (!['https:', 'http:'].includes(parsed.protocol)) {
    throw new Error('仅允许 http(s) 下载地址')
  }
  if (parsed.protocol !== 'https:' && !isLocalDev) {
    throw new Error('非本地地址必须使用 HTTPS')
  }
  return parsed.toString()
}

function takePendingDownload(webContents, item) {
  const queue = pendingDownloads.get(webContents.id)
  if (!queue?.length) return null

  const itemUrl = item.getURL()
  const urlChain = typeof item.getURLChain === 'function' ? item.getURLChain() : []
  let index = queue.findIndex((entry) => entry.url === itemUrl || urlChain.includes(entry.url))
  if (index < 0 && queue.length === 1) index = 0
  if (index < 0) return null

  const [entry] = queue.splice(index, 1)
  if (!queue.length) pendingDownloads.delete(webContents.id)
  clearTimeout(entry.timer)
  return entry
}

function enqueueDownload(webContents, url, savePath) {
  return new Promise((resolve) => {
    const entry = {
      url,
      savePath,
      resolve,
      timer: setTimeout(() => {
        const queue = pendingDownloads.get(webContents.id) || []
        const idx = queue.indexOf(entry)
        if (idx >= 0) queue.splice(idx, 1)
        if (!queue.length) pendingDownloads.delete(webContents.id)
        resolve({ ok: false, error: '下载没有开始，请检查网络或下载地址' })
      }, DOWNLOAD_TIMEOUT_MS),
    }

    const queue = pendingDownloads.get(webContents.id) || []
    queue.push(entry)
    pendingDownloads.set(webContents.id, queue)

    try {
      webContents.downloadURL(url)
    } catch (error) {
      clearTimeout(entry.timer)
      const idx = queue.indexOf(entry)
      if (idx >= 0) queue.splice(idx, 1)
      if (!queue.length) pendingDownloads.delete(webContents.id)
      resolve({ ok: false, error: error instanceof Error ? error.message : String(error) })
    }
  })
}

function configureDownloadHandling() {
  session.defaultSession.on('will-download', (event, item, webContents) => {
    const pending = webContents ? takePendingDownload(webContents, item) : null
    const suggestedName = sanitizeDownloadFileName(
      pending?.savePath ? path.basename(pending.savePath) : item.getFilename(),
    )
    const savePath = pending?.savePath || path.join(app.getPath('downloads'), suggestedName)

    item.setSavePath(savePath)
    item.once('done', (_event, state) => {
      if (!pending) return
      if (state === 'completed') {
        pending.resolve({ ok: true, filePath: savePath, filename: path.basename(savePath) })
        return
      }
      pending.resolve({
        ok: false,
        canceled: state === 'cancelled',
        error: state === 'cancelled' ? '下载已取消' : `下载失败：${state}`,
      })
    })
  })

  ipcMain.handle('xcagi:download-file', async (event, payload) => {
    const url = assertSafeDownloadUrl(payload?.url)
    const filename = sanitizeDownloadFileName(payload?.filename)
    const win = BrowserWindow.fromWebContents(event.sender)
    const defaultPath = path.join(app.getPath('downloads'), filename)
    const saveOptions = {
      title: '保存 XCAGI 安装包',
      defaultPath,
      buttonLabel: '保存',
      properties: ['createDirectory'],
    }
    const { canceled, filePath } = win
      ? await dialog.showSaveDialog(win, saveOptions)
      : await dialog.showSaveDialog(saveOptions)
    if (canceled || !filePath) return { ok: false, canceled: true }
    return enqueueDownload(event.sender, url, filePath)
  })
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 600,
    title: `XCAGI ${APP_VERSION}`,
    backgroundColor: '#0b0f1a',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      spellcheck: false,
    },
  })

  // 外链走系统浏览器，不在应用内开新窗口
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  win.loadURL(HOME_URL)
  return win
}

function buildMenu() {
  const template = [
    {
      label: 'XCAGI',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { type: 'separator' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    { role: 'editMenu' },
    { role: 'viewMenu' },
    { role: 'windowMenu' },
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

app.whenReady().then(() => {
  configureDownloadHandling()
  buildMenu()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
