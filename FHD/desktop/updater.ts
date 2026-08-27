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
import { discardPendingUpdateInstallReceipt, stageUpdateInstallReceipt } from './update-install-receipts.js'

let updateDownloaded = false
let downloadedVersion = ''
let downloadedBuildSha = ''
let remoteBuildSha = ''
let remoteReleaseDate = ''
let remoteReleaseNotes = ''
let remoteReleaseMedia: ReleaseMediaSlide[] = []
let remoteMinVersion = ''
let remoteForceUpgrade = false
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

function buildInfoCandidates(): string[] {
  if (!app.isPackaged) {
    return []
  }
  return [
    path.join(process.resourcesPath, 'build-info.json'),
    path.join(process.resourcesPath, 'backend', 'build-info.json'),
  ]
}

/** 远程更新元数据中的最低兼容版本（低于此版本必须强制更新）。 */
export function getRemoteMinVersion(): string {
  return remoteMinVersion
}

/** 远程更新元数据标记了强制升级。 */
export function isForceUpgradeEnabled(): boolean {
  return remoteForceUpgrade
}

/** Product version is four-part and comes from signed build metadata, not npm SemVer. */
export function readLocalProductVersion(): string {
  const fromEnv = String(process.env.XCAGI_PRODUCT_VERSION || '').trim()
  if (fromEnv) return fromEnv
  for (const filePath of buildInfoCandidates()) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as { version?: string }
      const version = String(raw.version || '').trim()
      if (version) return version
    } catch {
      /* try next */
    }
  }
  return app.getVersion()
}

/** 当前版本是否低于最低兼容版本，需要强制升级。 */
export function isCurrentBelowMinVersion(): boolean {
  if (!remoteMinVersion) return false
  try {
    return compareVersions(readLocalProductVersion(), remoteMinVersion) < 0
  } catch {
    return false
  }
}

/**
 * 4 段式版本号比较（如 1.0.0.1 vs 1.0.0.0）。
 * 支持 2-4 段，缺失段视为 0。
 */
export function compareVersions(a: string, b: string): number {
  const parse = (value: string): number[] => {
    const normalized = String(value || '').trim()
    if (!/^\d+(?:\.\d+){1,3}$/.test(normalized)) {
      throw new Error(`invalid version: ${normalized || '<empty>'}`)
    }
    return normalized.split('.').map(part => Number.parseInt(part, 10))
  }
  const partsA = parse(a)
  const partsB = parse(b)
  const len = Math.max(partsA.length, partsB.length)
  for (let i = 0; i < len; i++) {
    const va = partsA[i] ?? 0
    const vb = partsB[i] ?? 0
    if (va !== vb) return va - vb
  }
  return 0
}

/** 当前 Electron 版本是否低于最低兼容版本（需要强制升级）。 */
export function isForceUpgradeRequired(): boolean {
  return remoteForceUpgrade && isCurrentBelowMinVersion()
}

export function readLocalBuildSha(): string {
  if (!app.isPackaged) {
    return String(process.env.XCAGI_BUILD_SHA || '').trim()
  }
  for (const filePath of buildInfoCandidates()) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as {
        gitSha?: string
        buildSha?: string
        builtAt?: string
      }
      const sha = String(raw.gitSha || raw.buildSha || '').trim()
      if (sha) return sha
    } catch {
      /* try next */
    }
  }
  return ''
}

/** Local package time for same-version rebuild ordering (builtAt, else build-info mtime). */
export function readLocalBuildTimeMs(): number {
  if (!app.isPackaged) {
    const fromEnv = Date.parse(String(process.env.XCAGI_BUILD_TIME || '').trim())
    return Number.isFinite(fromEnv) ? fromEnv : 0
  }
  for (const filePath of buildInfoCandidates()) {
    try {
      if (!fs.existsSync(filePath)) continue
      const raw = JSON.parse(fs.readFileSync(filePath, 'utf8')) as { builtAt?: string }
      const builtAt = Date.parse(String(raw.builtAt || '').trim())
      if (Number.isFinite(builtAt) && builtAt > 0) return builtAt
      const mtimeMs = fs.statSync(filePath).mtimeMs
      if (Number.isFinite(mtimeMs) && mtimeMs > 0) return mtimeMs
    } catch {
      /* try next */
    }
  }
  return 0
}

/**
 * Same Electron semver may ship multiple rebuilds. Only treat remote as an update when
 * buildSha differs AND remote releaseDate is strictly newer than the local package time.
 * SHA mismatch alone used to roll newer local/dev builds back to a stale CDN package.
 */
