import { BrowserWindow, app } from 'electron'
import { autoUpdater } from 'electron-updater'
import type { UpdateInfo } from 'electron-updater'
import { isDesktopPackaged } from './desktop-config'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import {
  normalizeReleaseMedia,
} from './release-media.js'
import { appendUpdaterEvent, discardPendingUpdateInstallReceipt } from './update-install-receipts.js'
import { installResumableUpdaterDownload } from './resumable-download.js'
import { SignedUpdateProvider } from './signed-update-provider.js'

let updateDownloaded = false
let downloadedVersion = ''
let downloadedBuildSha = ''
type ProductUpdateInfo = UpdateInfo & {
  productVersion?: string
  buildSha?: string
  releaseMedia?: unknown
  minVersion?: string
  forceUpgrade?: boolean
}

let availableUpdate: ProductUpdateInfo | null = null
let rebuildHookInstalled = false
let signedFeedConfigured = false
let updaterNetSessionReady: Promise<typeof autoUpdater.netSession> | null = null
let checkPromise: Promise<unknown> | null = null
let downloadPromise: Promise<unknown> | null = null
/** 最近一次可展示给渲染进程的更新事件（刷新页面后可重放）。 */
let lastUpdateEvent: { type: string; data?: unknown } | null = null

export function ensureUpdaterNetSession(): Promise<typeof autoUpdater.netSession> {
  if (!updaterNetSessionReady) {
    const updaterSession = autoUpdater.netSession
    updaterNetSessionReady = updaterSession.setProxy({ mode: 'direct' }).then(() => updaterSession, error => {
      updaterNetSessionReady = null
      throw error
    })
  }
  return updaterNetSessionReady
}

export function isUpdateDownloaded(): boolean {
  return updateDownloaded
}

/** 已下载更新的只读快照，供 installUpdate（desktop-install-update.ts）执行安装。 */
export function getDownloadedUpdateState(): {
  downloaded: boolean
  version: string
  buildSha: string
} {
  return {
    downloaded: updateDownloaded,
    version: downloadedVersion,
    buildSha: downloadedBuildSha,
  }
}

/** 渲染进程挂载时拉取，避免 update-available 发生在订阅前或页面刷新后丢失角标。 */
export function getUpdateStatus(): { type: string; data?: unknown } | null {
  return lastUpdateEvent
}

function buildInfoCandidates(): string[] {
  if (!isDesktopPackaged()) {
    return []
  }
  return [
    path.join(process.resourcesPath, 'build-info.json'),
    path.join(process.resourcesPath, 'backend', 'build-info.json'),
  ]
}

/** 远程更新元数据中的最低兼容版本（低于此版本必须强制更新）。 */
export function getRemoteMinVersion(): string {
  return String(availableUpdate?.minVersion || '').trim()
}

