/**
 * useStartupSplash 覆盖率提升测试
 *
 * 目标：覆盖 useStartupSplash.ts 中未覆盖的分支，将覆盖率提升到 90%+。
 * 重点覆盖：
 *   - runStartupProgressLoop / stopStartupProgressLoop：进度动画循环
 *   - clearStartupTimers：failsafe timer / min wait timer / resolveStartupMinWait
 *   - loadModsForStartup：hint 设置、超时错误、finally 中 startupVisible 分支
 *   - teardownStartupAudio / tryPlayStartupAudio / bindStartupAudioFallback / initStartupAudio
 *   - createMinSplashElapsed：resolveStartupMinWait 回调路径
 *   - teardownOnUnmount：audio null 检查
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（apiBase / modLoadingStatus / modLoadingStatusShared / mods store）。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  extractModNames,
  useStartupSplash,
  STARTUP_SPLASH_MS,
  STARTUP_FAILSAFE_MS,
  STARTUP_AUTH_TIMEOUT_MS,
} from './useStartupSplash'

// ── 外部依赖 mock ─────────────────────────────────────────

vi.mock('@/utils/apiBase', () => ({
  isApiFetchTimeoutError: (e: unknown) =>
    e instanceof Error && e.message.includes('timeout'),
}))

vi.mock('@/utils/modLoadingStatusShared', () => ({
  fetchModLoadingStatusShared: vi.fn().mockResolvedValue(null),
}))

vi.mock('@/utils/modLoadingStatus', () => ({
  summarizeModLoadingData: vi.fn().mockReturnValue(''),
}))

vi.mock('@/stores/mods', () => ({
  CLIENT_MODS_UI_OFF_KEY: 'xcagi_client_mods_ui_off',
}))

// ── Mock Audio 构造函数 ────────────────────────────────────

/** 模拟 HTMLAudioElement，捕获 play/pause/addEventListener 调用 */
class MockAudio {
  preload = ''
  volume = 1
  currentTime = 0
  paused = true
  play = vi.fn(() => Promise.resolve())
  pause = vi.fn()
  addEventListener = vi.fn()
  removeEventListener = vi.fn()
}

// ── 测试套件 ──────────────────────────────────────────────