export function isSameVersionRebuildNewer(input: {
  remoteSha: string
  localSha: string
  remoteReleaseDate: string
  localBuildTimeMs: number
}): boolean {
  const remoteSha = String(input.remoteSha || '').trim()
  const localSha = String(input.localSha || '').trim()
  if (!remoteSha || !localSha || remoteSha === localSha) return false
  const remoteMs = Date.parse(String(input.remoteReleaseDate || '').trim())
  const localMs = Number(input.localBuildTimeMs) || 0
  if (!Number.isFinite(remoteMs) || remoteMs <= 0 || localMs <= 0) return false
  return remoteMs > localMs
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
  // 注意：新版 electron-updater 的 isUpdateAvailable 是 async，必须 await。
  // 若把 Promise 对象当布尔值，Promise 恒为 truthy → 同版本也会永远「可更新」。
  const updater = autoUpdater as unknown as {
    isUpdateAvailable?: (updateInfo: UpdateInfo) => boolean | Promise<boolean>
  }
  const original = updater.isUpdateAvailable?.bind(autoUpdater)
  updater.isUpdateAvailable = async (updateInfo: UpdateInfo) => {
    // macOS auto-update must use a ZIP artifact; DMG-only feeds are not installable.
    if (process.platform === 'darwin' && !updateInfoHasMacZip(updateInfo)) {
      return false
    }
    const remoteSha = String(
      (updateInfo as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || ''
    ).trim()
    const localSha = readLocalBuildSha()
    // 同一 Git 构建已装在本机：绝不再提示自更新。
    if (remoteSha && localSha && remoteSha === localSha) {
      return false
    }
    if (original && (await original(updateInfo))) {
      return true
    }
    const releaseDate = String(
      (updateInfo as UpdateInfo & { releaseDate?: string }).releaseDate || remoteReleaseDate || ''
    ).trim()
    return isSameVersionRebuildNewer({
      remoteSha,
      localSha,
      remoteReleaseDate: releaseDate,
      localBuildTimeMs: readLocalBuildTimeMs(),
    })
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
export function configureUpdater(
  mainWindow: BrowserWindow,
  options: { onForceUpgradeRequired?: () => void | Promise<void> } = {},
): void {
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = false
  ;(autoUpdater as unknown as { allowDowngrade?: boolean }).allowDowngrade = false
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
    } else if (
      type === 'error'
      && (
        lastUpdateEvent?.type === 'update-available'
        || lastUpdateEvent?.type === 'update-available-with-error'
      )
    ) {
      // 当前页面收到 error；刷新后的页面通过显式事件恢复“有更新但检查报错”的状态。
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
    downloadedVersion = String(info.version || '').trim()
    downloadedBuildSha = String(
      (info as UpdateInfo & { buildSha?: string }).buildSha || remoteBuildSha || '',
    ).trim()
    downloadInFlight = false
    appendUpdaterEvent('update_downloaded', { version: info.version })
    send('update-downloaded', enrichUpdateInfo(info))
  })
  autoUpdater.on('error', error => {
    downloadInFlight = false
    send('error', { message: error.message, stack: error.stack, phase: 'updater' })
    appendUpdaterEvent('error', { message: error.message, stack: error.stack })
  })

  const checkAndNotify = async () => {
    try {
      await runUpdateCheckWithDirectNet()
      if (isForceUpgradeRequired()) {
        await options.onForceUpgradeRequired?.()
      }
    } catch (error) {
      send('error', { message: error instanceof Error ? error.message : String(error) })
    }
  }

  setTimeout(() => void checkAndNotify(), 60_000)

  setInterval(() => {
    if (!app.isPackaged && !process.env.XCAGI_UPDATE_URL) {
      return
    }
    void checkAndNotify()
  }, 6 * 60 * 60 * 1000)
}

export async function downloadUpdate(): Promise<unknown> {
  if (updateDownloaded) {
    return { alreadyDownloaded: true }
  }
  if (downloadPromise) {
    return downloadPromise
  }
  downloadInFlight = true
  appendUpdaterEvent('download_start', {})
  downloadPromise = (async () => {
    try {
      return await autoUpdater.downloadUpdate()
    } catch (error) {
      updateDownloaded = false
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
    remoteReleaseDate = parseYamlField(metadataText, 'releaseDate').replace(/^['"]|['"]$/g, '')
    remoteReleaseNotes = parseYamlBlock(metadataText, 'releaseNotes')
    remoteReleaseMedia = parseReleaseMediaFromYaml(metadataText)
    remoteMinVersion = parseYamlField(metadataText, 'minVersion').replace(/^['"]|['"]$/g, '')
    remoteForceUpgrade = String(parseYamlField(metadataText, 'forceUpgrade') || '').trim().toLowerCase() === 'true'
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

export async function installUpdate(
  beforeInstall?: (toVersion: string) => Promise<void>,
  onInstallFailed?: () => Promise<void> | void,
): Promise<void> {
  if (!updateDownloaded) {
    throw new Error('尚未下载更新包，请先在更新面板确认下载')
  }
  try {
    if (beforeInstall) {
      const version = downloadedVersion || 'unknown'
      const identity = downloadedBuildSha ? `${version}+${downloadedBuildSha.slice(0, 12)}` : version
      await beforeInstall(identity)
    }
    stageUpdateInstallReceipt({ targetVersion: downloadedVersion || 'unknown', targetBuildSha: downloadedBuildSha, channel: process.env.XCAGI_UPDATE_CHANNEL })
    appendUpdaterEvent('install_start', {})
    autoUpdater.quitAndInstall(false, true)
  } catch (error) {
    discardPendingUpdateInstallReceipt()
    let cleanupError: unknown
    try {
      await onInstallFailed?.()
    } catch (caught) {
      cleanupError = caught
    }
    appendUpdaterEvent('install_failed', {
      message: error instanceof Error ? error.message : String(error),
      cleanupError: cleanupError instanceof Error ? cleanupError.message : String(cleanupError || ''),
    })
    if (cleanupError) {
      throw new Error(
        `${error instanceof Error ? error.message : String(error)}；清理回滚准备失败：${
          cleanupError instanceof Error ? cleanupError.message : String(cleanupError)
        }`,
      )
    }
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
  discardPendingUpdateInstallReceipt()
  updateDownloaded = false
  downloadedVersion = ''
  downloadedBuildSha = ''
  lastUpdateEvent = null
  downloadInFlight = false
  downloadPromise = null
  remoteReleaseMedia = []
  remoteReleaseNotes = ''
  remoteBuildSha = ''
  remoteReleaseDate = ''
  remoteMinVersion = ''
  remoteForceUpgrade = false
}

export { normalizeReleaseMedia, parseReleaseMediaFromYaml } from './release-media.js'
export type { ReleaseMediaSlide } from './release-media.js'
