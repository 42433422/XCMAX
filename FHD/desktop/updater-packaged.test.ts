import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const mocks = vi.hoisted(() => {
  const handlers = new Map<string, (...args: unknown[]) => void>()
  const autoUpdater = {
    autoDownload: true,
    autoInstallOnAppQuit: true,
    allowDowngrade: false,
    setFeedURL: vi.fn(),
    on: vi.fn((name: string, handler: (...args: unknown[]) => void) => {
      handlers.set(name, handler)
    }),
    checkForUpdates: vi.fn(() => Promise.resolve({})),
    downloadUpdate: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(),
    isUpdateAvailable: vi.fn(async (_info: { version: string }) => false),
    currentVersion: { version: '1.0.0' },
    isUpdateSupported: vi.fn(async () => true),
    isUserWithinRollout: vi.fn(async () => true),
    netSession: { setProxy: vi.fn(() => Promise.resolve()) },
  }
  return { autoUpdater, handlers, isPackaged: false }
})

vi.mock('electron-updater', () => ({ autoUpdater: mocks.autoUpdater }))

const tmpDir = path.join(os.tmpdir(), `xcagi-updater-pkg-${Date.now()}`)
fs.mkdirSync(tmpDir, { recursive: true })

vi.mock('electron', () => ({
  app: {
    get isPackaged() { return mocks.isPackaged },
    getVersion: () => '1.0.0',
    getPath: () => tmpDir,
  },
  BrowserWindow: vi.fn(),
  net: { request: vi.fn() },
  session: {
    defaultSession: {
      resolveProxy: vi.fn(async () => 'DIRECT'),
      setProxy: vi.fn(async () => undefined),
    },
  },
}))

const savedEnv: Record<string, string | undefined> = {}

beforeEach(() => {
  vi.resetModules()
  mocks.handlers.clear()
  mocks.isPackaged = false
  mocks.autoUpdater.on.mockClear()
  mocks.autoUpdater.checkForUpdates.mockClear()
  mocks.autoUpdater.downloadUpdate.mockReset()
  mocks.autoUpdater.downloadUpdate.mockResolvedValue(undefined)
  // installSameVersionRebuildHook 会用普通 async 函数替换 isUpdateAvailable，
  // 每个用例前恢复为全新 vi.fn，避免跨用例污染。
  mocks.autoUpdater.isUpdateAvailable = vi.fn(async (_info: { version: string }) => false)
  mocks.autoUpdater.isUserWithinRollout.mockResolvedValue(true)
  mocks.autoUpdater.checkForUpdates.mockResolvedValue({})
  vi.unstubAllEnvs()
  savedEnv.XCAGI_UPDATE_URL = process.env.XCAGI_UPDATE_URL
  savedEnv.XCAGI_UPDATE_ED25519_PUBLIC_KEY = process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  savedEnv.XCAGI_UPDATE_CHANNEL = process.env.XCAGI_UPDATE_CHANNEL
  savedEnv.XCAGI_PRODUCT_VERSION = process.env.XCAGI_PRODUCT_VERSION
  savedEnv.XCAGI_BUILD_SHA = process.env.XCAGI_BUILD_SHA
  savedEnv.XCAGI_BUILD_TIME = process.env.XCAGI_BUILD_TIME
  delete process.env.XCAGI_UPDATE_URL
  delete process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
  delete process.env.XCAGI_UPDATE_CHANNEL
  delete process.env.XCAGI_PRODUCT_VERSION
  delete process.env.XCAGI_BUILD_SHA
  delete process.env.XCAGI_BUILD_TIME
})

afterEach(() => {
  vi.unstubAllEnvs()
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

describe('updater — update checks', () => {
  it('skips development checks without a URL', async () => {
    const { runUpdateCheckWithDirectNet } = await import('./updater.js')
    await expect(runUpdateCheckWithDirectNet()).resolves.toMatchObject({ skipped: true })
    expect(mocks.autoUpdater.checkForUpdates).not.toHaveBeenCalled()
  })

  it('refuses packaged update checks before a signed provider is installed', async () => {
    mocks.isPackaged = true
    vi.stubEnv('XCAGI_UPDATE_URL', 'https://updates.example.com/')
    const { configureUpdater, runUpdateCheckWithDirectNet } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true } as never)
    await expect(runUpdateCheckWithDirectNet()).rejects.toThrow('尚未配置验签公钥')
    expect(mocks.autoUpdater.checkForUpdates).not.toHaveBeenCalled()
  })

  it('shares one update check and configures only the updater network session', async () => {
    vi.stubEnv('XCAGI_DESKTOP_TEST', '0')
    vi.stubEnv('XCAGI_UPDATE_URL', 'https://updates.example.com/')
    const { runUpdateCheckWithDirectNet } = await import('./updater.js')
    await Promise.all([runUpdateCheckWithDirectNet(), runUpdateCheckWithDirectNet()])
    expect(mocks.autoUpdater.netSession.setProxy).toHaveBeenCalledWith({ mode: 'direct' })
    expect(mocks.autoUpdater.checkForUpdates).toHaveBeenCalledOnce()
  })

  it('clears a previously available download if the next check fails', async () => {
    vi.stubEnv('XCAGI_UPDATE_URL', 'https://updates.example.com/')
    const { configureUpdater, downloadUpdate, runUpdateCheckWithDirectNet } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true } as never)
    mocks.handlers.get('update-available')?.({ version: '2.0.0', files: [] })
    mocks.autoUpdater.checkForUpdates.mockRejectedValueOnce(new Error('manifest signature failed'))
    await expect(runUpdateCheckWithDirectNet()).rejects.toThrow('manifest signature failed')
    await expect(downloadUpdate()).rejects.toThrow('请先检查更新')
    expect(mocks.autoUpdater.downloadUpdate).not.toHaveBeenCalled()
  })

  it('reads product identity and release notes from the updater events', async () => {
    const send = vi.fn()
    const { configureUpdater, getDownloadedUpdateState } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send } } as never)
    const info = { version: '3.0.0', productVersion: '3.0.0.7', buildSha: 'abc123', releaseNotes: '修复了若干问题' }
    mocks.handlers.get('update-available')?.(info)
    expect(send).toHaveBeenCalledWith('xcagi:update-event', { type: 'update-available', data: { ...info, releaseMedia: [] } })
    mocks.handlers.get('update-downloaded')?.(info)
    expect(getDownloadedUpdateState()).toEqual({ downloaded: true, version: '3.0.0.7', buildSha: 'abc123' })
  })

  it('honors the upstream rollout for same-version rebuilds and refuses older versions', async () => {
    vi.stubEnv('XCAGI_UPDATE_URL', 'https://updates.example.com/')
    vi.stubEnv('XCAGI_UPDATE_ED25519_PUBLIC_KEY', 'test-key')
    vi.stubEnv('XCAGI_BUILD_SHA', 'old')
    vi.stubEnv('XCAGI_BUILD_TIME', '2026-11-01T00:00:00Z')
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true } as never)
    const info = {
      version: '1.0.0', path: 'update.zip', buildSha: 'new', releaseDate: '2026-11-18T00:00:00Z',
    }
    mocks.autoUpdater.isUserWithinRollout.mockResolvedValueOnce(false)
    await expect(mocks.autoUpdater.isUpdateAvailable(info)).resolves.toBe(false)
    await expect(mocks.autoUpdater.isUpdateAvailable(info)).resolves.toBe(true)
    await expect(mocks.autoUpdater.isUpdateAvailable({ ...info, version: '0.9.0' })).resolves.toBe(false)
  })
})

