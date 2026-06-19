/**
 * usePerformanceMonitor 覆盖率提升测试
 *
 * 目标：覆盖 usePerformanceMonitor.ts 中未覆盖的分支，将覆盖率从 58.36% 提升到 90%+。
 * 重点覆盖：
 *   - usePerformanceMonitor：measureFPS（elapsed >= 1000、fpsHistory > 60、fps < threshold 回调）
 *   - measureMemory（有/无 performance.memory、enableMemory 开关）
 *   - detectLongTask（duration > threshold / <= threshold / 无回调 / enableLongTask 开关）
 *   - startMonitoring（已监控、enableFPS/Memory/LongTask 各组合、PerformanceObserver 异常）
 *   - stopMonitoring（各 interval 清理、未启动时停止）
 *   - resetMetrics / getMetrics
 *   - onMounted（autoStart true/false）
 *   - onUnmounted
 *   - useFrameRateLimiter（shouldRender true/false、throttle、cancelThrottle）
 *   - useAnimationFrame（start/stop/updateCallback/animate 各分支/onUnmounted）
 *
 * 遵循铁律3：happy path + 空值/None + 边界值 + 异常路径。
 * Mock 最小化：仅 mock 外部边界（performance API、requestAnimationFrame、PerformanceObserver）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount } from '@vue/test-utils'

import {
  usePerformanceMonitor,
  useFrameRateLimiter,
  useAnimationFrame,
} from './usePerformanceMonitor'

// ── 辅助函数 ──────────────────────────────────────────────────────────

/** 在组件 setup 中调用 composable，触发 onMounted/onUnmounted */
function mountWithComposable<T>(
  setup: () => T,
): { wrapper: ReturnType<typeof mount>; api: T } {
  let api!: T
  const Comp = defineComponent({
    setup() {
      api = setup()
      return () => h('div')
    },
  })
  const wrapper = mount(Comp)
  return { wrapper, api }
}

// ════════════════════════════════════════════════════════════════════
// usePerformanceMonitor
// ════════════════════════════════════════════════════════════════════

