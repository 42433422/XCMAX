import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

/**
 * updater.ts 打包模式 / 元数据解析 / 强制升级 / 网络会话等未覆盖路径的补充单测。
 * 与 updater.test.ts（签名校验/同版本排序）和 updater-install.test.ts（安装回滚契约）互补。
 */

const keyPair = crypto.generateKeyPairSync('ed25519')
const TEST_PUBLIC_KEY_PEM = keyPair.publicKey.export({ type: 'spki', format: 'pem' }).toString()
const TEST_PRIVATE_KEY_PEM = keyPair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()

function signBody(body: string): string {
  const privateKey = crypto.createPrivateKey(TEST_PRIVATE_KEY_PEM)
  const sig = crypto.sign(null, Buffer.from(body, 'utf8'), privateKey)
  return `signature: ed25519:${sig.toString('base64')}`
}

function buildMetadata(version: string, extra = ''): string {
  const body = `version: ${version}
files:
  - url: XCAGI-${version}-mac.zip
    sha512: fake-sha512
    size: 12345
path: XCAGI-${version}-mac.zip
sha512: fake-sha512
releaseDate: '2026-08-23T00:00:00.000Z'
buildSha: ${'a'.repeat(40)}${extra}`
  return `${body}\n${signBody(body)}`
}

// --- mocks ---
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
    isUpdateAvailable: vi.fn(async () => true),
    netSession: { setProxy: vi.fn(() => Promise.resolve()) },
  }
  return { autoUpdater, handlers }
})

vi.mock('electron-updater', () => ({ autoUpdater: mocks.autoUpdater }))

const tmpDir = path.join(os.tmpdir(), `xcagi-updater-pkg-${Date.now()}`)
fs.mkdirSync(tmpDir, { recursive: true })

vi.mock('electron', () => ({
  app: {
    isPackaged: false,
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

/** 构造一个可控的 net.request 伪对象（EventEmitter 语义）。 */
function makeNetRequest(response: {
  statusCode: number
  statusMessage?: string
  body?: string
  emitError?: Error
  requestError?: Error
}) {
  return () => {
    const events = require('node:events') as typeof import('node:events')
    const req = new events.EventEmitter() as import('node:events').EventEmitter & { end: () => void }
    const res = new events.EventEmitter() as import('node:events').EventEmitter & {
      statusCode?: number
      statusMessage?: string
    }
    req.end = () => {
      process.nextTick(() => {
        if (response.requestError) {
          req.emit('error', response.requestError)
          return
        }
        res.statusCode = response.statusCode
        res.statusMessage = response.statusMessage
        req.emit('response', res)
        if (response.emitError) {
          res.emit('error', response.emitError)
          return
        }
        if (response.body !== undefined) {
          res.emit('data', Buffer.from(response.body))
        }
        res.emit('end')
      })
    }
    return req
  }
}

const savedEnv: Record<string, string | undefined> = {}

beforeEach(() => {
  vi.resetModules()
  mocks.handlers.clear()
  mocks.autoUpdater.on.mockClear()
  mocks.autoUpdater.checkForUpdates.mockClear()
  mocks.autoUpdater.downloadUpdate.mockReset()
  mocks.autoUpdater.downloadUpdate.mockResolvedValue(undefined)
  // installSameVersionRebuildHook 会用普通 async 函数替换 isUpdateAvailable，
  // 每个用例前恢复为全新 vi.fn，避免跨用例污染。
  mocks.autoUpdater.isUpdateAvailable = vi.fn(async () => true)
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
  for (const [key, value] of Object.entries(savedEnv)) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
})

describe('updater — checkForUpdates with metadata parsing', () => {
  it('fetches and parses metadata when env configured (dev mode with URL)', async () => {
    process.env.XCAGI_UPDATE_URL = 'http://127.0.0.1:19999/releases/'
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    const metadata = buildMetadata('2.0.0', '\nminVersion: 1.0.0.0\nforceUpgrade: true')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => metadata,
    } as Response)

    const { checkForUpdates, getRemoteMinVersion, isForceUpgradeEnabled } = await import('./updater.js')
    await checkForUpdates()

    expect(getRemoteMinVersion()).toBe('1.0.0.0')
    expect(isForceUpgradeEnabled()).toBe(true)
    expect(mocks.autoUpdater.checkForUpdates).toHaveBeenCalledOnce()
    fetchSpy.mockRestore()
  })

  it('skips metadata fetch when env not configured', async () => {
    const { checkForUpdates } = await import('./updater.js')
    const result = await checkForUpdates()
    expect(result).toEqual({ skipped: true, reason: 'dev-mode-without-XCAGI_UPDATE_URL' })
  })

  it('parses releaseNotes block scalar and enriches update-available payload', async () => {
    process.env.XCAGI_UPDATE_URL = 'http://127.0.0.1:19999/releases/'
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    const body = `version: 3.0.0
productVersion: 3.0.0.7
releaseNotes: |
  - 修复了若干问题
  - 新增功能
path: XCAGI-3.0.0-mac.zip
sha512: fake
releaseDate: '2026-08-23T00:00:00.000Z'`
    const metadata = `${body}\n${signBody(body)}`
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => metadata,
    } as Response)

    const send = vi.fn()
    const { configureUpdater, checkForUpdates } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send } } as never)
    await checkForUpdates()

    // 触发 update-available：enrichUpdateInfo 应把解析出的 releaseNotes 附带进事件
    const handler = mocks.handlers.get('update-available')
    handler?.({ version: '3.0.0', files: [] })
    const payload = send.mock.calls.find(c => c[0] === 'xcagi:update-event')?.[1] as {
      data?: { productVersion?: string; releaseNotes?: string }
    }
    expect(payload?.data?.productVersion).toBe('3.0.0.7')
    expect(payload?.data?.releaseNotes).toContain('修复了若干问题')
    fetchSpy.mockRestore()
  })
})

