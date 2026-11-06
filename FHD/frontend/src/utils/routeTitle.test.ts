import { describe, expect, it } from 'vitest'
import { committedRouteTitle } from './routeTitle'

describe('committedRouteTitle', () => {
  it('names customers and products from the route that committed', () => {
    expect(committedRouteTitle({ fullPath: '/customers', meta: { title: '客户管理' } }, undefined, '/customers')).toBe('客户管理 - XCAGI')
    expect(committedRouteTitle({ fullPath: '/products', meta: { title: '产品管理' } }, undefined, '/products')).toBe('产品管理 - XCAGI')
  })

  it('ignores an aborted navigation so a customer page cannot be titled as products', () => {
    const aborted = committedRouteTitle(
      { fullPath: '/products', meta: { title: '产品管理' } },
      new Error('Navigation aborted'),
      '/customers',
    )
    expect(aborted).toBeNull()
  })

  it('ignores a title whose route is no longer current', () => {
    expect(committedRouteTitle({ fullPath: '/products', meta: { title: '产品管理' } }, undefined, '/customers')).toBeNull()
  })
})
