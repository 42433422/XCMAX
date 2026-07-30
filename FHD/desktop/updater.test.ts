import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import crypto from 'node:crypto'

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

// 动态生成 Ed25519 密钥对，避免硬编码私钥（更安全、可移植）
const keyPair = crypto.generateKeyPairSync('ed25519')
const TEST_PRIVATE_KEY_PEM = keyPair.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
const TEST_PUBLIC_KEY_PEM = keyPair.publicKey.export({ type: 'spki', format: 'pem' }).toString()

function signBody(body: string): string {
  const privateKey = crypto.createPrivateKey(TEST_PRIVATE_KEY_PEM)
  const sig = crypto.sign(null, Buffer.from(body, 'utf8'), privateKey)
  return `signature: ed25519:${sig.toString('base64')}`
}

function buildMetadata(version: string, withSignature = true): string {
  const body = `version: ${version}
files:
  - url: XCAGI-${version}.exe
    sha512: fake-sha512
    size: 12345
path: XCAGI-${version}.exe
sha512: fake-sha512
releaseDate: '2026-07-05T00:00:00.000Z'`
  if (!withSignature) return body
  return `${body}\n${signBody(body)}`
}

describe('updater — verifyMetadataSignatureText', () => {
  it('accepts valid Ed25519 signature', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const content = buildMetadata('10.0.1')
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).resolves.toBeUndefined()
  })

  it('rejects missing signature line', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const content = buildMetadata('10.0.1', false)
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).rejects.toThrow(
      /缺少 Ed25519 二次签名/
    )
  })

  it('rejects tampered body content', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const content = buildMetadata('10.0.1')
    const tampered = content.replace('10.0.1', '10.0.2')
    await expect(verifyMetadataSignatureText(tampered, TEST_PUBLIC_KEY_PEM)).rejects.toThrow(
      /Ed25519 二次签名校验失败/
    )
  })

  it('rejects signature from wrong key', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const other = crypto.generateKeyPairSync('ed25519')
    const otherPrivate = other.privateKey.export({ type: 'pkcs8', format: 'pem' }).toString()
    const body = `version: 10.0.1\npath: XCAGI-10.0.1.exe`
    const otherSig = crypto.sign(null, Buffer.from(body, 'utf8'), crypto.createPrivateKey(otherPrivate))
    const content = `${body}\nsignature: ed25519:${otherSig.toString('base64')}`
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).rejects.toThrow(
      /Ed25519 二次签名校验失败/
    )
  })

  it('verifies signature line appended at end of yaml content', async () => {
    // 真实生产场景：签名脚本在 latest.yml 末尾追加 "signature: ed25519:<sig>" 行
    // verifyMetadataSignatureText 必须过滤该行后用剩余 yaml 验签
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const yamlContent = `version: 10.0.1
files:
  - url: XCAGI-10.0.1.exe
    sha512: fake-sha512
    size: 12345
path: XCAGI-10.0.1.exe
sha512: fake-sha512
releaseDate: '2026-07-05T00:00:00.000Z'`
    const sig = signBody(yamlContent)
    const content = `${yamlContent}\n${sig}`
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).resolves.toBeUndefined()
  })

  it('handles CRLF line endings', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const body = `version: 10.0.1\r\npath: XCAGI-10.0.1.exe`
    // 签名时用 \n 规范化
    const sig = signBody(body.replace(/\r\n/g, '\n'))
    const content = `${body}\r\n${sig}`
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).resolves.toBeUndefined()
  })

  it('rejects malformed signature base64', async () => {
    const { verifyMetadataSignatureText } = await import('./updater.js')
    const content = `version: 10.0.1\nsignature: ed25519:!!!not-base64!!!`
    await expect(verifyMetadataSignatureText(content, TEST_PUBLIC_KEY_PEM)).rejects.toThrow()
  })
})


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

describe('updater — parseYamlField', () => {
  it('extracts buildSha from yaml text', async () => {
    const { parseYamlField } = await import('./updater.js')
    const content = `version: 10.0.0\nbuildSha: abc123\ntest: 1`
    expect(parseYamlField(content, 'buildSha')).toBe('abc123')
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

describe('updater — verifyLatestMetadataSignature', () => {
  const savedEnv = { ...process.env }

  beforeEach(() => {
    vi.resetModules()
    delete process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY
    delete process.env.XCAGI_UPDATE_URL
  })

  afterEach(() => {
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = savedEnv.XCAGI_UPDATE_ED25519_PUBLIC_KEY
    process.env.XCAGI_UPDATE_URL = savedEnv.XCAGI_UPDATE_URL
  })

  it('skips silently when env not configured', async () => {
    const { verifyLatestMetadataSignature } = await import('./updater.js')
    await expect(verifyLatestMetadataSignature()).resolves.toBeUndefined()
  })

  it('accepts fetched content with valid signature via fetchLatestMetadataText', async () => {
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    process.env.XCAGI_UPDATE_URL = 'https://update.example.com/releases/stable/enterprise/'
    const validContent = buildMetadata('10.0.5')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => validContent
    } as Response)
    const { fetchLatestMetadataText } = await import('./updater.js')
    await expect(fetchLatestMetadataText()).resolves.toContain('version: 10.0.5')
    fetchSpy.mockRestore()
  })

  it('throws on HTTP failure (404)', async () => {
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    process.env.XCAGI_UPDATE_URL = 'https://update.example.com/releases/stable/enterprise/'
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      text: async () => ''
    } as Response)
    const { verifyLatestMetadataSignature } = await import('./updater.js')
    await expect(verifyLatestMetadataSignature()).rejects.toThrow(/404/)
    fetchSpy.mockRestore()
  })

  it('throws when fetched content has no signature', async () => {
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    process.env.XCAGI_UPDATE_URL = 'https://update.example.com/releases/stable/enterprise/'
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => 'version: 10.0.5\npath: XCAGI-10.0.5.exe'
    } as Response)
    const { verifyLatestMetadataSignature } = await import('./updater.js')
    await expect(verifyLatestMetadataSignature()).rejects.toThrow(/缺少 Ed25519 二次签名/)
    fetchSpy.mockRestore()
  })

  it('accepts fetched content with valid signature', async () => {
    process.env.XCAGI_UPDATE_ED25519_PUBLIC_KEY = TEST_PUBLIC_KEY_PEM
    process.env.XCAGI_UPDATE_URL = 'https://update.example.com/releases/stable/enterprise/'
    const validContent = buildMetadata('10.0.5')
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => validContent
    } as Response)
    const { verifyLatestMetadataSignature } = await import('./updater.js')
    await expect(verifyLatestMetadataSignature()).resolves.toBeUndefined()
    fetchSpy.mockRestore()
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
    const { downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()

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