/** vi.mock 替换后的 defaultSession（真实类型为 electron.Session，须经 unknown 中转）。 */
type MockedDefaultSession = {
  resolveProxy: ReturnType<typeof vi.fn>
  setProxy: ReturnType<typeof vi.fn>
}

async function mockedDefaultSession(): Promise<MockedDefaultSession> {
  const { session } = await import('electron')
  return session.defaultSession as unknown as MockedDefaultSession
}

describe('updater — runUpdateCheckWithDirectNet proxy handling', () => {
  it('restores system proxy when previous was PROXY', async () => {
    const defaultSession = await mockedDefaultSession()
    defaultSession.resolveProxy.mockResolvedValue('PROXY 127.0.0.1:8080')

    const { runUpdateCheckWithDirectNet } = await import('./updater.js')
    await runUpdateCheckWithDirectNet()

    // 先设 direct，检查完后恢复 system
    const calls = defaultSession.setProxy.mock.calls.map(c => c[0])
    expect(calls).toContainEqual({ mode: 'direct' })
    expect(calls[calls.length - 1]).toEqual({ mode: 'system' })
  })

  it('keeps direct when previous was DIRECT', async () => {
    const defaultSession = await mockedDefaultSession()
    defaultSession.resolveProxy.mockResolvedValue('DIRECT')

    const { runUpdateCheckWithDirectNet } = await import('./updater.js')
    await runUpdateCheckWithDirectNet()

    const calls = defaultSession.setProxy.mock.calls.map(c => c[0])
    expect(calls[calls.length - 1]).toEqual({ mode: 'direct' })
  })

  it('restores system proxy when previous was SOCKS', async () => {
    const defaultSession = await mockedDefaultSession()
    defaultSession.resolveProxy.mockResolvedValue('SOCKS5 127.0.0.1:1080')

    const { runUpdateCheckWithDirectNet } = await import('./updater.js')
    await runUpdateCheckWithDirectNet()

    const calls = defaultSession.setProxy.mock.calls.map(c => c[0])
    expect(calls[calls.length - 1]).toEqual({ mode: 'system' })
  })
})

describe('updater — downloadUpdate error mapping', () => {
  it('maps ZIP-not-provided error to user-friendly message', async () => {
    const { configureUpdater, downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)

    mocks.autoUpdater.downloadUpdate.mockRejectedValueOnce(new Error('ZIP file not provided for auto update'))
    await expect(downloadUpdate()).rejects.toThrow(/无法在应用内自动更新/)
  })

  it('returns alreadyDownloaded when update already downloaded', async () => {
    const { configureUpdater, downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)

    // 模拟 update-downloaded 事件
    const handler = mocks.handlers.get('update-downloaded')
    handler?.({ version: '2.0.0', buildSha: '', files: [] })

    const result = await downloadUpdate()
    expect(result).toEqual({ alreadyDownloaded: true })
  })
})

