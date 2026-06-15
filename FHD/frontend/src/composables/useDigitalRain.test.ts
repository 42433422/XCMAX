import { describe, expect, it, vi, afterEach } from 'vitest'
import { ref } from 'vue'
import { useDigitalRain } from './useDigitalRain'

describe('useDigitalRain', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('start/stop lifecycle without hanging', async () => {
    const canvas = document.createElement('canvas')
    canvas.width = 200
    canvas.height = 100
    const ctx = canvas.getContext('2d')
    vi.spyOn(canvas, 'getContext').mockReturnValue(ctx)

    const canvasRef = ref<HTMLCanvasElement | null>(canvas)
    const { stop, isRunning, setWorkMode } = useDigitalRain(canvasRef, {
      width: 200,
      height: 100,
      fontSize: 10,
    })

    setWorkMode(true)
    stop()
    expect(isRunning.value).toBe(false)
  })
})
