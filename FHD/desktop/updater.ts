import { BrowserWindow, app, dialog, net, session } from 'electron'
import type { Session } from 'electron'
import { autoUpdater } from 'electron-updater'
import type { UpdateInfo } from 'electron-updater'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

let updateDownloaded = false
let remoteBuildSha = ''
let rebuildHookInstalled = false
let updaterNetSession: Session | null = null
let updaterNetSessionReady: Promise<Session> | null = null

export async function ensureUpdaterNetSession(): Promise<Session> {
  if (updaterNetSession) {
    return updaterNetSession
  }
  if (!updaterNetSessionReady) {
    updaterNetSessionReady = (async () => {
      const updaterSession = session.fromPartition('persist:xcagi-updater', { cache: false })
      await updaterSession.setProxy({ mode: 'direct' })
      updaterNetSession = updaterSession
      const updater = autoUpdater as unknown as { netSession?: Session }
      updater.netSession = updaterSession
      return updaterSession
    })()
  }
  return updaterNetSessionReady
}

export function fetchTextViaSession(targetSession: Session, url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const request = net.request({ method: 'GET', url, session: targetSession })
    const chunks: Buffer[] = []
    request.on('response', response => {
      response.on('data', chunk => chunks.push(Buffer.from(chunk)))
      response.on('end', () => {
        const status = response.statusCode || 0
        if (status < 200 || status >= 300) {
          reject(new Error(`更新元数据下载失败: ${status} ${response.statusMessage || ''}`.trim()))
          return
        }
        resolve(Buffer.concat(chunks).toString('utf8'))
      })
      response.on('error', reject)
    })
    request.on('error', reject)
    request.end()
  })
}

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

export function readLocalBuildSha(): string {
  return readLocalBuildIdentity().buildSha
}

export type BuildIdentity = {
  version: string
  buildSha: string
  builtAt: string
}

export function parseBuildIdentityJson(content: string, fallbackVersion: string): BuildIdentity {
  const raw = JSON.parse(content.replace(/^\uFEFF/, '')) as {
    version?: string
    gitSha?: string
    buildSha?: string
    builtAt?: string
  }
  return {
    version: String(raw.version || fallbackVersion).trim(),
    buildSha: String(raw.gitSha || raw.buildSha || '').trim(),
    builtAt: String(raw.builtAt || '').trim(),
  }
}

export function readLocalBuildIdentity(): BuildIdentity {
  if (!app.isPackaged) {
    return {
      version: app.getVersion(),
      buildSha: String(process.env.XCAGI_BUILD_SHA || '').trim(),
      builtAt: String(process.env.XCAGI_BUILD_AT || '').trim(),
    }
  }
  const candidates = [
    path.join(process.resourcesPath, 'build-info.json'),
    path.join(process.resourcesPath, 'backend', 'build-info.json')
  ]
  for (const filePath of candidates) {
    try {
      if (!fs.existsSync(filePath)) continue
      const identity = parseBuildIdentityJson(
        fs.readFileSync(filePath, 'utf8'),
        app.getVersion()
      )
      if (identity.buildSha || identity.builtAt) return identity
    } catch {
      /* try next */
    }
  }
  return { version: app.getVersion(), buildSha: '', builtAt: '' }
}

export function isNewerSameVersionRebuild(input: {
  remoteVersion: string
  remoteBuildSha: string
  remoteReleaseDate: string
  localVersion: string
  localBuildSha: string
  localBuiltAt: string
}): boolean {
  if (!input.remoteVersion || input.remoteVersion !== input.localVersion) return false
  if (!input.remoteBuildSha || !input.localBuildSha) return false
  if (input.remoteBuildSha === input.localBuildSha) return false

  // Legacy installers did not record builtAt. Preserve their same-version repair path.
  if (!input.localBuiltAt) return true

  const remoteTime = Date.parse(input.remoteReleaseDate)
  const localTime = Date.parse(input.localBuiltAt)
  return Number.isFinite(remoteTime) && Number.isFinite(localTime) && remoteTime > localTime
}

export function parseYamlField(content: string, field: string): string {
  const prefix = `${field}:`
  const line = content.split(/\r?\n/).find(entry => entry.startsWith(prefix))
  return line ? line.slice(prefix.length).trim() : ''
}