describe('updater — downloadUpdate error mapping', () => {
  it('maps ZIP-not-provided error to user-friendly message', async () => {
    const { configureUpdater, downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)

    mocks.handlers.get('update-available')?.({ version: '2.0.0', files: [] })
    mocks.autoUpdater.downloadUpdate.mockRejectedValueOnce(new Error('ZIP file not provided for auto update'))
    await expect(downloadUpdate()).rejects.toThrow(/无法在应用内自动更新/)
  })

  it('returns alreadyDownloaded when update already downloaded', async () => {
    const { configureUpdater, downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)

    const handler = mocks.handlers.get('update-downloaded')
    handler?.({ version: '2.0.0', buildSha: '', files: [] })

    const result = await downloadUpdate()
    expect(result).toEqual({ alreadyDownloaded: true })
  })
})

describe('updater — force upgrade version comparison', () => {
  it('requires a forced update only after an eligible update is available', async () => {
    vi.stubEnv('XCAGI_PRODUCT_VERSION', '1.0.0.0')
    const { configureUpdater, isForceUpgradeRequired } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true } as never)
    expect(isForceUpgradeRequired()).toBe(false)
    const info = { version: '2.0.0', minVersion: '1.0.0.1' }
    mocks.handlers.get('update-available')?.({ ...info, forceUpgrade: false })
    expect(isForceUpgradeRequired()).toBe(false)
    mocks.handlers.get('update-available')?.({ ...info, forceUpgrade: true })
    expect(isForceUpgradeRequired()).toBe(true)
  })
})

describe('updater — configureUpdater event wiring', () => {
  it('registers all expected event handlers', async () => {
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)

    const registeredEvents = mocks.autoUpdater.on.mock.calls.map(c => c[0])
    expect(registeredEvents).toContain('checking-for-update')
    expect(registeredEvents).toContain('update-available')
    expect(registeredEvents).toContain('update-not-available')
    expect(registeredEvents).toContain('download-progress')
    expect(registeredEvents).toContain('update-downloaded')
    expect(registeredEvents).toContain('error')
  })

  it('sets autoDownload and autoInstallOnAppQuit to false', async () => {
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)
    expect(mocks.autoUpdater.autoDownload).toBe(false)
    expect(mocks.autoUpdater.autoInstallOnAppQuit).toBe(false)
  })

  it('sends update event to renderer via webContents', async () => {
    const send = vi.fn()
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send } } as never)

    const handler = mocks.handlers.get('update-available')
    handler?.({ version: '2.0.0', files: [] })
    expect(send).toHaveBeenCalledWith('xcagi:update-event', expect.objectContaining({ type: 'update-available' }))
  })

  it('does not send to destroyed window', async () => {
    const send = vi.fn()
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true, webContents: { send } } as never)

    const handler = mocks.handlers.get('update-available')
    handler?.({ version: '2.0.0', files: [] })
    expect(send).not.toHaveBeenCalled()
  })

  it('sets feed URL with channel when XCAGI_UPDATE_CHANNEL is set', async () => {
    process.env.XCAGI_UPDATE_URL = 'http://127.0.0.1:19999/releases/'
    process.env.XCAGI_UPDATE_CHANNEL = 'beta'
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = 'test-key'
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)
    expect(mocks.autoUpdater.setFeedURL).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'custom', url: 'http://127.0.0.1:19999/releases/', channel: 'beta', updateProvider: expect.any(Function) }),
    )
  })
})

describe('updater — installUpdate without download', () => {
  it('throws when no update downloaded', async () => {
    const { installUpdate } = await import('./desktop-install-update.js')
    const { __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()
    await expect(installUpdate()).rejects.toThrow(/尚未下载更新包/)
  })
})
