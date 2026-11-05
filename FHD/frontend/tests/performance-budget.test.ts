import { describe, expect, it } from 'vitest'
import { assertWithinBudget, latencyPercentile, positiveBudget } from '../e2e/performance-budget'

describe('performance gate negative controls', () => {
  it('rejects delays that previously passed the relaxed ready and health budgets', () => {
    expect(() => assertWithinBudget(3001, 3000, 'ready')).toThrow()
    expect(() => assertWithinBudget(501, 500, 'health')).toThrow()
    expect(() => assertWithinBudget(23000, 3000, 'ready')).toThrow()
    expect(() => assertWithinBudget(3000, 500, 'health')).toThrow()
    expect(() => assertWithinBudget(500, 500, 'health')).not.toThrow()
  })

  it('fails closed for invalid budgets and invalid observations', () => {
    for (const value of ['0', '-1', 'Infinity', 'bad']) expect(() => positiveBudget(value, 500)).toThrow()
    for (const value of [NaN, Infinity, -1]) expect(() => assertWithinBudget(value, 500, 'health')).toThrow()
    expect(positiveBudget(undefined, 500)).toBe(500)
  })

  it('computes percentiles from observations and catches a slow tail', () => {
    const samples = [...Array(19).fill(10), 900]
    expect(latencyPercentile(samples, 95)).toBe(10)
    expect(latencyPercentile(samples, 99)).toBe(900)
    expect(() => assertWithinBudget(latencyPercentile(samples, 99), 500, 'P99')).toThrow()
    expect(() => latencyPercentile([10], 95)).toThrow()
    expect(() => latencyPercentile([...Array(19).fill(10), NaN], 95)).toThrow()
  })
})
