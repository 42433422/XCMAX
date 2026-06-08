import { BrowserWindow, app, dialog } from 'electron'
import { autoUpdater } from 'electron-updater'
import crypto from 'node:crypto'

export function configureUpdater(mainWindow: BrowserWindow, beforeInstall?: () => Promise<void>): void {
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
  autoUpdater.on('update-available', info => send('update-available', info))
  autoUpdater.on('update-not-available', info => send('update-not-available', info))
  autoUpdater.on('download-progress', progress => send('download-progress', progress))
  autoUpdater.on('update-downloaded', async info => {
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
      if (beforeInstall) {
        await beforeInstall()
      }
      autoUpdater.quitAndInstall(false, true)
    }
  })
  autoUpdater.on('error', error => send('error', { message: error.message, stack: error.stack }))

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

export async function installUpdate(beforeInstall?: () => Promise<void>): Promise<void> {
  if (beforeInstall) {
    await beforeInstall()
  }
  autoUpdater.quitAndInstall(false, true)
}

async function verifyLatestMetadataSignature(): Promise<void> {
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
