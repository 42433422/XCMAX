import { describe, expect, it } from 'vitest'
import { formatMetric, parseMarketOverviewStats } from './marketOverviewMetrics'

describe('parseMarketOverviewStats', () => {
  it('reads catalog and user business metrics', () => {
    const stats = parseMarketOverviewStats({
      ok: true,
      total_catalog_items: 532,
      total_users: 21,
    })
    expect(stats.ok).toBe(true)
    expect(stats.totalCatalogItems).toBe(532)
    expect(stats.totalUsers).toBe(21)
    expect(formatMetric(stats.totalCatalogItems)).toBe('532')
  })

  it('marks invalid counts as unverified', () => {
    const stats = parseMarketOverviewStats({ ok: true, total_catalog_items: -1, total_users: 'x' })
    expect(stats.totalCatalogItems).toBeNull()
    expect(stats.totalUsers).toBeNull()
    expect(formatMetric(null)).toBe('待核实')
  })
})
