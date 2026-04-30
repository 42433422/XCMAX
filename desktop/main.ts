import { BrowserWindow, Menu, Tray, app, dialog, ipcMain, nativeImage, shell } from 'electron'
import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { checkForUpdates, configureUpdater, installUpdate } from './updater'

const APP_NAME = 'XCAGI'
const DEFAULT_PORT = Number(process.env.XCAGI_DESKTOP_PORT || 5000)

let mainWindow: BrowserWindow | null = null
let backendProcess: ChildProcessWithoutNullStreams | null = null
let tray: Tray | null = null
let restartCount = 0

function repoRoot(): string {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..', '..')
}

/** 托盘与窗口图标：与 dist 同级打包的 resources（由 beforePack 生成）。 */
function shellIconPath(): string {
  const name = process.platform === 'win32' ? 'icon.ico' : 'icon.png'
  return path.join(__dirname, '..', 'resources', name)
}

function backendExecutable(): { command: string; args: string[]; cwd: string } {
  const dataDir = app.getPath('userData')
  if (!app.isPackaged) {
    const root = repoRoot()
    return {
      command: process.env.PYTHON || 'python',
      args: [
        path.join(root, 'XCAGI', 'run.py'),
        '--desktop',
        '--headless',
        '--host',
        '127.0.0.1',
        '--port',
        String(DEFAULT_PORT),
        '--data-dir',
        dataDir
      ],
      cwd: root
    }
  }

  const backendDir = path.join(process.resourcesPath, 'backend')
  const command =
    process.platform === 'win32'
      ? path.join(backendDir, 'xcagi-backend.exe')
      : path.join(backendDir, 'xcagi-backend')

  return {
    command,
    args: [
      '--desktop',
      '--headless',
      '--host',
      '127.0.0.1',
      '--port',
      String(DEFAULT_PORT),
      '--data-dir',
      dataDir
    ],
    cwd: path.dirname(command)
  }
}

function waitForPort(port: number, timeoutMs = 45_000): Promise<void> {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const socket = net.createConnection({ host: '127.0.0.1', port })
      socket.once('connect', () => {
        socket.end()
        resolve()
      })
      socket.once('error', () => {
        socket.destroy()
        if (Date.now() - started > timeoutMs) {
          reject(new Error(`后端端口 ${port} 在 ${timeoutMs}ms 内未就绪`))
          return
        }
        setTimeout(attempt, 500)
      })
    }
    attempt()
  })
}

async function waitForBackend(port: number, timeoutMs = 60_000): Promise<void> {
  const started = Date.now()
  while (Date.now() - started <= timeoutMs) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/desktop/status`)
      if (response.ok) {
        return
      }
    } catch {
      // Keep polling until FastAPI has finished importing all routers.
    }
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  throw new Error(`后端服务在 ${timeoutMs}ms 内未通过健康检查`)
}

function startBackend(): void {
  if (backendProcess) {
    return
  }

  const executable = backendExecutable()
  if (app.isPackaged && !fs.existsSync(executable.command)) {
    void dialog.showErrorBox(APP_NAME, `找不到后端程序：${executable.command}`)
    return
  }

  backendProcess = spawn(executable.command, executable.args, {
    cwd: executable.cwd,
    env: {
      ...process.env,
      XCAGI_DESKTOP_MODE: '1',
      XCAGI_DATA_DIR: app.getPath('userData'),
      PYTHONUTF8: '1'
    },
    windowsHide: true
  })

  backendProcess.stdout.on('data', data => process.stdout.write(`[xcagi-backend] ${data}`))
  backendProcess.stderr.on('data', data => process.stderr.write(`[xcagi-backend] ${data}`))
  backendProcess.on('exit', code => {
    backendProcess = null
    if (app.isQuitting) {
      return
    }
    restartCount += 1
    if (restartCount <= 3) {
      setTimeout(startBackend, 1500)
      return
    }
    void dialog.showErrorBox(APP_NAME, `后端服务已退出（code=${code}），请重启 XCAGI。`)
  })
}

function runBackendMigration(): Promise<void> {
  const executable = backendExecutable()
  return new Promise((resolve, reject) => {
    const child = spawn(executable.command, [...executable.args, '--migrate-only', '--backup'], {
      cwd: executable.cwd,
      env: {
        ...process.env,
        XCAGI_DESKTOP_MODE: '1',
        XCAGI_DATA_DIR: app.getPath('userData'),
        PYTHONUTF8: '1'
      },
      windowsHide: true
    })
    let stderr = ''
    child.stderr.on('data', data => {
      stderr += String(data)
      process.stderr.write(`[xcagi-migrate] ${data}`)
    })
    child.stdout.on('data', data => process.stdout.write(`[xcagi-migrate] ${data}`))
    child.on('error', reject)
    child.on('exit', code => {
      if (code === 0) {
        resolve()
      } else {
        reject(new Error(`数据库迁移失败（code=${code}）: ${stderr}`))
      }
    })
  })
}

function stopBackend(): void {
  const child = backendProcess
  backendProcess = null
  if (!child || child.killed) {
    return
  }
  child.kill(process.platform === 'win32' ? undefined : 'SIGTERM')
}

async function createWindow(): Promise<void> {
  const icon = shellIconPath()
  const winOpts: Electron.BrowserWindowConstructorOptions = {
    width: 1440,
    height: 920,
    minWidth: 1180,
    minHeight: 760,
    title: APP_NAME,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  }
  if (fs.existsSync(icon)) {
    winOpts.icon = icon
  }
  mainWindow = new BrowserWindow(winOpts)

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  await waitForPort(DEFAULT_PORT)
  await waitForBackend(DEFAULT_PORT)
  await mainWindow.loadURL(`http://127.0.0.1:${DEFAULT_PORT}/`)
  configureUpdater(mainWindow, runBackendMigration)
}

function createMenu(): void {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: APP_NAME,
      submenu: [
        { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
        { label: '检查更新', click: () => void checkForUpdates() },
        { type: 'separator' },
        { role: 'quit', label: '退出' }
      ]
    },
    { role: 'editMenu', label: '编辑' },
    { role: 'viewMenu', label: '视图' },
    { role: 'windowMenu', label: '窗口' }
  ]
  Menu.setApplicationMenu(Menu.buildFromTemplate(template))
}

function createTray(): void {
  const iconPath = shellIconPath()
  if (!fs.existsSync(iconPath)) {
    return
  }
  const image = nativeImage.createFromPath(iconPath)
  tray = new Tray(image)
  tray.setToolTip(APP_NAME)
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: '显示 XCAGI', click: () => mainWindow?.show() },
      { label: '打开数据目录', click: () => void shell.openPath(app.getPath('userData')) },
      { type: 'separator' },
      { label: '退出', click: () => app.quit() }
    ])
  )
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.on('before-quit', () => {
    app.isQuitting = true
    stopBackend()
  })

  app.whenReady().then(async () => {
    ipcMain.handle('xcagi:get-data-dir', () => app.getPath('userData'))
    ipcMain.handle('xcagi:check-for-updates', () => checkForUpdates())
    ipcMain.handle('xcagi:install-update', () => installUpdate(runBackendMigration))

    createMenu()
    createTray()
    startBackend()
    try {
      await createWindow()
    } catch (error) {
      void dialog.showErrorBox(APP_NAME, error instanceof Error ? error.message : String(error))
      app.quit()
    }
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      void createWindow()
    }
  })
}

declare global {
  namespace Electron {
    interface App {
      isQuitting?: boolean
    }
  }
}
