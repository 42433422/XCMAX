import { describe, it, expect, vi, beforeEach } from 'vitest'

// offlineTts 依赖重（transformers/worker），统一 mock 掉
const mockEnsureOfflineReady = vi.fn().mockResolvedValue(undefined)

vi.mock('./offlineTts', () => ({
  playOfflinePcm: vi.fn(),
  synthesizeOffline: vi.fn(),
  ensureOfflineReady: mockEnsureOfflineReady,
  isOfflineReady: vi.fn(() => false),
  isOfflineLoading: vi.fn(() => false),
  getOfflineProgress: vi.fn(() => 0),
  stopOffline: vi.fn(),
}))

vi.mock('./apiBase', () => ({
  apiFetch: vi.fn(),
  getApiBase: vi.fn(() => ''),
}))

vi.mock('./csrfCookie', () => ({
  readCsrfTokenFromCookie: vi.fn(() => ''),
  shouldAttachCsrfHeader: vi.fn(() => false),
}))

function installSpeechMocks(voices: Array<Record<string, unknown>>): void {
  Object.defineProperty(window, 'speechSynthesis', {
    configurable: true,
    value: {
      speak: vi.fn(),
      cancel: vi.fn(),
      getVoices: () => voices,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      speaking: false,
      pending: false,
    },
  })
}

/** 通过 pickBestChineseVoiceSync 触发 exposeDebugHelpers，再逐个调用 window.__xcagiTts 的方法。 */
describe('tts window.__xcagiTts debug helpers', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetModules()
    delete (window as unknown as { __xcagiTts?: unknown }).__xcagiTts
  })

  it('voices 加载后暴露 debug 命名空间，且每个方法可调用', async () => {
    installSpeechMocks([
      { name: 'Microsoft Yunxi', lang: 'zh-CN', localService: true, default: false },
      { name: 'Microsoft Xiaoxiao', lang: 'zh-CN', localService: false, default: false },
      { name: 'Google US English', lang: 'en-US', localService: false, default: true },
    ])
    const tts = await import('./tts')

    const picked = tts.pickBestChineseVoiceSync()
    expect(picked?.name).toBe('Microsoft Yunxi')

    const dbg = (window as unknown as { __xcagiTts?: Record<string, unknown> }).__xcagiTts
    expect(dbg).toBeTruthy()
    if (!dbg) return

    // list()
    const listed = dbg.list() as Array<{ name: string; localService: boolean; default: boolean }>
    expect(listed).toHaveLength(3)
    expect(listed[0]).toMatchObject({ name: 'Microsoft Yunxi', localService: true, default: false })

    // current()
    expect(dbg.current()).toBe('Microsoft Yunxi (zh-CN)')

    // status()
    const status = dbg.status() as { engineMode: string; systemVoice: string | null }
    expect(status.engineMode).toBe('online')
    expect(status.systemVoice).toContain('Yunxi')

    // preferred() / set() / reset()
    expect(dbg.preferred()).toBe('')
    expect(dbg.set('Microsoft Xiaoxiao')).toContain('已切换到')
    expect(dbg.preferred()).toBe('Microsoft Xiaoxiao')
    // 偏好不存在时回退最佳音色（Yunxi），仍提示已切换
    expect(dbg.set('NoSuchVoice')).toContain('已切换到')
    expect(dbg.reset()).toContain('已重置')

    // setEngine / onlineVoice / setOnlineVoice（getEngineMode 仅在 debug 子命名空间）
    ;(dbg.setEngine as (m: string) => void)('offline')
    expect(dbg.onlineVoice()).toBe('zh-CN-XiaoxiaoNeural')
    ;(dbg.setOnlineVoice as (id: string) => void)('zh-CN-YunxiNeural')
    expect(dbg.onlineVoice()).toBe('zh-CN-YunxiNeural')

    // download() → startOfflineDownload → ensureOfflineReady
    await expect((dbg.download as () => Promise<void>)()).resolves.toBeUndefined()
    expect(mockEnsureOfflineReady).toHaveBeenCalled()

    // getRate / setRate / clean
    expect(dbg.getRate()).toBe(1.15)
    ;(dbg.setRate as (n: number) => void)(1.5)
    expect(dbg.getRate()).toBe(1.5)
    expect(dbg.clean('你好，世界！')).toBe('你好 世界')

    // debug 子命名空间
    const inner = dbg.debug as Record<string, () => unknown>
    expect(inner.getStatus()).toBeTruthy()
    expect(inner.getEngineMode()).toBe('offline')
    expect(inner.isOfflineReady()).toBe(false)
    expect(inner.isOfflineLoading()).toBe(false)
    expect(inner.getOfflineProgress()).toBe(0)
  }, 15_000)

  it('window 无 speechSynthesis 时不暴露 debug 命名空间', async () => {
    Reflect.deleteProperty(window, 'speechSynthesis')
    const tts = await import('./tts')
    expect(tts.pickBestChineseVoiceSync()).toBeNull()
    expect((window as unknown as { __xcagiTts?: unknown }).__xcagiTts).toBeUndefined()
  })
})
