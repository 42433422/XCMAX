import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { usePerformanceMonitor } from './usePerformanceMonitor'

describe('usePerformanceMonitor', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts and stops monitoring', () => {
    const onUpdate = vi.fn()
    const monitor = usePerformanceMonitor({
      autoStart: false,
      onPerformanceUpdate: onUpdate,
      sampleRate: 100,
    })
    expect(monitor.isMonitoring.value).toBe(false)
    monitor.startMonitoring()
    expect(monitor.isMonitoring.value).toBe(true)
    monitor.stopMonitoring()
    expect(monitor.isMonitoring.value).toBe(false)
  })

  it('autoStart option is accepted', () => {
    const monitor = usePerformanceMonitor({ autoStart: false, sampleRate: 500 })
    monitor.startMonitoring()
    expect(monitor.isMonitoring.value).toBe(true)
    monitor.stopMonitoring()
  })

  it('resetMetrics clears history', () => {
    const monitor = usePerformanceMonitor({ autoStart: false })
    monitor.resetMetrics()
    expect(monitor.performanceMetrics.value.avgFPS).toBe(60)
    expect(monitor.longTasks.value).toHaveLength(0)
  })

  it('getMetrics returns snapshot', () => {
    const monitor = usePerformanceMonitor({ autoStart: false })
    const report = monitor.getMetrics()
    expect(report).toHaveProperty('fps')
    expect(report).toHaveProperty('memory')
    expect(report).toHaveProperty('avgFPS')
  })

  it('exposes fps and memory refs', () => {
    const monitor = usePerformanceMonitor({ autoStart: false })
    expect(monitor.fps.value).toBe(60)
    expect(typeof monitor.memory.value).toBe('number')
  })
})