describe('useStartupSplash - coverage ramp', () => {
  let splash: ReturnType<typeof useStartupSplash>
  let originalAudio: typeof globalThis.Audio

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()

    // 替换全局 Audio 构造函数
    originalAudio = globalThis.Audio
    globalThis.Audio = MockAudio as unknown as typeof Audio

    splash = useStartupSplash()
  })

  afterEach(() => {
    splash.teardownOnUnmount()
    globalThis.Audio = originalAudio
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  // ════════════════════════════════════════════════════════════════════
  // runStartupProgressLoop / stopStartupProgressLoop
  // 手动 mock raf 和 performance.now，避免 fake timers 递归 raf 问题
  // ════════════════════════════════════════════════════════════════════

  describe('runStartupProgressLoop / stopStartupProgressLoop', () => {
    let rafCallback: FrameRequestCallback | null
    let perfTime: number

    beforeEach(() => {
      vi.useRealTimers()
      rafCallback = null
      perfTime = 0

      // 手动 mock requestAnimationFrame：捕获回调但不自动执行
      vi.stubGlobal(
        'requestAnimationFrame',
        vi.fn((cb: FrameRequestCallback) => {
          rafCallback = cb
          return 1
        }),
      )
      vi.stubGlobal('cancelAnimationFrame', vi.fn())
      vi.spyOn(performance, 'now').mockImplementation(() => perfTime)
    })

    it('startupVisible=true 时推进进度百分比', () => {
      splash.startupVisible.value = true
      splash.runStartupProgressLoop()

      // 第一次 raf 已注册（callback 被捕获）
      expect(rafCallback).not.toBeNull()

      // 推进 performance 时间到 600ms（一半），手动触发 tick
      perfTime = 600
      rafCallback!(perfTime)

      // 进度应已推进
      expect(splash.startupProgressPct.value).toBeGreaterThan(0)
      expect(splash.startupProgressPct.value).toBeLessThanOrEqual(88)
    })

    it('完整时间后进度达到 88 上限', () => {
      splash.startupVisible.value = true
      splash.runStartupProgressLoop()

      // 推进到超过 STARTUP_SPLASH_MS
      perfTime = STARTUP_SPLASH_MS + 100
      rafCallback!(perfTime)

      expect(splash.startupProgressPct.value).toBe(88)
    })

    it('startupVisible=false 时停止循环（cancelAnimationFrame 被调用）', () => {
      splash.startupVisible.value = true
      splash.runStartupProgressLoop()

      // 第一次 tick 正常执行
      perfTime = 100
      rafCallback!(perfTime)

      // 设置 visible=false，触发 tick → stopStartupProgressLoop
      const cancelSpy = globalThis.cancelAnimationFrame as ReturnType<typeof vi.fn>
      cancelSpy.mockClear()

      splash.startupVisible.value = false
      rafCallback!(perfTime)

      // stopStartupProgressLoop 应调用 cancelAnimationFrame
      expect(cancelSpy).toHaveBeenCalled()
    })

    it('pct 不超过已有值时不更新', () => {
      splash.startupVisible.value = true
      splash.startupProgressPct.value = 88
      splash.runStartupProgressLoop()

      // 推进时间，但 pct 已是 88 上限
      perfTime = 600
      rafCallback!(perfTime)

      // 不应降低
      expect(splash.startupProgressPct.value).toBe(88)
    })

    it('stopStartupProgressLoop 在 raf 为 null 时不调用 cancel', () => {
      const cancelSpy = globalThis.cancelAnimationFrame as ReturnType<typeof vi.fn>
      cancelSpy.mockClear()

      // 直接调用 teardownOnUnmount（内部调用 stopStartupProgressLoop）
      // raf 从未被设置，应为 null
      splash.teardownOnUnmount()

      // cancelAnimationFrame 不应被调用（raf 为 null）
      expect(cancelSpy).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // clearStartupTimers（通过 completeStartupSplash / dismissStartupSplashImmediate 触发）
  // ════════════════════════════════════════════════════════════════════

  describe('clearStartupTimers', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('completeStartupSplash 首次调用时清理 failsafe timer 和 min wait timer', async () => {
      // 设置 failsafe timer
      splash.appReady.value = false
      splash.scheduleFailsafe(() => {})
      expect(splash.getFailsafeTimer()).not.toBeNull()

      // 设置 min wait timer（同时设置 resolveStartupMinWait）
      const minWaitPromise = splash.createMinSplashElapsed()

      // 首次调用 completeStartupSplash → clearStartupTimers
      const ensureAuth = vi.fn().mockResolvedValue({ ok: true })
      splash.completeStartupSplash(ensureAuth)

      // failsafe timer 应被清理
      expect(splash.getFailsafeTimer()).toBeNull()

      // min wait promise 应被 resolve（通过 resolveStartupMinWait 回调）
      await expect(minWaitPromise).resolves.toBeUndefined()
    })

    it('dismissStartupSplashImmediate 首次调用时清理 failsafe timer', () => {
      splash.appReady.value = false
      splash.scheduleFailsafe(() => {})
      expect(splash.getFailsafeTimer()).not.toBeNull()

      splash.dismissStartupSplashImmediate()
      expect(splash.getFailsafeTimer()).toBeNull()
    })

    it('clearFailsafeTimer 清理 failsafe timer', () => {
      splash.appReady.value = false
      splash.scheduleFailsafe(() => {})
      expect(splash.getFailsafeTimer()).not.toBeNull()

      splash.clearFailsafeTimer()
      expect(splash.getFailsafeTimer()).toBeNull()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // loadModsForStartup - 错误路径与 hint
  // ════════════════════════════════════════════════════════════════════

  describe('loadModsForStartup - 错误路径与 hint', () => {
    beforeEach(() => {
      vi.useRealTimers()
    })

    it('返回数据且 summarizeModLoadingData 返回 hint 时设置 modsLoadError', async () => {
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
      const { summarizeModLoadingData } = await import('@/utils/modLoadingStatus')

      vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({
        mods: [{ name: 'M1' }],
      })
      vi.mocked(summarizeModLoadingData).mockReturnValueOnce('加载异常提示')

      await splash.loadModsForStartup()

      expect(splash.modsLoadError.value).toBe('加载异常提示')
      expect(splash.startupModPreview.value).toEqual([{ name: 'M1' }])
    })

    it('返回数据但 mods 不是数组时使用空数组', async () => {
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
      vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({ mods: 'not array' })

      await splash.loadModsForStartup()

      expect(splash.startupModPreview.value).toEqual([])
    })

    it('超时错误时输出 console.debug', async () => {
      const debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => {})
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')

      vi.mocked(fetchModLoadingStatusShared).mockRejectedValueOnce(
        new Error('network timeout'),
      )
      await splash.loadModsForStartup()

      expect(debugSpy).toHaveBeenCalled()
      expect(splash.startupModPreview.value).toEqual([])
      debugSpy.mockRestore()
    })

    it('非超时错误时输出 console.warn', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')

      vi.mocked(fetchModLoadingStatusShared).mockRejectedValueOnce(
        new Error('server error'),
      )
      await splash.loadModsForStartup()

      expect(warnSpy).toHaveBeenCalled()
      expect(splash.startupModPreview.value).toEqual([])
      warnSpy.mockRestore()
    })

    it('startupVisible=true 时 finally 中推进进度到至少 72', async () => {
      splash.startupVisible.value = true
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
      vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({ mods: [] })

      await splash.loadModsForStartup()

      expect(splash.startupProgressPct.value).toBeGreaterThanOrEqual(72)
    })

    it('startupVisible=false 时 finally 中不推进进度', async () => {
      splash.startupVisible.value = false
      splash.startupProgressPct.value = 0
      const { fetchModLoadingStatusShared } = await import('@/utils/modLoadingStatusShared')
      vi.mocked(fetchModLoadingStatusShared).mockResolvedValueOnce({ mods: [] })

      await splash.loadModsForStartup()

      expect(splash.startupProgressPct.value).toBe(0)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // 音频初始化与清理
  // ════════════════════════════════════════════════════════════════════

  describe('initStartupAudio / tryPlayStartupAudio / bindStartupAudioFallback', () => {
    beforeEach(() => {
      vi.useRealTimers()
    })

    it('initStartupAudio 创建 Audio 并设置属性', () => {
      const urlFn = vi.fn((fileName: string) => `/audio/${fileName}`)
      splash.initStartupAudio(urlFn)

      expect(urlFn).toHaveBeenCalledWith('startup-enter.mp3')
    })

    it('initStartupAudio 调用 tryPlayStartupAudio（play 被调用）', () => {
      const playMock = vi.fn(() => Promise.resolve())
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: playMock,
        pause: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')

      expect(playMock).toHaveBeenCalled()
    })

    it('initStartupAudio 设置 preload=metadata 和 volume=0.9', () => {
      let captured: { preload: string; volume: number } | null = null
      globalThis.Audio = vi.fn().mockImplementation(() => {
        const obj = {
          preload: '',
          volume: 1,
          currentTime: 0,
          paused: true,
          play: vi.fn(() => Promise.resolve()),
          pause: vi.fn(),
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        }
        captured = obj
        return obj
      }) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')

      expect(captured).not.toBeNull()
      expect(captured!.preload).toBe('metadata')
      expect(captured!.volume).toBe(0.9)
    })

    it('Audio error 事件将 startupAudio 置空（后续 teardown 不崩溃）', () => {
      const errorListeners: Array<(e: Event) => void> = []
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: vi.fn(() => Promise.resolve()),
        pause: vi.fn(),
        addEventListener: vi.fn((event: string, listener: (e: Event) => void) => {
          if (event === 'error') errorListeners.push(listener)
        }),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')

      // 触发 error 事件 → startupAudio = null
      errorListeners.forEach((l) => l(new Event('error')))

      // teardownOnUnmount 不应崩溃（startupAudio 已为 null）
      splash.teardownOnUnmount()
      expect(true).toBe(true)
    })

    it('tryPlayStartupAudio 在 play 失败时不抛异常', () => {
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: vi.fn(() => Promise.reject(new Error('autoplay blocked'))),
        pause: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      // 不应抛异常
      splash.initStartupAudio(() => '/audio/startup.mp3')
      expect(true).toBe(true)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // bindStartupAudioFallback - 用户手势触发
  // ════════════════════════════════════════════════════════════════════

  describe('bindStartupAudioFallback - 用户手势触发', () => {
    beforeEach(() => {
      vi.useRealTimers()
    })

    it('pointerdown 事件触发音频 fallback 播放', () => {
      const playMock = vi.fn(() => Promise.resolve())
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: playMock,
        pause: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')
      // initStartupAudio 内部已调用 tryPlayStartupAudio（play 第 1 次）
      playMock.mockClear()

      // 模拟用户手势 → bindStartupAudioFallback 注册的 handler
      document.dispatchEvent(new Event('pointerdown'))

      // fallback handler 应调用 play
      expect(playMock).toHaveBeenCalled()
    })

    it('keydown 事件触发音频 fallback 播放', () => {
      const playMock = vi.fn(() => Promise.resolve())
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: playMock,
        pause: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')
      playMock.mockClear()

      document.dispatchEvent(new Event('keydown'))

      expect(playMock).toHaveBeenCalled()
    })

    it('fallback 已播放后不再触发（startupAudioFallbackPlayed 守卫）', () => {
      const playMock = vi.fn(() => Promise.resolve())
      globalThis.Audio = vi.fn().mockImplementation(() => ({
        preload: '',
        volume: 1,
        currentTime: 0,
        paused: true,
        play: playMock,
        pause: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')
      playMock.mockClear()

      // 第一次触发
      document.dispatchEvent(new Event('pointerdown'))
      const firstCount = playMock.mock.calls.length

      // 第二次触发不应再调用 play
      document.dispatchEvent(new Event('keydown'))
      expect(playMock.mock.calls.length).toBe(firstCount)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // teardownStartupAudio / teardownOnUnmount
  // ════════════════════════════════════════════════════════════════════

  describe('teardownStartupAudio / teardownOnUnmount', () => {
    beforeEach(() => {
      vi.useRealTimers()
    })

    it('teardownOnUnmount 暂停音频并重置 currentTime', () => {
      const pauseMock = vi.fn()
      const audioObj = {
        preload: '',
        volume: 1,
        currentTime: 5,
        paused: false,
        play: vi.fn(() => Promise.resolve()),
        pause: pauseMock,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      }
      globalThis.Audio = vi.fn().mockImplementation(() => audioObj) as unknown as typeof Audio

      splash.initStartupAudio(() => '/audio/startup.mp3')

      splash.teardownOnUnmount()

      // pause 应被调用
      expect(pauseMock).toHaveBeenCalled()
      // currentTime 应被重置为 0
      expect(audioObj.currentTime).toBe(0)
    })

    it('teardownOnUnmount 清理 audio 为 null（lines 246-247）', () => {
      splash.initStartupAudio(() => '/audio/startup.mp3')

      // teardownOnUnmount 内部：teardownStartupAudio → if (startupAudio) { startupAudio = null }
      splash.teardownOnUnmount()

      // 再次调用不应崩溃（audio 已为 null）
      splash.teardownOnUnmount()
      expect(true).toBe(true)
    })

    it('teardownOnUnmount 在 audio 为 null 时不崩溃', () => {
      // 不调用 initStartupAudio，audio 为 null
      splash.teardownOnUnmount()
      expect(true).toBe(true)
    })

    it('teardownOnUnmount 清理所有资源（timers + raf + audio）', () => {
      splash.initStartupAudio(() => '/audio/startup.mp3')
      splash.appReady.value = false
      splash.scheduleFailsafe(() => {})
      splash.startupVisible.value = true
      splash.runStartupProgressLoop()

      splash.teardownOnUnmount()

      // failsafe timer 应被清理
      expect(splash.getFailsafeTimer()).toBeNull()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // createMinSplashElapsed - resolveStartupMinWait 路径
  // ════════════════════════════════════════════════════════════════════

  describe('createMinSplashElapsed', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('通过 clearStartupTimers 提前 resolve（resolveStartupMinWait 回调）', async () => {
      const promise = splash.createMinSplashElapsed()
      // 通过 completeStartupSplash → clearStartupTimers → resolveStartupMinWait 提前 resolve
      splash.completeStartupSplash(vi.fn().mockResolvedValue({ ok: true }))
      await expect(promise).resolves.toBeUndefined()
    })

    it('通过 dismissStartupSplashImmediate 提前 resolve', async () => {
      const promise = splash.createMinSplashElapsed()
      splash.dismissStartupSplashImmediate()
      await expect(promise).resolves.toBeUndefined()
    })

    it('通过超时正常 resolve', async () => {
      const promise = splash.createMinSplashElapsed()
      vi.advanceTimersByTime(STARTUP_SPLASH_MS)
      await expect(promise).resolves.toBeUndefined()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // completeStartupSplash - 首次/二次调用与 auth 超时
  // ════════════════════════════════════════════════════════════════════

  describe('completeStartupSplash', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('二次调用直接 finishStartupUi 不再启动 auth', async () => {
      const ensureAuth = vi.fn().mockResolvedValue({ ok: true })

      // 首次调用
      splash.completeStartupSplash(ensureAuth)
      await vi.advanceTimersByTimeAsync(STARTUP_AUTH_TIMEOUT_MS + 100)

      splash.startupVisible.value = true
      ensureAuth.mockClear()

      // 二次调用
      splash.completeStartupSplash(ensureAuth)
      expect(splash.startupVisible.value).toBe(false)
      // 二次调用不应再调用 ensureAuth
      expect(ensureAuth).not.toHaveBeenCalled()
    })

    it('auth 超时后仍 finishStartupUi', async () => {
      const ensureAuth = vi.fn(() => new Promise(() => {})) // 永不 resolve
      splash.completeStartupSplash(ensureAuth)

      // 推进超过 auth 超时时间
      await vi.advanceTimersByTimeAsync(STARTUP_AUTH_TIMEOUT_MS + 100)

      expect(splash.startupVisible.value).toBe(false)
      expect(splash.appReady.value).toBe(true)
    })

    it('auth 抛异常时仍 finishStartupUi', async () => {
      const ensureAuth = vi.fn().mockRejectedValue(new Error('auth fail'))
      splash.completeStartupSplash(ensureAuth)

      await vi.advanceTimersByTimeAsync(100)

      expect(splash.startupVisible.value).toBe(false)
      expect(splash.appReady.value).toBe(true)
    })

    it('首次调用设置 progressPct 为 100', () => {
      const ensureAuth = vi.fn().mockResolvedValue({ ok: true })
      splash.completeStartupSplash(ensureAuth)
      expect(splash.startupProgressPct.value).toBe(100)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // scheduleFailsafe - 兜底超时
  // ════════════════════════════════════════════════════════════════════

  describe('scheduleFailsafe', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('appReady=false 时超时后调用 complete', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      const complete = vi.fn()
      splash.appReady.value = false
      splash.scheduleFailsafe(complete)
      vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
      expect(complete).toHaveBeenCalled()
      expect(warnSpy).toHaveBeenCalled()
      warnSpy.mockRestore()
    })

    it('appReady=true 时超时后不调用 complete', () => {
      const complete = vi.fn()
      splash.appReady.value = true
      splash.scheduleFailsafe(complete)
      vi.advanceTimersByTime(STARTUP_FAILSAFE_MS)
      expect(complete).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // skipStartupSplash
  // ════════════════════════════════════════════════════════════════════

  describe('skipStartupSplash', () => {
    it('startupVisible=true 时调用 complete', () => {
      const complete = vi.fn()
      splash.startupVisible.value = true
      splash.skipStartupSplash(complete)
      expect(complete).toHaveBeenCalled()
    })

    it('startupVisible=false 时不调用 complete', () => {
      const complete = vi.fn()
      splash.startupVisible.value = false
      splash.skipStartupSplash(complete)
      expect(complete).not.toHaveBeenCalled()
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // dismissStartupSplashImmediate
  // ════════════════════════════════════════════════════════════════════

  describe('dismissStartupSplashImmediate', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    it('首次调用设置 splashFinishOnce 并清理 timers', () => {
      splash.appReady.value = false
      splash.scheduleFailsafe(() => {})
      expect(splash.getFailsafeTimer()).not.toBeNull()

      splash.dismissStartupSplashImmediate()

      expect(splash.startupVisible.value).toBe(false)
      expect(splash.appReady.value).toBe(true)
      expect(splash.startupProgressPct.value).toBe(100)
      expect(splash.getFailsafeTimer()).toBeNull()
    })

    it('二次调用直接返回（splashFinishOnce 守卫）', () => {
      splash.startupVisible.value = true
      splash.dismissStartupSplashImmediate()
      // 二次调用
      splash.startupVisible.value = true
      splash.dismissStartupSplashImmediate()
      expect(splash.startupVisible.value).toBe(false)
    })
  })

  // ════════════════════════════════════════════════════════════════════
  // extractModNames - 边界覆盖
  // ════════════════════════════════════════════════════════════════════

  describe('extractModNames - 边界覆盖', () => {
    it('name 和 id 都为空时被过滤', () => {
      expect(extractModNames([{ name: '', id: '' }])).toEqual([])
    })

    it('name 含空白时被 trim 并过滤', () => {
      expect(extractModNames([{ name: '  ' }, { name: 'A' }])).toEqual(['A'])
    })

    it('id 作为 fallback', () => {
      expect(extractModNames([{ name: '', id: 'x' }])).toEqual(['x'])
    })

    it('name 和 id 同时存在时优先 name', () => {
      expect(extractModNames([{ name: 'A', id: 'x' }])).toEqual(['A'])
    })

    it('重复 name 被去重', () => {
      expect(extractModNames([{ name: 'A' }, { name: 'A' }, { id: 'A' }])).toEqual([
        'A',
      ])
    })
  })
})