describe('updater — force upgrade version comparison', () => {
  it('isCurrentBelowMinVersion returns true when local < min', async () => {
    process.env.XCAGI_PRODUCT_VERSION = '1.0.0.0'
    const { checkForUpdates, isCurrentBelowMinVersion } = await import('./updater.js')
    process.env.XCAGI_UPDATE_URL = 'http://127.0.0.1:19999/releases/'
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    const metadata = buildMetadata('2.0.0', '\nminVersion: 1.0.0.1\nforceUpgrade: true')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => metadata,
    } as Response)

    await checkForUpdates()
    expect(isCurrentBelowMinVersion()).toBe(true)
    fetchSpy.mockRestore()
  })

  it('isForceUpgradeRequired is false when forceUpgrade is false', async () => {
    process.env.XCAGI_PRODUCT_VERSION = '1.0.0.0'
    const { checkForUpdates, isForceUpgradeRequired } = await import('./updater.js')
    process.env.XCAGI_UPDATE_URL = 'http://127.0.0.1:19999/releases/'
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    const metadata = buildMetadata('2.0.0', '\nminVersion: 2.0.0.0\nforceUpgrade: false')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => metadata,
    } as Response)

    await checkForUpdates()
    expect(isForceUpgradeRequired()).toBe(false)
    fetchSpy.mockRestore()
  })

  it('isCurrentBelowMinVersion returns false when no minVersion set', async () => {
    const { isCurrentBelowMinVersion } = await import('./updater.js')
    expect(isCurrentBelowMinVersion()).toBe(false)
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
    const { configureUpdater } = await import('./updater.js')
    configureUpdater({ isDestroyed: () => false, webContents: { send: vi.fn() } } as never)
    expect(mocks.autoUpdater.setFeedURL).toHaveBeenCalledWith(
      expect.objectContaining({ provider: 'generic', url: 'http://127.0.0.1:19999/releases/', channel: 'beta' }),
    )
  })
})

describe('updater — fetchTextViaSession network paths', () => {
  it('resolves with body on 2xx', async () => {
    const { net } = await import('electron')
    ;(net.request as ReturnType<typeof vi.fn>).mockImplementation(
      makeNetRequest({ statusCode: 200, body: 'version: 1.0.0' }),
    )
    const { fetchTextViaSession } = await import('./updater.js')
    const fakeSession = {} as never
    await expect(fetchTextViaSession(fakeSession, 'http://127.0.0.1/latest.yml')).resolves.toBe(
      'version: 1.0.0',
    )
  })

  it('rejects on non-2xx status', async () => {
    const { net } = await import('electron')
    ;(net.request as ReturnType<typeof vi.fn>).mockImplementation(
      makeNetRequest({ statusCode: 404, statusMessage: 'Not Found', body: '' }),
    )
    const { fetchTextViaSession } = await import('./updater.js')
    await expect(fetchTextViaSession({} as never, 'http://127.0.0.1/latest.yml')).rejects.toThrow(
      /更新元数据下载失败: 404/,
    )
  })

  it('rejects when the response stream errors', async () => {
    const { net } = await import('electron')
    ;(net.request as ReturnType<typeof vi.fn>).mockImplementation(
      makeNetRequest({ statusCode: 200, emitError: new Error('stream broken') }),
    )
    const { fetchTextViaSession } = await import('./updater.js')
    await expect(fetchTextViaSession({} as never, 'http://127.0.0.1/latest.yml')).rejects.toThrow(
      'stream broken',
    )
  })

  it('rejects when the request itself errors', async () => {
    const { net } = await import('electron')
    ;(net.request as ReturnType<typeof vi.fn>).mockImplementation(
      makeNetRequest({ statusCode: 200, requestError: new Error('net down') }),
    )
    const { fetchTextViaSession } = await import('./updater.js')
    await expect(fetchTextViaSession({} as never, 'http://127.0.0.1/latest.yml')).rejects.toThrow(
      'net down',
    )
  })
})

describe('updater — parseYamlBlock', () => {
  it('extracts inline value', async () => {
    const { parseYamlField } = await import('./updater.js')
    expect(parseYamlField('version: 1.0.0\npath: test.zip', 'path')).toBe('test.zip')
  })

  it('returns empty for missing field', async () => {
    const { parseYamlField } = await import('./updater.js')
    expect(parseYamlField('version: 1.0.0', 'missing')).toBe('')
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
