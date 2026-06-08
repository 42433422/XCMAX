'use strict'
// XCAGI 桌面客户端（精简）：加载 XCAGI 工作台 Web 面，作为干净构建链的可安装产物。
// 全产品线 v10 锁：版本恒 10.0.0（见 package.json / FHD/VERSION.md）。
const { app, BrowserWindow, shell, Menu } = require('electron')
const path = require('path')

const HOME_URL = process.env.XCAGI_DESKTOP_URL || 'https://xiu-ci.com/market/'
const APP_VERSION = app.getVersion()

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
  buildMenu()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