/** 远程更新元数据标记了强制升级。 */
export function isForceUpgradeEnabled(): boolean {
  return availableUpdate?.forceUpgrade === true
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
  const minVersion = getRemoteMinVersion()
  if (!minVersion) return false
  try {
    return compareVersions(readLocalProductVersion(), minVersion) < 0
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
  return isForceUpgradeEnabled() && isCurrentBelowMinVersion()
}

export function readLocalBuildSha(): string {
  if (!isDesktopPackaged()) {
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
  if (!isDesktopPackaged()) {
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
    const remoteSha = String((updateInfo as ProductUpdateInfo).buildSha || '').trim()
    const localSha = readLocalBuildSha()
    if (remoteSha && localSha && remoteSha === localSha) {
      return false
    }
    if (original && (await original(updateInfo))) {
      return true
    }
    // The upstream check short-circuits equal SemVer before evaluating OS support and rollout.
    if (updateInfo.version !== autoUpdater.currentVersion.version
        || !(await autoUpdater.isUpdateSupported(updateInfo))
        || !(await autoUpdater.isUserWithinRollout(updateInfo))) {
      return false
    }
    return isSameVersionRebuildNewer({
      remoteSha,
      localSha,
      remoteReleaseDate: updateInfo.releaseDate,
      localBuildTimeMs: readLocalBuildTimeMs(),
    })
  }
}

function updateInfoHasMacZip(updateInfo: UpdateInfo): boolean {
  const files = updateInfo.files?.length ? updateInfo.files : [{ url: updateInfo.path }]
  return files.some(file => /\.zip(?:[?#]|$)/i.test(file.url))
}

function enrichUpdateInfo(info: ProductUpdateInfo) {
  return {
    ...info,
    productVersion: String(info.productVersion || info.version).trim(),
    buildSha: String(info.buildSha || '').trim(),
    releaseMedia: normalizeReleaseMedia(info.releaseMedia),
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
  autoUpdater.allowDowngrade = false
  installResumableUpdaterDownload()

  const url = process.env.XCAGI_UPDATE_URL
  const publicKey = process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  const channel = process.env.XCAGI_UPDATE_CHANNEL?.trim() || undefined
  if (url && publicKey) {
    autoUpdater.setFeedURL({
      provider: 'custom',
      updateProvider: SignedUpdateProvider,
      url,
      channel,
      publicKey,
    })
    signedFeedConfigured = true
    installSameVersionRebuildHook()
  } else if (url && !isDesktopPackaged()) {
    autoUpdater.setFeedURL({ provider: 'generic', url, channel })
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
    availableUpdate = info
    appendUpdaterEvent('update_available', { version: info.version })
    send('update-available', enrichUpdateInfo(info))
  })
  autoUpdater.on('update-not-available', info => send('update-not-available', info))
  autoUpdater.on('download-progress', progress => send('download-progress', progress))
  autoUpdater.on('update-downloaded', info => {
    const update = enrichUpdateInfo(info)
    updateDownloaded = true
    downloadedVersion = update.productVersion
    downloadedBuildSha = update.buildSha
    appendUpdaterEvent('update_downloaded', { version: info.version })
    send('update-downloaded', update)
  })
  autoUpdater.on('error', error => {
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
    if (!isDesktopPackaged() && !process.env.XCAGI_UPDATE_URL) {
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
  if (!availableUpdate || checkPromise) {
    throw new Error('请先检查更新，确认有可下载的版本')
  }
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
    }
  })().finally(() => {
    downloadPromise = null
  })
  return downloadPromise
}

export async function runUpdateCheckWithDirectNet(): Promise<unknown> {
  if (downloadPromise || updateDownloaded) {
    return { skipped: true, reason: 'update-already-downloading-or-downloaded' }
  }
  if (!process.env.XCAGI_UPDATE_URL) {
    if (!isDesktopPackaged()) {
      return { skipped: true, reason: 'dev-mode-without-XCAGI_UPDATE_URL' }
    }
    throw new Error('缺少桌面更新源配置')
  }
  if (isDesktopPackaged() && !signedFeedConfigured) {
    throw new Error('桌面更新源尚未配置验签公钥')
  }
  checkPromise ??= (async () => {
    availableUpdate = null
    if (process.env.XCAGI_DESKTOP_TEST !== '1') {
      await ensureUpdaterNetSession()
    }
    return autoUpdater.checkForUpdates()
  })().finally(() => {
    checkPromise = null
  })
  return checkPromise
}

/** 测试辅助：重置 updateDownloaded 状态。仅用于单测。 */
export function __resetUpdateDownloadedForTest(): void {
  discardPendingUpdateInstallReceipt()
  updateDownloaded = false
  downloadedVersion = ''
  downloadedBuildSha = ''
  lastUpdateEvent = null
  availableUpdate = null
  checkPromise = null
  downloadPromise = null
}

export { normalizeReleaseMedia, parseReleaseMediaFromYaml } from './release-media.js'
export type { ReleaseMediaSlide } from './release-media.js'
