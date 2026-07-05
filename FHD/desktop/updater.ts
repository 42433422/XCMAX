import { BrowserWindow, app, dialog } from 'electron'
import { autoUpdater } from 'electron-updater'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

let updateDownloaded = false

function updaterLogPath(): string {
  return path.join(app.getPath('userData'), 'logs', 'updater-events.jsonl')
}

function appendUpdaterEvent(type: string, data?: unknown): void {
  try {
    const dir = path.dirname(updaterLogPath())
    fs.mkdirSync(dir, { recursive: true })
    fs.appendFileSync(
      updaterLogPath(),
      `${JSON.stringify({ ts: new Date().toISOString(), type, data })}\n`,
      'utf8',
    )
  } catch {
    /* ignore log failures */
  }
}

export function isUpdateDownloaded(): boolean {
  return updateDownloaded
}

export function configureUpdater(mainWindow: BrowserWindow, beforeInstall?: (toVersion: string) => Promise<void>): void {
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true

  const updateUrl = process.env.XCAGI_UPDATE_URL
  if (updateUrl) {
    autoUpdater.setFeedURL({
      provider: 'generic',
      url: updateUrl,
      channel: process.env.XCAGI_UPDATE_CHANNEL || 'stable'
    })
  }

  const send = (type: string, data?: unknown) => {
    mainWindow.webContents.send('xcagi:update-event', { type, data })
  }

  autoUpdater.on('checking-for-update', () => send('checking-for-update'))
  autoUpdater.on('update-available', info => {
    send('update-available', info)
    void autoUpdater.downloadUpdate().catch(error => {
      send('error', { message: error.message, phase: 'download' })
      appendUpdaterEvent('download_failed', { message: error.message })
      updateDownloaded = false
    })
  })
  autoUpdater.on('update-not-available', info => send('update-not-available', info))
  autoUpdater.on('download-progress', progress => send('download-progress', progress))
  autoUpdater.on('update-downloaded', async info => {
    updateDownloaded = true
    send('update-downloaded', info)
    const result = await dialog.showMessageBox(mainWindow, {
      type: 'info',
      buttons: ['稍后', '立即重启安装'],
      defaultId: 1,
      cancelId: 0,
      title: 'XCAGI 更新已下载',
      message: `新版本 ${info.version} 已准备好，是否立即重启安装？`
    })
    if (result.response === 1) {
      try {
        if (beforeInstall) {
          await beforeInstall(info.version)
        }
        appendUpdaterEvent('install_start', { version: info.version })
        autoUpdater.quitAndInstall(false, true)
      } catch (error) {
        appendUpdaterEvent('install_failed', {
          message: error instanceof Error ? error.message : String(error),
        })
        updateDownloaded = true
        await dialog.showMessageBox(mainWindow, {
          type: 'error',
          title: '更新安装失败',
          message: '更新安装未完成，当前版本仍可继续使用。可导出诊断包后重试或安装上一版本。',
        })
      }
    }
  })
  autoUpdater.on('error', error => {
    send('error', { message: error.message, stack: error.stack, phase: 'updater' })
    appendUpdaterEvent('error', { message: error.message, stack: error.stack })
    updateDownloaded = false
  })

  setTimeout(() => {
    void checkForUpdates().catch(error => send('error', { message: error.message }))
  }, 60_000)

  setInterval(() => {
    if (!app.isPackaged && !process.env.XCAGI_UPDATE_URL) {
      return
    }
    void checkForUpdates().catch(error => send('error', { message: error.message }))
  }, 6 * 60 * 60 * 1000)
}

export async function checkForUpdates(): Promise<unknown> {
  if (!app.isPackaged && !process.env.XCAGI_UPDATE_URL) {
    return { skipped: true, reason: 'dev-mode-without-XCAGI_UPDATE_URL' }
  }
  await verifyLatestMetadataSignature()
  return autoUpdater.checkForUpdates()
}

export async function installUpdate(beforeInstall?: (toVersion: string) => Promise<void>): Promise<void> {
  if (!updateDownloaded) {
    throw new Error('尚未下载更新包，请先检查更新并等待下载完成')
  }
  if (beforeInstall) {
    await beforeInstall('manual')
  }
  autoUpdater.quitAndInstall(false, true)
}

export async function verifyLatestMetadataSignature(): Promise<void> {
  const publicKeyPem = process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  const updateUrl = process.env.XCAGI_UPDATE_URL
  if (!publicKeyPem || !updateUrl) {
    return
  }

  const file = process.platform === 'darwin' ? 'latest-mac.yml' : 'latest.yml'
  const url = `${updateUrl.replace(/\/+$/, '')}/${file}`
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`更新元数据下载失败: ${response.status} ${response.statusText}`)
  }

  const content = await response.text()
  await verifyMetadataSignatureText(content, publicKeyPem)
}

/** 纯函数：校验 update 元数据文本的 Ed25519 二次签名。便于单测。 */
export async function verifyMetadataSignatureText(content: string, publicKeyPem: string): Promise<void> {
  const lines = content.split(/\r?\n/)
  const signatureLine = lines.find(line => line.startsWith('signature: ed25519:'))
  if (!signatureLine) {
    throw new Error('更新元数据缺少 Ed25519 二次签名')
  }

  const body = lines.filter(line => !line.startsWith('signature: ed25519:')).join('\n').trimEnd()
  const signature = Buffer.from(signatureLine.replace('signature: ed25519:', '').trim(), 'base64')
  const publicKey = crypto.createPublicKey(publicKeyPem.replace(/\\n/g, '\n'))
  const ok = crypto.verify(null, Buffer.from(body, 'utf8'), publicKey, signature)
  if (!ok) {
    throw new Error('更新元数据 Ed25519 二次签名校验失败')
  }
}

/** 测试辅助：重置 updateDownloaded 状态。仅用于单测。 */
export function __resetUpdateDownloadedForTest(): void {
  updateDownloaded = false
}
