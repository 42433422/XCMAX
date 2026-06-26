import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useDigitalRain } from './useDigitalRain'

describe('useDigitalRain', () => {
  let canvasRef: ReturnType<typeof ref<HTMLCanvasElement | null>>
  let mockCtx: ReturnType<typeof vi.fn>

  beforeEach(() => {
    mockCtx = vi.fn(() => null) as any
    canvasRef = ref(null)
  })

  it('returns expected API', () => {
    const rain = useDigitalRain(canvasRef)
    expect(rain).toHaveProperty('isRunning')
    expect(rain).toHaveProperty('start')
    expect(rain).toHaveProperty('stop')
    expect(rain).toHaveProperty('setWorkMode')
    expect(rain).toHaveProperty('resize')
    expect(rain).toHaveProperty('clear')
  })

  it('isRunning is false initially', () => {
    const rain = useDigitalRain(canvasRef)
    expect(rain.isRunning.value).toBe(false)
  })

  it('start does nothing without canvas', () => {
    const rain = useDigitalRain(canvasRef)
    rain.start()
    expect(rain.isRunning.value).toBe(false)
  })

  it('stop does not throw without canvas', () => {
    const rain = useDigitalRain(canvasRef)
    expect(() => rain.stop()).not.toThrow()
  })

  it('setWorkMode toggles work mode', () => {
    const rain = useDigitalRain(canvasRef)
    rain.setWorkMode(true)
    // No direct way to check internal state, but should not throw
    rain.setWorkMode(false)
  })

  it('resize does not throw without canvas', () => {
    const rain = useDigitalRain(canvasRef)
    expect(() => rain.resize()).not.toThrow()
  })

  it('clear does not throw without canvas', () => {
    const rain = useDigitalRain(canvasRef)
    expect(() => rain.clear()).not.toThrow()
  })

  it('start initializes canvas context when canvas is available', () => {
    const mockCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => ({
        fillStyle: '',
        fillRect: vi.fn(),
        font: '',
        fillText: vi.fn(),
        clearRect: vi.fn(),
      })),
    }
    canvasRef.value = mockCanvas as any

    const rain = useDigitalRain(canvasRef, { width: 800, height: 600 })
    rain.start()
    expect(mockCanvas.getContext).toHaveBeenCalledWith('2d')
    expect(rain.isRunning.value).toBe(true)
    rain.stop()
  })

  it('uses custom fontSize and chars options', () => {
    const mockCanvas = {
      width: 0,
      height: 0,
      getContext: vi.fn(() => ({
        fillStyle: '',
        fillRect: vi.fn(),
        font: '',
        fillText: vi.fn(),
        clearRect: vi.fn(),
      })),
    }
    canvasRef.value = mockCanvas as any

    const rain = useDigitalRain(canvasRef, { fontSize: 20, chars: ['a', 'b', 'c'] })
    rain.start()
    expect(rain.isRunning.value).toBe(true)
    rain.stop()
  })

  it('stop clears canvas when context is available', () => {
    const mockCtx2d = {
      fillStyle: '',
      fillRect: vi.fn(),
      font: '',
      fillText: vi.fn(),
      clearRect: vi.fn(),
    }
    const mockCanvas = {
      width: 800,
      height: 600,
      getContext: vi.fn(() => mockCtx2d),
    }
    canvasRef.value = mockCanvas as any

    const rain = useDigitalRain(canvasRef)
    rain.start()
    rain.stop()
    expect(mockCtx2d.fillRect).toHaveBeenCalled()
    expect(mockCtx2d.clearRect).toHaveBeenCalled()
  })
})
