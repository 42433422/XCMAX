import { describe, it, expect, beforeEach, vi } from 'vitest'

const updaterMocks = vi.hoisted(() => ({
  autoUpdater: {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    setFeedURL: vi.fn(),
    on: vi.fn(),
    checkForUpdates: vi.fn(() => Promise.resolve({})),
    downloadUpdate: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(),
  },
}))

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
    getVersion: () => '1.0.0',
    getPath: () => '/tmp',
  },
  BrowserWindow: vi.fn(),
  net: { request: vi.fn() },
  session: {
    defaultSession: {
      resolveProxy: vi.fn(() => Promise.resolve('DIRECT')),
      setProxy: vi.fn(() => Promise.resolve()),
    },
  },
}))

vi.mock('electron-updater', () => ({ autoUpdater: updaterMocks.autoUpdater }))

describe('updater — same-version rebuild ordering', () => {
  it('rejects SHA mismatch when remote releaseDate is older than local package', async () => {
    const { isSameVersionRebuildNewer } = await import('./updater.js')
    expect(
      isSameVersionRebuildNewer({
        remoteSha: 'a'.repeat(40),
        localSha: 'b'.repeat(40),
        remoteReleaseDate: '2026-07-13T15:04:08.075Z',
        localBuildTimeMs: Date.parse('2026-07-23T00:00:00.000Z'),
      }),
    ).toBe(false)
  })

  it('accepts SHA mismatch when remote releaseDate is newer than local package', async () => {
    const { isSameVersionRebuildNewer } = await import('./updater.js')
    expect(
      isSameVersionRebuildNewer({
        remoteSha: 'a'.repeat(40),
        localSha: 'b'.repeat(40),
        remoteReleaseDate: '2026-07-23T12:00:00.000Z',
        localBuildTimeMs: Date.parse('2026-07-13T15:04:08.075Z'),
      }),
    ).toBe(true)
  })

  it('rejects SHA mismatch when releaseDate or local time is missing', async () => {
    const { isSameVersionRebuildNewer } = await import('./updater.js')
    expect(
      isSameVersionRebuildNewer({
        remoteSha: 'a'.repeat(40),
        localSha: 'b'.repeat(40),
        remoteReleaseDate: '',
        localBuildTimeMs: Date.parse('2026-07-13T15:04:08.075Z'),
      }),
    ).toBe(false)
  })

  it('rejects identical buildSha even when remote releaseDate is newer', async () => {
    const { isSameVersionRebuildNewer } = await import('./updater.js')
    const sha = 'c'.repeat(40)
    expect(
      isSameVersionRebuildNewer({
        remoteSha: sha,
        localSha: sha,
        remoteReleaseDate: '2026-07-24T09:31:21.167Z',
        localBuildTimeMs: Date.parse('2026-07-24T09:26:33.083Z'),
      }),
    ).toBe(false)
  })
})

describe('updater — forced-upgrade product versions', () => {
  it('compares three- and four-part versions without conflating npm SemVer', async () => {
    const { compareVersions } = await import('./updater.js')
    expect(compareVersions('1.0.0.0', '1.0.0.1')).toBeLessThan(0)
    expect(compareVersions('1.0.1', '1.0.0.9')).toBeGreaterThan(0)
    expect(compareVersions('1.0', '1.0.0.0')).toBe(0)
  })

  it('rejects malformed minimum versions instead of treating them as zero', async () => {
    const { compareVersions } = await import('./updater.js')
    expect(() => compareVersions('1.0.0.0', "'1.0.0.1'")).toThrow(/invalid version/)
  })

  it('prefers the explicit product-version environment over Electron SemVer', async () => {
    const saved = process.env.XCAGI_PRODUCT_VERSION
    process.env.XCAGI_PRODUCT_VERSION = '1.0.0.7'
    const { readLocalProductVersion } = await import('./updater.js')
    expect(readLocalProductVersion()).toBe('1.0.0.7')
    if (saved === undefined) delete process.env.XCAGI_PRODUCT_VERSION
    else process.env.XCAGI_PRODUCT_VERSION = saved
  })
})

describe('updater — downloadUpdate is explicit', () => {
  it('exports downloadUpdate for user-triggered installs', async () => {
    const mod = await import('./updater.js')
    expect(typeof mod.downloadUpdate).toBe('function')
    expect(typeof mod.configureUpdater).toBe('function')
    expect(typeof mod.getUpdateStatus).toBe('function')
    expect(mod.getUpdateStatus()).toBeNull()
  })
})

describe('updater — __resetUpdateDownloadedForTest', () => {
  it('can be called without error', async () => {
    const { __resetUpdateDownloadedForTest } = await import('./updater.js')
    expect(() => __resetUpdateDownloadedForTest()).not.toThrow()
  })
})

describe('updater — concurrent download requests', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('shares one in-flight updater promise', async () => {
    let finish: (() => void) | undefined
    updaterMocks.autoUpdater.downloadUpdate = vi.fn(
      () => new Promise<void>(resolve => {
        finish = resolve
      }),
    )
    updaterMocks.autoUpdater.on = vi.fn()
    const { configureUpdater, downloadUpdate } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => true } as never)
    updaterMocks.autoUpdater.on.mock.calls.find(call => call[0] === 'update-available')?.[1]({
      version: '2.0.0',
    })

    const first = downloadUpdate()
    const second = downloadUpdate()
    finish?.()
    await Promise.all([first, second])

    expect(updaterMocks.autoUpdater.downloadUpdate).toHaveBeenCalledTimes(1)
  })
})

describe('updater — available update error replay', () => {
  it('persists an explicit available-with-error state for refreshed renderers', async () => {
    vi.resetModules()
    updaterMocks.autoUpdater.on = vi.fn()
    const { configureUpdater, getUpdateStatus, __resetUpdateDownloadedForTest } = await import(
      './updater.js'
    )
    __resetUpdateDownloadedForTest()
    const mainWindow = {
      isDestroyed: () => false,
      webContents: { send: vi.fn() },
    }

    configureUpdater(mainWindow as never)
    const available = updaterMocks.autoUpdater.on.mock.calls.find(
      call => call[0] === 'update-available',
    )?.[1] as ((value: { version: string }) => void) | undefined
    const error = updaterMocks.autoUpdater.on.mock.calls.find(
      call => call[0] === 'error',
    )?.[1] as ((value: Error) => void) | undefined

    available?.({ version: '1.0.1' })
    error?.(new Error('network error'))
    error?.(new Error('retry failed'))

    expect(getUpdateStatus()?.type).toBe('update-available-with-error')
    expect(
      (getUpdateStatus()?.data as { lastError?: { message?: string } }).lastError?.message,
    ).toBe('retry failed')
  })
})