function installSameVersionRebuildHook(): void {
  if (rebuildHookInstalled) {
    return
  }
  rebuildHookInstalled = true
  // electron-updater 将 isUpdateAvailable 标为 private；经 unknown 注入同版本 buildSha 比对。
  const updater = autoUpdater as unknown as {
    isUpdateAvailable?: (updateInfo: UpdateInfo) => boolean
  }
  const original = updater.isUpdateAvailable?.bind(autoUpdater)
  updater.isUpdateAvailable = (updateInfo: UpdateInfo) => {
    if (original?.(updateInfo)) {
      return true
    }
    const remoteSha = String(
      (updateInfo as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || ''
    ).trim()
    const local = readLocalBuildIdentity()
    return isNewerSameVersionRebuild({
      remoteVersion: String(updateInfo.version || '').trim(),
      remoteBuildSha: remoteSha,
      remoteReleaseDate: String(updateInfo.releaseDate || '').trim(),
      localVersion: local.version,
      localBuildSha: local.buildSha,
      localBuiltAt: local.builtAt,
    })
  }
}

export function configureUpdater(mainWindow: BrowserWindow, beforeInstall?: (toVersion: string) => Promise<void>): void {
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true
  if (process.env.XCAGI_DESKTOP_TEST !== '1') {
    void ensureUpdaterNetSession()
  }

  const updateUrl = process.env.XCAGI_UPDATE_URL
  if (updateUrl) {
    // generic 提供方默认拉取 latest.yml；勿设 channel，否则会请求 stable.yml 导致 404。
    const feed: { provider: 'generic'; url: string; channel?: string } = {
      provider: 'generic',
      url: updateUrl,
    }
    const channel = String(process.env.XCAGI_UPDATE_CHANNEL || '').trim()
    if (channel) {
      feed.channel = channel
    }
    autoUpdater.setFeedURL(feed)
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
    const local = readLocalBuildIdentity()
    const remoteSha = String(
      (info as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || ''
    ).trim()
    if (
      info.version === local.version &&
      !isNewerSameVersionRebuild({
        remoteVersion: info.version,
        remoteBuildSha: remoteSha,
        remoteReleaseDate: String(info.releaseDate || '').trim(),
        localVersion: local.version,
        localBuildSha: local.buildSha,
        localBuiltAt: local.builtAt,
      })
    ) {
      updateDownloaded = false
      appendUpdaterEvent('download_ignored_stale_same_version', {
        version: info.version,
        remoteBuildSha: remoteSha,
        localBuildSha: local.buildSha,
      })
      send('update-not-available', { ...info, reason: 'stale-same-version' })
      return
    }

    updateDownloaded = true
    send('update-downloaded', info)
    const sameVersionRebuild = info.version === local.version
    const result = await dialog.showMessageBox(mainWindow, {
      type: 'info',
      buttons: ['稍后', '立即重启安装'],
      defaultId: 1,
      cancelId: 0,
      title: 'XCAGI 更新已下载',
      message: sameVersionRebuild
        ? `版本 ${info.version} 的维护更新已准备好，是否立即重启安装？`
        : `新版本 ${info.version} 已准备好，是否立即重启安装？`
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
    void runUpdateCheckWithDirectNet().catch(error => send('error', { message: error.message }))
  }, 60_000)

  setInterval(() => {
    if (!app.isPackaged && !process.env.XCAGI_UPDATE_URL) {
      return
    }
    void runUpdateCheckWithDirectNet().catch(error => send('error', { message: error.message }))
  }, 6 * 60 * 60 * 1000)
}

export async function runUpdateCheckWithDirectNet(): Promise<unknown> {
  const defaultSession = session.defaultSession
  const previous = await defaultSession.resolveProxy('https://xiu-ci.com')
  await defaultSession.setProxy({ mode: 'direct' })
  try {
    return await checkForUpdates()
  } finally {
    if (/^PROXY/i.test(previous) || /^SOCKS/i.test(previous)) {
      await defaultSession.setProxy({ mode: 'system' })
    } else {
      await defaultSession.setProxy({ mode: 'direct' })
    }
  }
}

export async function checkForUpdates(): Promise<unknown> {
  if (!app.isPackaged && !process.env.XCAGI_UPDATE_URL) {
    return { skipped: true, reason: 'dev-mode-without-XCAGI_UPDATE_URL' }
  }
  if (process.env.XCAGI_DESKTOP_TEST !== '1') {
    await ensureUpdaterNetSession()
  }
  const publicKeyPem = process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  const updateUrl = process.env.XCAGI_UPDATE_URL
  if (publicKeyPem && updateUrl) {
    const metadataText = await fetchLatestMetadataText()
    remoteBuildSha = parseYamlField(metadataText, 'buildSha')
    installSameVersionRebuildHook()
  }
  return autoUpdater.checkForUpdates()
}

export async function fetchLatestMetadataText(): Promise<string> {
  const publicKeyPem = process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  const updateUrl = process.env.XCAGI_UPDATE_URL
  if (!publicKeyPem || !updateUrl) {
    return ''
  }

  const file = process.platform === 'darwin' ? 'latest-mac.yml' : 'latest.yml'
  const url = `${updateUrl.replace(/\/+$/, '')}/${file}`
  let content: string
  if (process.env.XCAGI_DESKTOP_TEST === '1') {
    const response = await fetch(url)
    if (!response.ok) {
      throw new Error(`更新元数据下载失败: ${response.status} ${response.statusText}`)
    }
    content = await response.text()
  } else {
    const updaterSession = await ensureUpdaterNetSession()
    content = await fetchTextViaSession(updaterSession, url)
  }
  await verifyMetadataSignatureText(content, publicKeyPem)
  return content
}

export async function verifyLatestMetadataSignature(): Promise<void> {
  await fetchLatestMetadataText()
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
