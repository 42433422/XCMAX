import { describe, it, expect, vi } from 'vitest'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
    delete: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { kittenApi } from './kitten'
import { api } from './core'

describe('kittenApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getBusinessSnapshot calls api.get', async () => {
    await kittenApi.getBusinessSnapshot()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/business-snapshot')
  })

  it('getCharts calls api.get', async () => {
    await kittenApi.getCharts()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/all')
  })

  it('getRevenueChart calls api.get with default months', async () => {
    await kittenApi.getRevenueChart()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/revenue?months=6')
  })

  it('getRevenueChart calls api.get with custom months', async () => {
    await kittenApi.getRevenueChart(12)
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/revenue?months=12')
  })

  it('getProductChart calls api.get', async () => {
    await kittenApi.getProductChart()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/products')
  })

  it('getCustomerChart calls api.get', async () => {
    await kittenApi.getCustomerChart()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/customers')
  })

  it('getProfitChart calls api.get with default months', async () => {
    await kittenApi.getProfitChart()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/profit?months=6')
  })

  it('getInventoryChart calls api.get', async () => {
    await kittenApi.getInventoryChart()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/charts/inventory')
  })

  it('generateFinancialReport calls api.post with default metadata', async () => {
    await kittenApi.generateFinancialReport()
    expect(api.post).toHaveBeenCalledWith('/api/ai/kitten/financial/report', { metadata: {} })
  })

  it('generateFinancialReport calls api.post with custom metadata', async () => {
    await kittenApi.generateFinancialReport({ period: 'Q1' })
    expect(api.post).toHaveBeenCalledWith('/api/ai/kitten/financial/report', { metadata: { period: 'Q1' } })
  })

  it('exportReport calls api.post with blob responseType', async () => {
    await kittenApi.exportReport({ format: 'pdf' })
    expect(api.post).toHaveBeenCalledWith('/api/ai/kitten/report/export', { format: 'pdf' }, { responseType: 'blob' })
  })

  it('getSavedAnalyses calls api.get without type', async () => {
    await kittenApi.getSavedAnalyses()
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/saved/list')
  })

  it('getSavedAnalyses calls api.get with type', async () => {
    await kittenApi.getSavedAnalyses('financial')
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/saved/list?type=financial')
  })

  it('getSavedAnalysis calls api.get with id', async () => {
    await kittenApi.getSavedAnalysis('analysis-1')
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/saved/analysis-1')
  })

  it('exportSavedAnalysis calls api.get with blob responseType', async () => {
    await kittenApi.exportSavedAnalysis('analysis-1')
    expect(api.get).toHaveBeenCalledWith('/api/ai/kitten/saved/analysis-1/export', { responseType: 'blob' })
  })

  it('deleteSavedAnalysis calls api.delete with id', async () => {
    await kittenApi.deleteSavedAnalysis('analysis-1')
    expect(api.delete).toHaveBeenCalledWith('/api/ai/kitten/saved/analysis-1')
  })
})