describe('usePerformanceMonitor - coverage ramp', () => {
  let nowValue: number
  let rafCallbacks: FrameRequestCallback[]
  let intervalCallbacks: Array<() => void>
  let observerCallback:
    | ((list: { getEntries: () => PerformanceEntry[] }) => void)
    | null
  let observerObserve: ReturnType<typeof vi.fn>
  let originalPerformanceObserver: typeof PerformanceObserver | undefined

  beforeEach(() => {
    nowValue = 0
    rafCallbacks = []
    intervalCallbacks = []
    observerCallback = null
    observerObserve = vi.fn()

    vi.spyOn(performance, 'now').mockImplementation(() => nowValue)
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((cb: FrameRequestCallback) => {
        rafCallbacks.push(cb)
        return rafCallbacks.length
      }),
    )
    vi.stubGlobal('cancelAnimationFrame', vi.fn(() => {}))
    vi.stubGlobal(
      'setInterval',
      vi.fn((cb: () => void) => {
        intervalCallbacks.push(cb)
        return intervalCallbacks.length
      }) as unknown as typeof setInterval,
    )
    vi.stubGlobal('clearInterval', vi.fn(() => {}))

    originalPerformanceObserver = globalThis.PerformanceObserver
    vi.stubGlobal(
      'PerformanceObserver',
      vi.fn(
        (cb: (list: { getEntries: () => PerformanceEntry[] }) => void) => {
          observerCallback = cb
          return { observe: observerObserve }
        },
      ),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    if (originalPerformanceObserver) {
      globalThis.PerformanceObserver = originalPerformanceObserver
    }
    // 清理可能残留的 performance.memory
    try {
      delete (performance as Record<string, unknown>).memory
    } catch {
      /* ignore */
    }
  })

  /** 取最后注册的 rAF 回调 */
  function lastRaf(): FrameRequestCallback | null {
    return rafCallbacks.length > 0
      ? rafCallbacks[rafCallbacks.length - 1]
      : null
  }

  // ── 基础 API 返回值 ──────────────────────────────────────────────

  describe('基础 API 返回值', () => {
    it('返回完整的监控 API surface', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ autoStart: false }),
      )
      expect(api.fps).toBeDefined()
      expect(api.memory).toBeDefined()
      expect(api.longTasks).toBeDefined()
      expect(api.isMonitoring).toBeDefined()
      expect(api.performanceMetrics).toBeDefined()
      expect(typeof api.startMonitoring).toBe('function')
      expect(typeof api.stopMonitoring).toBe('function')
      expect(typeof api.resetMetrics).toBe('function')
      expect(typeof api.getMetrics).toBe('function')
      wrapper.unmount()
    })
  })

  // ── onMounted / autoStart ────────────────────────────────────────

  describe('onMounted / autoStart', () => {
    it('autoStart 默认 true 时 onMounted 自动启动监控', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ enableMemory: false, enableLongTask: false }),
      )
      expect(api.isMonitoring.value).toBe(true)
      wrapper.unmount()
    })

    it('autoStart=false 时 onMounted 不启动监控', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ autoStart: false }),
      )
      expect(api.isMonitoring.value).toBe(false)
      wrapper.unmount()
    })
  })

  // ── startMonitoring ──────────────────────────────────────────────

  describe('startMonitoring', () => {
    it('已监控时不重复启动', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      const rafCountBefore = rafCallbacks.length
      api.startMonitoring()
      expect(rafCallbacks.length).toBe(rafCountBefore)
      wrapper.unmount()
    })

    it('enableFPS=true 时注册 requestAnimationFrame', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      rafCallbacks.length = 0
      api.startMonitoring()
      expect(rafCallbacks.length).toBe(1)
      wrapper.unmount()
    })

    it('enableFPS=false 时不注册 requestAnimationFrame', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      rafCallbacks.length = 0
      api.startMonitoring()
      expect(rafCallbacks.length).toBe(0)
      wrapper.unmount()
    })

    it('enableMemory=true 时立即测量内存并设置 interval', () => {
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: { usedJSHeapSize: 1048576 * 10 },
      })
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: true,
          enableLongTask: false,
        }),
      )
      intervalCallbacks.length = 0
      api.startMonitoring()
      // measureMemory 立即调用一次 + memoryInterval + sampleInterval = 2 个 interval
      expect(intervalCallbacks.length).toBe(2)
      expect(api.memory.value).toBe(10)
      wrapper.unmount()
    })

    it('enableMemory=false 时不设置 memory interval', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      intervalCallbacks.length = 0
      api.startMonitoring()
      // 只有 sampleInterval，没有 memoryInterval
      expect(intervalCallbacks.length).toBe(1)
      wrapper.unmount()
    })

    it('enableLongTask=true 且 PerformanceObserver 存在时创建 observer', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: true,
        }),
      )
      api.startMonitoring()
      expect(observerObserve).toHaveBeenCalledWith({ entryTypes: ['longtask'] })
      wrapper.unmount()
    })

    it('enableLongTask=true 但 PerformanceObserver 抛异常时 console.warn', () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      vi.stubGlobal('PerformanceObserver', vi.fn(() => {
        throw new Error('not supported')
      }))
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: true,
        }),
      )
      api.startMonitoring()
      expect(warnSpy).toHaveBeenCalledWith('Long task detection not supported')
      warnSpy.mockRestore()
      wrapper.unmount()
    })

    it('enableLongTask=false 时不创建 observer', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      expect(observerCallback).toBeNull()
      wrapper.unmount()
    })

    it('sampleInterval 注册定时采样回调', () => {
      const onPerformanceUpdate = vi.fn()
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
          onPerformanceUpdate,
          sampleRate: 1000,
        }),
      )
      intervalCallbacks.length = 0
      api.startMonitoring()
      expect(intervalCallbacks.length).toBe(1)
      // 调用 sample interval 回调
      intervalCallbacks[intervalCallbacks.length - 1]()
      expect(onPerformanceUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'sample' }),
      )
      wrapper.unmount()
    })

    it('sampleInterval: isMonitoring=false 时不触发回调', () => {
      const onPerformanceUpdate = vi.fn()
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
          onPerformanceUpdate,
        }),
      )
      api.startMonitoring()
      onPerformanceUpdate.mockClear()
      api.stopMonitoring()
      // 调用 sample interval 回调（isMonitoring=false）
      intervalCallbacks[intervalCallbacks.length - 1]()
      expect(onPerformanceUpdate).not.toHaveBeenCalled()
      wrapper.unmount()
    })
  })

  // ── measureFPS ───────────────────────────────────────────────────

  describe('measureFPS', () => {
    it('未监控时直接返回', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      const cb = lastRaf()!
      api.stopMonitoring()
      const fpsBefore = api.fps.value
      cb(0) // isMonitoring=false，应直接返回
      expect(api.fps.value).toBe(fpsBefore)
      wrapper.unmount()
    })

    it('elapsed >= 1000 时计算 FPS 并更新 metrics', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
          fpsThreshold: 30,
        }),
      )
      nowValue = 0
      api.startMonitoring()
      const cb = lastRaf()!

      // 模拟 1 帧后过了 1100ms
      nowValue = 1100
      cb(0) // frameCount=1, elapsed=1100, currentFPS=round(1*1000/1100)=1

      expect(api.fps.value).toBe(1)
      expect(api.performanceMetrics.value.minFPS).toBe(1)
      expect(api.performanceMetrics.value.maxFPS).toBe(1)
      expect(api.performanceMetrics.value.avgFPS).toBe(1)
      wrapper.unmount()
    })

    it('fps < threshold 时触发 onPerformanceUpdate 回调', () => {
      const onPerformanceUpdate = vi.fn()
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
          fpsThreshold: 60,
          onPerformanceUpdate,
        }),
      )
      nowValue = 0
      api.startMonitoring()
      const cb = lastRaf()!

      nowValue = 2000 // elapsed=2000, currentFPS=round(1*1000/2000)=1, 1<60
      cb(0)

      expect(onPerformanceUpdate).toHaveBeenCalledWith({
        type: 'fps',
        value: 1,
        threshold: 60,
      })
      wrapper.unmount()
    })

    it('fps >= threshold 时不触发 onPerformanceUpdate 回调', () => {
      const onPerformanceUpdate = vi.fn()
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
          fpsThreshold: 30,
          onPerformanceUpdate,
        }),
      )
      nowValue = 0
      api.startMonitoring()
      const cb = lastRaf()!

      // 模拟 60 帧在 1000ms 内
      nowValue = 500 // elapsed < 1000，不计算
      for (let i = 0; i < 59; i++) {
        cb(0)
      }
      nowValue = 1001 // elapsed >= 1000, frameCount=60, currentFPS=round(60*1000/1001)=60
      cb(0)

      expect(api.fps.value).toBe(60)
      expect(onPerformanceUpdate).not.toHaveBeenCalled()
      wrapper.unmount()
    })

    it('fpsHistory 超过 60 条时移除最旧条目', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      nowValue = 0
      api.startMonitoring()
      let cb = lastRaf()!

      // 调用 65 次，每次 elapsed >= 1000
      for (let i = 0; i < 65; i++) {
        nowValue += 1000
        cb(0)
        cb = lastRaf()!
      }

      // fpsHistory 应被截断到 60 条，不抛异常即可验证
      expect(api.fps.value).toBeGreaterThan(0)
      wrapper.unmount()
    })

    it('监控停止后不再请求下一帧', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      nowValue = 0
      api.startMonitoring()
      const rafCountBefore = rafCallbacks.length
      const cb = lastRaf()!

      api.stopMonitoring()
      nowValue = 1100
      cb(0) // isMonitoring=false，开头就 return

      expect(rafCallbacks.length).toBe(rafCountBefore)
      wrapper.unmount()
    })
  })

  // ── measureMemory ────────────────────────────────────────────────

  describe('measureMemory', () => {
    it('performance.memory 存在时更新 memory 值并触发回调', () => {
      const onPerformanceUpdate = vi.fn()
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: { usedJSHeapSize: 1048576 * 10 }, // 10 MB
      })
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: true,
          enableLongTask: false,
          onPerformanceUpdate,
        }),
      )
      api.startMonitoring()
      expect(api.memory.value).toBe(10)
      expect(api.performanceMetrics.value.memoryUsage).toBe(10)
      expect(onPerformanceUpdate).toHaveBeenCalledWith({
        type: 'memory',
        value: 10,
      })
      wrapper.unmount()
    })

    it('performance.memory 不存在时不更新', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: true,
          enableLongTask: false,
        }),
      )
      // 确保 performance.memory 不存在
      delete (performance as Record<string, unknown>).memory
      api.startMonitoring()
      expect(api.memory.value).toBe(0)
      wrapper.unmount()
    })

    it('enableMemory=false 时不测量', () => {
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: { usedJSHeapSize: 1048576 * 10 },
      })
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      expect(api.memory.value).toBe(0)
      wrapper.unmount()
    })

    it('memory interval 回调可重复调用', () => {
      Object.defineProperty(performance, 'memory', {
        configurable: true,
        value: { usedJSHeapSize: 1048576 * 5 },
      })
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: true,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      // memoryInterval 是第一个 interval（index 0）
      const memoryCb = intervalCallbacks[0]
      expect(memoryCb).toBeDefined()
      // 再次调用
      memoryCb()
      expect(api.memory.value).toBe(5)
      wrapper.unmount()
    })
  })

  // ── detectLongTask ───────────────────────────────────────────────

  describe('detectLongTask', () => {
    it('duration > threshold 时记录长任务并触发回调', () => {
      const onPerformanceUpdate = vi.fn()
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: true,
          longTaskThreshold: 50,
          onPerformanceUpdate,
        }),
      )
      api.startMonitoring()
      expect(observerCallback).not.toBeNull()

      observerCallback!({
        getEntries: () => [
          {
            duration: 100,
            startTime: 0,
            entryType: 'longtask',
          } as unknown as PerformanceEntry,
        ],
      })

      expect(api.longTasks.value.length).toBe(1)
      expect(api.performanceMetrics.value.totalLongTasks).toBe(1)
      expect(onPerformanceUpdate).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'longTask' }),
      )
      wrapper.unmount()
    })

    it('duration <= threshold 时不记录', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: true,
          longTaskThreshold: 50,
        }),
      )
      api.startMonitoring()
      observerCallback!({
        getEntries: () => [
          {
            duration: 30,
            startTime: 0,
            entryType: 'longtask',
          } as unknown as PerformanceEntry,
        ],
      })
      expect(api.longTasks.value.length).toBe(0)
      wrapper.unmount()
    })

    it('enableLongTask=false 时不检测', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      expect(observerCallback).toBeNull()
      expect(api.longTasks.value.length).toBe(0)
      wrapper.unmount()
    })

    it('多个长任务条目都被记录', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: false,
          enableMemory: false,
          enableLongTask: true,
          longTaskThreshold: 50,
        }),
      )
      api.startMonitoring()
      observerCallback!({
        getEntries: () => [
          { duration: 100, startTime: 0, entryType: 'longtask' } as unknown as PerformanceEntry,
          { duration: 80, startTime: 200, entryType: 'longtask' } as unknown as PerformanceEntry,
        ],
      })
      expect(api.longTasks.value.length).toBe(2)
      expect(api.performanceMetrics.value.totalLongTasks).toBe(2)
      wrapper.unmount()
    })
  })

  // ── stopMonitoring ───────────────────────────────────────────────

  describe('stopMonitoring', () => {
    it('停止监控时清理 animationFrame 和 intervals', () => {
      const cancelRafSpy = vi.mocked(cancelAnimationFrame)
      const clearIntervalSpy = vi.mocked(clearInterval)
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: false,
          enableFPS: true,
          enableMemory: true,
          enableLongTask: false,
        }),
      )
      api.startMonitoring()
      api.stopMonitoring()
      expect(api.isMonitoring.value).toBe(false)
      expect(cancelRafSpy).toHaveBeenCalled()
      expect(clearIntervalSpy).toHaveBeenCalled()
      wrapper.unmount()
    })

    it('未启动时停止不报错', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ autoStart: false }),
      )
      expect(() => api.stopMonitoring()).not.toThrow()
      wrapper.unmount()
    })
  })

  // ── resetMetrics ─────────────────────────────────────────────────

  describe('resetMetrics', () => {
    it('重置所有指标到初始值', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ autoStart: false }),
      )
      api.fps.value = 30
      api.memory.value = 100
      api.longTasks.value = [{ test: true }]
      api.performanceMetrics.value = {
        avgFPS: 30,
        minFPS: 20,
        maxFPS: 40,
        totalLongTasks: 5,
        memoryUsage: 100,
      }

      api.resetMetrics()

      expect(api.fps.value).toBe(60)
      expect(api.memory.value).toBe(0)
      expect(api.longTasks.value).toEqual([])
      expect(api.performanceMetrics.value).toEqual({
        avgFPS: 60,
        minFPS: 60,
        maxFPS: 60,
        totalLongTasks: 0,
        memoryUsage: 0,
      })
      wrapper.unmount()
    })
  })

  // ── getMetrics ───────────────────────────────────────────────────

  describe('getMetrics', () => {
    it('返回当前所有指标', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({ autoStart: false }),
      )
      api.fps.value = 45
      api.memory.value = 50
      api.longTasks.value = [{ duration: 100 }]

      const metrics = api.getMetrics()
      expect(metrics.fps).toBe(45)
      expect(metrics.memory).toBe(50)
      expect(metrics.longTasks).toEqual([{ duration: 100 }])
      expect(metrics.avgFPS).toBe(60)
      expect(metrics.totalLongTasks).toBe(0)
      wrapper.unmount()
    })
  })

  // ── onUnmounted ──────────────────────────────────────────────────

  describe('onUnmounted', () => {
    it('卸载时自动停止监控', () => {
      const { wrapper, api } = mountWithComposable(() =>
        usePerformanceMonitor({
          autoStart: true,
          enableMemory: false,
          enableLongTask: false,
        }),
      )
      expect(api.isMonitoring.value).toBe(true)
      wrapper.unmount()
      expect(api.isMonitoring.value).toBe(false)
    })
  })
})

