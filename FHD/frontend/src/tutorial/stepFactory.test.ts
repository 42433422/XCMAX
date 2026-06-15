import { describe, it, expect } from 'vitest'
import {
  createStep,
  advancedSidebarNavStep,
  advancedPageFeaturesStep,
  pageHighlightToStep,
  fallbackPageObserveStep,
} from './stepFactory'

describe('tutorial stepFactory', () => {
  it('createStep defaults excludeInPro to true', () => {
    expect(createStep({ id: 'a', title: 't', description: 'd', actionType: 'observe' }).excludeInPro).toBe(true)
    expect(
      createStep({ id: 'a', title: 't', description: 'd', actionType: 'observe', excludeInPro: false }).excludeInPro,
    ).toBe(false)
  })

  it('advancedSidebarNavStep sanitizes id and sets click', () => {
    const s = advancedSidebarNavStep('chat/view', '标题', '描述')
    expect(s.id).toBe('nav-chat-view')
    expect(s.actionType).toBe('click')
    expect(s.excludeInPro).toBe(false)
  })

  it('advancedPageFeaturesStep falls back highlight to target', () => {
    const s = advancedPageFeaturesStep('x', 'orders', 't', 'd', '#sel')
    expect(s.id).toBe('page-orders-x')
    expect(s.highlightSelector).toBe('#sel')
    const s2 = advancedPageFeaturesStep('y', 'orders', 't', 'd', '#sel', '#hl')
    expect(s2.highlightSelector).toBe('#hl')
  })

  it('pageHighlightToStep maps highlight object', () => {
    const s = pageHighlightToStep('products', {
      idSuffix: 'kpi',
      title: 'KPI',
      description: 'desc',
      targetSelector: '.kpi',
    })
    expect(s.id).toBe('page-products-kpi')
    expect(s.routeName).toBe('products')
  })

  it('fallbackPageObserveStep builds overview step', () => {
    const s = fallbackPageObserveStep('orders', '订单')
    expect(s.id).toBe('page-orders-overview')
    expect(s.title).toContain('订单')
    expect(s.actionType).toBe('observe')
  })
})
