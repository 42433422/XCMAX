import { describe, expect, it } from 'vitest'
import { getThreshold, loadAdaptiveThresholds } from '../adaptive-thresholds.js'

describe('adaptive-thresholds', () => {
  it('loads defaults with floor/ceiling', () => {
    const all = loadAdaptiveThresholds('')
    expect(all.crash_threshold.value).toBe(3)
    expect(all.crash_threshold.floor).toBe(2)
    expect(all.crash_threshold.ceiling).toBe(5)
  })

  it('clamps override json into floor/ceiling', () => {
    const json = JSON.stringify({
      thresholds: {
        crash_threshold: { value: 1, floor: 2, ceiling: 5 },
        disk_clean_threshold: { value: 95, floor: 60, ceiling: 90 },
      },
    })
    expect(getThreshold('crash_threshold', json).value).toBe(2)
    expect(getThreshold('disk_clean_threshold', json).value).toBe(90)
  })
})
