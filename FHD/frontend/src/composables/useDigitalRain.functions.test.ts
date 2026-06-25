import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref, nextTick } from 'vue'
import { useDigitalRain } from './useDigitalRain'

function createMockCtx() {
  return {
    fillStyle: '',
    font: '',
    fillRect: vi.fn(),
    fillText: vi.fn(),
    clearRect: vi.fn(),
  } as unknown as CanvasRenderingContext2D
}

function createCanvas(ctx: CanvasRenderingContext2D): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = 200
  canvas.height = 100
  vi.spyOn(canvas, 'getContext').mockReturnValue(ctx)
  return canvas
}

describe('useDigitalRain', () => {
  let rafSpy: ReturnType<typeof vi.fn>
  let cancelRafSpy: ReturnType<typeof vi.fn>

  beforeEach(() => {
    rafSpy = vi.fn((cb: FrameRequestCallback) => {
      // Don't actually invoke to prevent infinite loop
      return 1
    })
    cancelRafSpy = vi.fn()
    vi.stubGlobal('requestAnimationFrame', rafSpy)
    vi.stubGlobal('cancelAnimationFrame', cancelRafSpy)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  describe('start', () => {
    it('initializes canvas context and starts animation', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, isRunning } = useDigitalRain(canvasRef, {
        width: 200,
        height: 100,
        fontSize: 10,
      })

      start()
      expect(isRunning.value).toBe(true)
      expect(rafSpy).toHaveBeenCalled()
    })

    it('does nothing when canvas ref is null', () => {
      const canvasRef = ref<HTMLCanvasElement | null>(null)
      const { start, isRunning } = useDigitalRain(canvasRef)
      start()
      expect(isRunning.value).toBe(false)
      expect(rafSpy).not.toHaveBeenCalled()
    })

    it('does nothing when getContext returns null', () => {
      const canvas = document.createElement('canvas')
      vi.spyOn(canvas, 'getContext').mockReturnValue(null)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, isRunning } = useDigitalRain(canvasRef)
      start()
      expect(isRunning.value).toBe(false)
    })

    it('does not restart if already running', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, isRunning } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      start()
      const firstCallCount = rafSpy.mock.calls.length
      start()
      expect(isRunning.value).toBe(true)
      expect(rafSpy.mock.calls.length).toBe(firstCallCount)
    })

    it('uses default fontSize 14 when not provided', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start } = useDigitalRain(canvasRef, { width: 280, height: 100 })
      start()
      // 280 / 14 = 20 columns
      expect(ctx.font).toContain('14px')
    })

    it('uses default chars [0, 1] when not provided', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start } = useDigitalRain(canvasRef, { width: 100, height: 100 })
      start()
      // draw was called, fillText should have been called with '0' or '1'
      expect(ctx.fillText).toHaveBeenCalled()
    })

    it('uses window dimensions when width/height not provided', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const originalInnerWidth = window.innerWidth
      const originalInnerHeight = window.innerHeight
      Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: 768, configurable: true })
      const { start } = useDigitalRain(canvasRef)
      start()
      expect(canvas.width).toBe(1024)
      expect(canvas.height).toBe(768)
      Object.defineProperty(window, 'innerWidth', { value: originalInnerWidth, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: originalInnerHeight, configurable: true })
    })
  })

  describe('stop', () => {
    it('sets isRunning to false', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, stop, isRunning } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      start()
      stop()
      expect(isRunning.value).toBe(false)
    })

    it('cancels animation frame when stopping', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, stop } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      start()
      stop()
      expect(cancelRafSpy).toHaveBeenCalledWith(1)
    })

    it('clears canvas when stopping after start', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, stop } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      start()
      stop()
      expect(ctx.fillRect).toHaveBeenCalled()
      expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, 100, 100)
    })

    it('does not throw when stopping without starting', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { stop } = useDigitalRain(canvasRef, { width: 100, height: 100 })
      expect(() => stop()).not.toThrow()
    })
  })

  describe('setWorkMode', () => {
    it('sets work mode to true (affects draw color)', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, setWorkMode } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      setWorkMode(true)
      start()
      // In work mode, fillStyle should be red
      expect(ctx.fillStyle).toBe('#ff0000')
    })

    it('sets work mode to false (default green)', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, setWorkMode } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      setWorkMode(false)
      start()
      expect(ctx.fillStyle).toBe('#0f0')
    })
  })

  describe('resize', () => {
    it('resizes canvas to options width/height', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { resize } = useDigitalRain(canvasRef, { width: 300, height: 200, fontSize: 10 })

      resize()
      expect(canvas.width).toBe(300)
      expect(canvas.height).toBe(200)
    })

    it('falls back to window dimensions when no options', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const originalInnerWidth = window.innerWidth
      const originalInnerHeight = window.innerHeight
      Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true })
      const { resize } = useDigitalRain(canvasRef)
      resize()
      expect(canvas.width).toBe(800)
      expect(canvas.height).toBe(600)
      Object.defineProperty(window, 'innerWidth', { value: originalInnerWidth, configurable: true })
      Object.defineProperty(window, 'innerHeight', { value: originalInnerHeight, configurable: true })
    })

    it('does nothing when canvas ref is null', () => {
      const canvasRef = ref<HTMLCanvasElement | null>(null)
      const { resize } = useDigitalRain(canvasRef, { width: 300, height: 200 })
      expect(() => resize()).not.toThrow()
    })
  })

  describe('clear', () => {
    it('fills canvas with black when not in work mode', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, clear } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      // start() initializes ctx.value; clear() requires ctx.value to be set
      start()
      clear()
      expect(ctx.fillStyle).toBe('rgba(0, 0, 0, 1)')
      expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 100, 100)
    })

    it('fills canvas with red when in work mode', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start, setWorkMode, clear } = useDigitalRain(canvasRef, { width: 100, height: 100 })

      start()
      setWorkMode(true)
      clear()
      expect(ctx.fillStyle).toBe('rgba(255, 0, 0, 1)')
      expect(ctx.fillRect).toHaveBeenCalledWith(0, 0, 100, 100)
    })

    it('does nothing when ctx is null (not started)', () => {
      const canvas = document.createElement('canvas')
      vi.spyOn(canvas, 'getContext').mockReturnValue(null)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { clear } = useDigitalRain(canvasRef, { width: 100, height: 100 })
      expect(() => clear()).not.toThrow()
    })

    it('does nothing when canvas ref is null', () => {
      const canvasRef = ref<HTMLCanvasElement | null>(null)
      const { clear } = useDigitalRain(canvasRef, { width: 100, height: 100 })
      expect(() => clear()).not.toThrow()
    })
  })

  describe('custom chars', () => {
    it('uses provided chars array', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start } = useDigitalRain(canvasRef, {
        width: 100,
        height: 100,
        chars: ['A', 'B', 'C'],
      })
      start()
      // fillText called with one of A, B, C
      const calls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls
      expect(calls.length).toBeGreaterThan(0)
      for (const call of calls) {
        expect(['A', 'B', 'C']).toContain(call[0])
      }
    })
  })

  describe('custom fontSize', () => {
    it('uses provided fontSize for column count', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start } = useDigitalRain(canvasRef, {
        width: 200,
        height: 100,
        fontSize: 20,
      })
      start()
      expect(ctx.font).toContain('20px')
    })
  })

  describe('draw behavior', () => {
    it('calls fillRect to fade and fillText for each column', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { start } = useDigitalRain(canvasRef, {
        width: 100,
        height: 100,
        fontSize: 10,
      })
      start()
      // 100 / 10 = 10 columns, fillText called once per column
      expect(ctx.fillRect).toHaveBeenCalled()
      expect(ctx.fillText).toHaveBeenCalled()
      const fillTextCalls = (ctx.fillText as ReturnType<typeof vi.fn>).mock.calls
      expect(fillTextCalls.length).toBe(10)
    })
  })

  describe('return value', () => {
    it('exposes isRunning, start, stop, setWorkMode, resize, clear', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const result = useDigitalRain(canvasRef, { width: 100, height: 100 })

      expect(result).toHaveProperty('isRunning')
      expect(result).toHaveProperty('start')
      expect(result).toHaveProperty('stop')
      expect(result).toHaveProperty('setWorkMode')
      expect(result).toHaveProperty('resize')
      expect(result).toHaveProperty('clear')
      expect(typeof result.start).toBe('function')
      expect(typeof result.stop).toBe('function')
      expect(typeof result.setWorkMode).toBe('function')
      expect(typeof result.resize).toBe('function')
      expect(typeof result.clear).toBe('function')
    })

    it('isRunning is reactive ref starting as false', () => {
      const ctx = createMockCtx()
      const canvas = createCanvas(ctx)
      const canvasRef = ref<HTMLCanvasElement | null>(canvas)
      const { isRunning } = useDigitalRain(canvasRef, { width: 100, height: 100 })
      expect(isRunning.value).toBe(false)
    })
  })
})