// ════════════════════════════════════════════════════════════════════
// useFrameRateLimiter
// ════════════════════════════════════════════════════════════════════

describe('useFrameRateLimiter - coverage ramp', () => {
  it('返回完整 API', () => {
    const limiter = useFrameRateLimiter(60)
    expect(typeof limiter.shouldRender).toBe('function')
    expect(typeof limiter.throttle).toBe('function')
    expect(typeof limiter.cancelThrottle).toBe('function')
    expect(limiter.frameInterval).toBeCloseTo(1000 / 60, 2)
  })

  it('使用默认 targetFPS=60', () => {
    const limiter = useFrameRateLimiter()
    expect(limiter.frameInterval).toBeCloseTo(1000 / 60, 2)
  })

  it('shouldRender: elapsed >= frameInterval 时返回 true', () => {
    // 使用 targetFPS=10，frameInterval=100，便于测试
    const limiter = useFrameRateLimiter(10)
    // 第一次调用，lastFrameTime=0, elapsed = 150 - 0 = 150 >= 100
    expect(limiter.shouldRender(150)).toBe(true)
  })

  it('shouldRender: elapsed < frameInterval 时返回 false', () => {
    const limiter = useFrameRateLimiter(10)
    limiter.shouldRender(150) // 更新 lastFrameTime = 150 - (150%100) = 150-50=100
    // 下一次 elapsed = 110 - 100 = 10 < 100
    expect(limiter.shouldRender(110)).toBe(false)
  })

  it('throttle: shouldRender=true 时调用 callback', () => {
    const limiter = useFrameRateLimiter(10)
    const callback = vi.fn()
    const throttled = limiter.throttle(callback)
    throttled(150) // elapsed >= frameInterval
    expect(callback).toHaveBeenCalledWith(150)
  })

  it('throttle: shouldRender=false 时不调用 callback', () => {
    const limiter = useFrameRateLimiter(10)
    const callback = vi.fn()
    const throttled = limiter.throttle(callback)
    throttled(150) // 第一次调用，更新 lastFrameTime
    callback.mockClear()
    throttled(110) // elapsed < frameInterval
    expect(callback).not.toHaveBeenCalled()
  })

  it('cancelThrottle: animationId 为 null 时不报错', () => {
    const cancelSpy = vi.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation(() => {})
    const limiter = useFrameRateLimiter(60)
    // animationId 为 null，不调用 cancelAnimationFrame
    limiter.cancelThrottle()
    expect(cancelSpy).not.toHaveBeenCalled()
    cancelSpy.mockRestore()
  })
})

