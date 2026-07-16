import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import crypto from 'node:crypto'

// Mock electron 和 electron-updater 以便测试 downloadUpdate 和事件处理
const updaterMocks = vi.hoisted(() => ({
  autoUpdater: {
    autoDownload: false,
    autoInstallOnAppQuit: true,
    setFeedURL: vi.fn(),
    on: vi.fn(),
    checkForUpdates: vi.fn(() => Promise.resolve({})),
    downloadUpdate: vi.fn(() => Promise.resolve()),
    quitAndInstall: vi.fn(),
  }
}))

vi.mock('electron', () => ({
  app: { isPackaged: false, getVersion: () => '10.0.0', getPath: () => '/tmp' },
  BrowserWindow: vi.fn(() => ({ isDestroyed: () => true, webContents: { send: vi.fn() } })),
  session: { defaultSession: { setProxy: vi.fn(() => Promise.resolve()), resolveProxy: vi.fn(() => 'DIRECT') } },
  net: { request: vi.fn() },
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

describe('updater — downloadUpdate reuses in-flight Promise', () => {
  beforeEach(() => {
    vi.resetModules()
    updaterMocks.autoUpdater.downloadUpdate = vi.fn(() => new Promise(resolve => setTimeout(() => resolve({}), 50)))
  })

  afterEach(() => {
    updaterMocks.autoUpdater.downloadUpdate = vi.fn(() => Promise.resolve())
  })

  it('concurrent calls share the same Promise (autoUpdater.downloadUpdate called once)', async () => {
    const { downloadUpdate, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()

    const p1 = downloadUpdate()
    const p2 = downloadUpdate()

    await Promise.all([p1, p2])

    expect(updaterMocks.autoUpdater.downloadUpdate).toHaveBeenCalledTimes(1)
  })
})

describe('updater — error after update-available emits update-available-with-error', () => {
  beforeEach(() => {
    vi.resetModules()
    updaterMocks.autoUpdater.on = vi.fn()
  })

  it('emits update-available-with-error type when error follows update-available', async () => {
    const { configureUpdater, getUpdateStatus, __resetUpdateDownloadedForTest } = await import('./updater.js')
    __resetUpdateDownloadedForTest()

    // configureUpdater 注册事件处理器
    configureUpdater({} as never)

    // 找到 autoUpdater.on 的调用，模拟事件触发
    const onCalls = updaterMocks.autoUpdater.on.mock.calls
    const updateAvailableHandler = onCalls.find(c => c[0] === 'update-available')?.[1]
    const errorHandler = onCalls.find(c => c[0] === 'error')?.[1]

    expect(updateAvailableHandler).toBeDefined()
    expect(errorHandler).toBeDefined()

    // 先触发 update-available
    updateAvailableHandler({ version: '10.0.1' })
    expect(getUpdateStatus()?.type).toBe('update-available')

    // 再触发 error
    errorHandler(new Error('network error'))
    const status = getUpdateStatus()
    expect(status?.type).toBe('update-available-with-error')
    expect((status?.data as { lastError?: { message?: string } })?.lastError?.message).toBe('network error')
  })
})
