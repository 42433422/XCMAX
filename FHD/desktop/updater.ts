import { BrowserWindow, app, net, session } from 'electron'
import type { Session } from 'electron'
import { autoUpdater } from 'electron-updater'
import type { UpdateInfo } from 'electron-updater'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import {
  normalizeReleaseMedia,
  parseReleaseMediaFromYaml,
  type ReleaseMediaSlide,
} from './release-media.js'

let updateDownloaded = false
let remoteBuildSha = ''
let remoteReleaseNotes = ''
let remoteReleaseMedia: ReleaseMediaSlide[] = []
let rebuildHookInstalled = false
let updaterNetSession: Session | null = null
let updaterNetSessionReady: Promise<Session> | null = null
let downloadInFlight = false
let downloadPromise: Promise<unknown> | null = null
/** 最近一次可展示给渲染进程的更新事件（刷新页面后可重放）。 */
let lastUpdateEvent: { type: string; data?: unknown } | null = null

export async function ensureUpdaterNetSession(): Promise<Session> {
  if (updaterNetSession) {
    return updaterNetSession
  }
  if (!updaterNetSessionReady) {
    updaterNetSessionReady = (async () => {
      // electron-updater 6.x exposes the exact Session used by its HTTP executor
      // through a read-only getter. Configure that Session in place; assigning to
      // `autoUpdater.netSession` crashes packaged apps because the property has no setter.
      const updaterSession = autoUpdater.netSession
      await updaterSession.setProxy({ mode: 'direct' })
      updaterNetSession = updaterSession
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

/** 渲染进程挂载时拉取，避免 update-available 发生在订阅前或页面刷新后丢失角标。 */
export function getUpdateStatus(): { type: string; data?: unknown } | null {
  return lastUpdateEvent
}

export function readLocalBuildSha(): string {
  if (!app.isPackaged) {
    return String(process.env.XCAGI_BUILD_SHA || '').trim()
  }
  const candidates = [
    path.join(process.resourcesPath, 'build-info.json'),
    path.join(process.resourcesPath, 'backend', 'build-info.json')
  ]
  for (const filePath of candidates) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as { gitSha?: string; buildSha?: string }
      const sha = String(raw.gitSha || raw.buildSha || '').trim()
      if (sha) return sha
    } catch {
      /* try next */
    }
  }
  return ''
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
    // macOS auto-update must use a ZIP artifact; DMG-only feeds are not installable.
    if (process.platform === 'darwin' && !updateInfoHasMacZip(updateInfo)) {
      return false
    }
    if (original?.(updateInfo)) {
      return true
    }
    const remoteSha = String(
      (updateInfo as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || ''
    ).trim()
    const localSha = readLocalBuildSha()
    return Boolean(remoteSha && localSha && remoteSha !== localSha)
  }
}

function updateInfoHasMacZip(updateInfo: UpdateInfo): boolean {
  const files = Array.isArray(updateInfo.files) ? updateInfo.files : []
  if (files.some(file => String(file?.url || '').toLowerCase().endsWith('.zip'))) {
    return true
  }
  const pathHint = String(updateInfo.path || '').toLowerCase()
  return pathHint.endsWith('.zip')
}

function enrichUpdateInfo(
  info: UpdateInfo,
): UpdateInfo & { buildSha?: string; releaseNotes?: string; releaseMedia?: ReleaseMediaSlide[] } {
  const notes = String(
    (info as UpdateInfo & { releaseNotes?: string }).releaseNotes || remoteReleaseNotes || ''
  ).trim()
  const fromInfo = normalizeReleaseMedia(
    (info as UpdateInfo & { releaseMedia?: unknown }).releaseMedia,
  )
  const releaseMedia = fromInfo.length ? fromInfo : remoteReleaseMedia
  return {
    ...info,
    buildSha: String(
      (info as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || ''
    ).trim(),
    releaseNotes: notes,
    ...(releaseMedia.length ? { releaseMedia } : {}),
  }
}

/**
 * Cursor-style updates: check in background, never auto-download / auto-prompt.
 * Renderer shows a corner badge; user opens notes modal, then downloads & restarts.
 */
export function configureUpdater(mainWindow: BrowserWindow): void {
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
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
    if (
      type === 'update-available' ||
      type === 'update-downloaded' ||
      type === 'download-progress'
    ) {
      lastUpdateEvent = { type, data }
    } else if (type === 'update-not-available') {
      lastUpdateEvent = null
    } else if (type === 'error' && lastUpdateEvent?.type === 'update-available') {
      // 不再混入 update-available；前端必须显式处理 update-available-with-error
      lastUpdateEvent = {
        type: 'update-available-with-error',
        data: {
          ...(typeof lastUpdateEvent.data === 'object' && lastUpdateEvent.data
            ? lastUpdateEvent.data
            : {}),
          lastError: data,
        },
      }
    }
    if (!mainWindow.isDestroyed()) {
      mainWindow.webContents.send('xcagi:update-event', { type, data })
    }
  }

  autoUpdater.on('checking-for-update', () => send('checking-for-update'))
  autoUpdater.on('update-available', info => {
    appendUpdaterEvent('update_available', { version: info.version })
    send('update-available', enrichUpdateInfo(info))
  })
  autoUpdater.on('update-not-available', info => send('update-not-available', info))
  autoUpdater.on('download-progress', progress => send('download-progress', progress))
  autoUpdater.on('update-downloaded', info => {
    updateDownloaded = true
    downloadInFlight = false
    appendUpdaterEvent('update_downloaded', { version: info.version })
    send('update-downloaded', enrichUpdateInfo(info))
  })
  autoUpdater.on('error', error => {
    downloadInFlight = false
    send('error', { message: error.message, stack: error.stack, phase: 'updater' })
    appendUpdaterEvent('error', { message: error.message, stack: error.stack })
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

export async function downloadUpdate(): Promise<unknown> {
  if (updateDownloaded) {
    return { alreadyDownloaded: true }
  }
  // 复用 in-flight Promise：并发调用拿到同一份结果，而非误判成功
  if (downloadPromise) {
    return downloadPromise
  }
  downloadInFlight = true
  appendUpdaterEvent('download_start', {})
  downloadPromise = (async () => {
    try {
      return await autoUpdater.downloadUpdate()
    } catch (error) {
      const raw = error instanceof Error ? error.message : String(error)
      const message = /ZIP file not provided/i.test(raw)
        ? '更新服务器提供的是安装包（DMG），无法在应用内自动更新。请改用官网下载 ZIP/安装包，或等待已修复的更新源生效后再试。'
        : raw
      appendUpdaterEvent('download_failed', { message: raw })
      throw new Error(message)
    } finally {
      downloadInFlight = false
      downloadPromise = null
    }
  })()
  return downloadPromise
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

function parseYamlBlock(content: string, field: string): string {
  const lines = content.split(/\r?\n/)
  const start = lines.findIndex(line => line.startsWith(`${field}:`))
  if (start < 0) return ''
  const head = lines[start].slice(`${field}:`.length).trim()
  if (head && head !== '|' && head !== '>') {
    return head.replace(/^["']|["']$/g, '')
  }
  const collected: string[] = []
  for (let i = start + 1; i < lines.length; i += 1) {
    const line = lines[i]
    if (!line.startsWith(' ') && !line.startsWith('\t') && line.trim() !== '') break
    if (line.startsWith('signature:')) break
    collected.push(line.replace(/^\s{2}/, ''))
  }
  return collected.join('\n').trim()
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
    remoteReleaseNotes = parseYamlBlock(metadataText, 'releaseNotes')
    remoteReleaseMedia = parseReleaseMediaFromYaml(metadataText)
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
    throw new Error('尚未下载更新包，请先在更新面板确认下载')
  }
  try {
    if (beforeInstall) {
      await beforeInstall('manual')
    }
    appendUpdaterEvent('install_start', {})
    autoUpdater.quitAndInstall(false, true)
  } catch (error) {
    appendUpdaterEvent('install_failed', {
      message: error instanceof Error ? error.message : String(error),
    })
    throw error
  }
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
  lastUpdateEvent = null
  downloadInFlight = false
  downloadPromise = null
  remoteReleaseMedia = []
  remoteReleaseNotes = ''
  remoteBuildSha = ''
}

export { normalizeReleaseMedia, parseReleaseMediaFromYaml } from './release-media.js'
export type { ReleaseMediaSlide } from './release-media.js'