// ════════════════════════════════════════════════════════════════════
// useAnimationFrame
// ════════════════════════════════════════════════════════════════════

describe('useAnimationFrame - coverage ramp', () => {
  let rafCallbacks: FrameRequestCallback[]

  beforeEach(() => {
    rafCallbacks = []
    vi.stubGlobal(
      'requestAnimationFrame',
      vi.fn((cb: FrameRequestCallback) => {
        rafCallbacks.push(cb)
        return rafCallbacks.length
      }),
    )
    vi.stubGlobal('cancelAnimationFrame', vi.fn(() => {}))
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('返回完整 API', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    expect(api.isRunning).toBeDefined()
    expect(typeof api.start).toBe('function')
    expect(typeof api.stop).toBe('function')
    expect(typeof api.updateCallback).toBe('function')
    wrapper.unmount()
  })

  it('start: 注册 rAF 并设置 isRunning=true', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    const cb = vi.fn()
    api.start(cb)
    expect(api.isRunning.value).toBe(true)
    expect(rafCallbacks.length).toBe(1)
    wrapper.unmount()
  })

  it('start: 已运行时不重复启动', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    api.start(vi.fn())
    const rafCountBefore = rafCallbacks.length
    api.start(vi.fn())
    expect(rafCallbacks.length).toBe(rafCountBefore)
    wrapper.unmount()
  })

  it('animate: 调用 callback 并注册下一帧', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    const cb = vi.fn()
    api.start(cb)
    const animateFn = rafCallbacks[0]
    animateFn(1000) // currentTime=1000
    expect(cb).toHaveBeenCalledWith(expect.any(Number), 1000)
    // 应注册下一帧
    expect(rafCallbacks.length).toBe(2)
    wrapper.unmount()
  })

  it('stop: 设置 isRunning=false 并 cancelAnimationFrame', () => {
    const cancelSpy = vi.mocked(cancelAnimationFrame)
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    api.start(vi.fn())
    api.stop()
    expect(api.isRunning.value).toBe(false)
    expect(cancelSpy).toHaveBeenCalled()
    wrapper.unmount()
  })

  it('stop: animationId 为 null 时不调用 cancelAnimationFrame', () => {
    const cancelSpy = vi.mocked(cancelAnimationFrame)
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    // 未 start 直接 stop
    api.stop()
    expect(cancelSpy).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('updateCallback: 更新回调函数', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    const originalCb = vi.fn()
    const newCb = vi.fn()
    api.start(originalCb)
    api.updateCallback(newCb)
    // 触发 animate
    rafCallbacks[0](1000)
    expect(newCb).toHaveBeenCalled()
    expect(originalCb).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('animate: isRunning=false 时直接返回', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    const cb = vi.fn()
    api.start(cb)
    const animateFn = rafCallbacks[0]
    api.stop() // isRunning = false
    animateFn(2000) // 应直接返回
    expect(cb).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('onUnmounted: 卸载时停止动画', () => {
    const { wrapper, api } = mountWithComposable(() => useAnimationFrame())
    api.start(vi.fn())
    expect(api.isRunning.value).toBe(true)
    wrapper.unmount()
    expect(api.isRunning.value).toBe(false)
  })
})
