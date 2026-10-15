import { describe, expect, it } from 'vitest'
import {
  estimateLaborCostSavedCny,
  formatCny,
  VALUE_STATS_COST_PER_TASK_MAX_CNY,
  VALUE_STATS_COST_PER_TASK_MIN_CNY,
} from './valueStats'

describe('estimateLaborCostSavedCny', () => {
  it('常量口径为 1.9–5.8 元/单', () => {
    expect(VALUE_STATS_COST_PER_TASK_MIN_CNY).toBe(1.9)
    expect(VALUE_STATS_COST_PER_TASK_MAX_CNY).toBe(5.8)
  })

  it('非法输入按 0 处理', () => {
    expect(estimateLaborCostSavedCny(0)).toBe(0)
    expect(estimateLaborCostSavedCny(-3)).toBe(0)
    expect(estimateLaborCostSavedCny(Number.NaN)).toBe(0)
    expect(estimateLaborCostSavedCny('abc')).toBe(0)
    expect(estimateLaborCostSavedCny(null)).toBe(0)
  })

  it('1 单成本落在 1.9–5.8 区间，且结果确定（刷新不抖动）', () => {
    expect(estimateLaborCostSavedCny(1)).toBe(estimateLaborCostSavedCny(1))
    expect(estimateLaborCostSavedCny(1)).toBeGreaterThanOrEqual(1.9)
    expect(estimateLaborCostSavedCny(1)).toBeLessThanOrEqual(5.8)
  })

  it('任务数递增时总额单调递增，每次增量都在 1.9–5.8 内', () => {
    let prev = estimateLaborCostSavedCny(1)
    for (let n = 2; n <= 50; n += 1) {
      const current = estimateLaborCostSavedCny(n)
      const delta = current - prev
      expect(delta).toBeGreaterThanOrEqual(VALUE_STATS_COST_PER_TASK_MIN_CNY)
      expect(delta).toBeLessThanOrEqual(VALUE_STATS_COST_PER_TASK_MAX_CNY)
      prev = current
    }
  })

  it('总额始终在 [count×1.9, count×5.8] 区间内', () => {
    for (const n of [1, 7, 60, 200, 1000]) {
      const total = estimateLaborCostSavedCny(n)
      expect(total).toBeGreaterThanOrEqual(n * VALUE_STATS_COST_PER_TASK_MIN_CNY)
      expect(total).toBeLessThanOrEqual(n * VALUE_STATS_COST_PER_TASK_MAX_CNY)
    }
  })

  it('小数任务数向下取整', () => {
    expect(estimateLaborCostSavedCny(2.9)).toBe(estimateLaborCostSavedCny(2))
  })
})

describe('formatCny', () => {
  it('千分位格式化', () => {
    expect(formatCny(0)).toBe('¥0')
    expect(formatCny(200)).toBe('¥200')
    expect(formatCny(1234)).toBe('¥1,234')
    expect(formatCny(1234567)).toBe('¥1,234,567')
  })
})
