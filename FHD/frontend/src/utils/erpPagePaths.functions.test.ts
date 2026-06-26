/**
 * erpPagePaths 函数覆盖率补齐测试
 * 目标：覆盖 pushErpPage、resolveErpPagePath 边界、resolveErpPageRedirectForRouteName 边界
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  resolveErpPagePath,
  resolveErpPageRedirectForRouteName,
  pushErpPage,
  useErpModPages,
} from './erpPagePaths'
import type { Router } from 'vue-router'

describe('erpPagePaths – useErpModPages', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('facade 关闭时返回 false', () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    expect(useErpModPages()).toBe(false)
  })

  it('facade 开启时返回 true', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(useErpModPages()).toBe(true)
  })

  it('localStorage 无值时返回 false', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(useErpModPages()).toBe(false)
  })
})

describe('erpPagePaths – resolveErpPagePath 边界', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('facade 关闭时原样返回路径', () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    expect(resolveErpPagePath('/products')).toBe('/products')
    expect(resolveErpPagePath('/unknown')).toBe('/unknown')
  })

  it('facade 关闭时无前导斜杠的路径添加斜杠', () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    expect(resolveErpPagePath('products')).toBe('/products')
  })

  it('facade 开启时映射已知路径到 Mod 路径', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPagePath('/products')).toBe('/mod/xcagi-erp-domain-bridge/products')
    expect(resolveErpPagePath('/customers')).toBe('/mod/xcagi-erp-domain-bridge/customers')
    expect(resolveErpPagePath('/orders')).toBe('/mod/xcagi-erp-domain-bridge/orders')
    expect(resolveErpPagePath('/orders/create')).toBe('/mod/xcagi-erp-domain-bridge/orders/create')
    expect(resolveErpPagePath('/shipment-records')).toBe('/mod/xcagi-erp-domain-bridge/shipment-records')
    expect(resolveErpPagePath('/materials')).toBe('/mod/xcagi-erp-domain-bridge/materials')
    expect(resolveErpPagePath('/materials-list')).toBe('/mod/xcagi-erp-domain-bridge/materials')
    expect(resolveErpPagePath('/traditional-mode')).toBe('/mod/xcagi-erp-domain-bridge/traditional-mode')
    expect(resolveErpPagePath('/business-docking')).toBe('/mod/xcagi-erp-domain-bridge/template-preview')
    expect(resolveErpPagePath('/data-sources')).toBe('/mod/xcagi-erp-domain-bridge/data-sources')
    expect(resolveErpPagePath('/print')).toBe('/mod/xcagi-erp-domain-bridge/print')
    expect(resolveErpPagePath('/printer-list')).toBe('/mod/xcagi-erp-domain-bridge/printer-list')
    expect(resolveErpPagePath('/template-preview')).toBe('/mod/xcagi-erp-domain-bridge/template-preview')
    expect(resolveErpPagePath('/label-editor')).toBe('/mod/xcagi-erp-domain-bridge/label-editor')
    expect(resolveErpPagePath('/purchase')).toBe('/mod/xcagi-erp-domain-bridge/purchase')
    expect(resolveErpPagePath('/inventory')).toBe('/mod/xcagi-erp-domain-bridge/inventory')
    expect(resolveErpPagePath('/batch-analyze')).toBe('/mod/xcagi-erp-domain-bridge/batch-analyze')
  })

  it('facade 开启时未知路径原样返回', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPagePath('/unknown')).toBe('/unknown')
    expect(resolveErpPagePath('/custom-path')).toBe('/custom-path')
  })

  it('facade 开启时 wechat-contacts 添加 source 参数', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    const result = resolveErpPagePath('/wechat-contacts')
    expect(result).toContain('/mod/xcagi-erp-domain-bridge/data-sources')
    expect(result).toContain('source=wechat_local_db')
  })

  it('facade 开启时 wechat-contacts 保留已有 query', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    const result = resolveErpPagePath('/wechat-contacts?foo=bar')
    expect(result).toContain('/mod/xcagi-erp-domain-bridge/data-sources')
    expect(result).toContain('foo=bar')
  })

  it('facade 开启时路径带 query 参数时保留', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    const result = resolveErpPagePath('/products?page=1&size=10')
    expect(result).toBe('/mod/xcagi-erp-domain-bridge/products?page=1&size=10')
  })

  it('facade 开启时路径带 hash 时保留', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    const result = resolveErpPagePath('/products#section')
    expect(result).toBe('/mod/xcagi-erp-domain-bridge/products#section')
  })

  it('facade 开启时无前导斜杠的路径也能处理', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPagePath('products')).toBe('/mod/xcagi-erp-domain-bridge/products')
  })
})

describe('erpPagePaths – resolveErpPageRedirectForRouteName 边界', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('facade 关闭时返回 null', () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    expect(resolveErpPageRedirectForRouteName('products')).toBeNull()
    expect(resolveErpPageRedirectForRouteName('unknown')).toBeNull()
  })

  it('facade 开启时未知 routeName 返回 null', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPageRedirectForRouteName('unknown')).toBeNull()
    expect(resolveErpPageRedirectForRouteName('')).toBeNull()
  })

  it('facade 开启时已知 routeName 返回 Mod 路径', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPageRedirectForRouteName('products')).toBe('/mod/xcagi-erp-domain-bridge/products')
    expect(resolveErpPageRedirectForRouteName('customers')).toBe('/mod/xcagi-erp-domain-bridge/customers')
    expect(resolveErpPageRedirectForRouteName('orders')).toBe('/mod/xcagi-erp-domain-bridge/orders')
    expect(resolveErpPageRedirectForRouteName('orders-create')).toBe('/mod/xcagi-erp-domain-bridge/orders/create')
    expect(resolveErpPageRedirectForRouteName('shipment-records')).toBe('/mod/xcagi-erp-domain-bridge/shipment-records')
    expect(resolveErpPageRedirectForRouteName('materials')).toBe('/mod/xcagi-erp-domain-bridge/materials')
    expect(resolveErpPageRedirectForRouteName('materials-list')).toBe('/mod/xcagi-erp-domain-bridge/materials')
    expect(resolveErpPageRedirectForRouteName('traditional-mode')).toBe('/mod/xcagi-erp-domain-bridge/traditional-mode')
    expect(resolveErpPageRedirectForRouteName('business-docking')).toBe('/mod/xcagi-erp-domain-bridge/template-preview')
    expect(resolveErpPageRedirectForRouteName('data-sources')).toBe('/mod/xcagi-erp-domain-bridge/data-sources')
    expect(resolveErpPageRedirectForRouteName('print')).toBe('/mod/xcagi-erp-domain-bridge/print')
    expect(resolveErpPageRedirectForRouteName('printer-list')).toBe('/mod/xcagi-erp-domain-bridge/printer-list')
    expect(resolveErpPageRedirectForRouteName('template-preview')).toBe('/mod/xcagi-erp-domain-bridge/template-preview')
    expect(resolveErpPageRedirectForRouteName('label-editor')).toBe('/mod/xcagi-erp-domain-bridge/label-editor')
    expect(resolveErpPageRedirectForRouteName('purchase')).toBe('/mod/xcagi-erp-domain-bridge/purchase')
    expect(resolveErpPageRedirectForRouteName('inventory')).toBe('/mod/xcagi-erp-domain-bridge/inventory')
    expect(resolveErpPageRedirectForRouteName('batch-analyze')).toBe('/mod/xcagi-erp-domain-bridge/batch-analyze')
  })

  it('facade 开启时 wechat-contacts 添加 source 参数', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveErpPageRedirectForRouteName('wechat-contacts')).toBe(
      '/mod/xcagi-erp-domain-bridge/data-sources?source=wechat_local_db',
    )
  })
})

describe('erpPagePaths – pushErpPage', () => {
  let mockRouter: { push: ReturnType<typeof vi.fn> }

  beforeEach(() => {
    vi.unstubAllGlobals()
    mockRouter = { push: vi.fn().mockResolvedValue(undefined) }
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('字符串路径 facade 关闭时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    pushErpPage(mockRouter as unknown as Router, '/products')
    expect(mockRouter.push).toHaveBeenCalledWith('/products')
  })

  it('字符串路径 facade 开启时 push Mod 路径', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, '/products')
    expect(mockRouter.push).toHaveBeenCalledWith('/mod/xcagi-erp-domain-bridge/products')
  })

  it('对象路径 facade 关闭时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    pushErpPage(mockRouter as unknown as Router, { path: '/products' })
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/products' })
  })

  it('对象路径 facade 开启时 push 解析后的 Mod 路径', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { path: '/products' })
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/mod/xcagi-erp-domain-bridge/products' })
  })

  it('对象路由名 facade 开启时 push Mod 路径', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { name: 'products' })
    expect(mockRouter.push).toHaveBeenCalledWith({ path: '/mod/xcagi-erp-domain-bridge/products' })
  })

  it('对象路由名带 query 和 hash 时一并传递', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { name: 'products', query: { page: '1' }, hash: '#top' })
    expect(mockRouter.push).toHaveBeenCalledWith({
      path: '/mod/xcagi-erp-domain-bridge/products',
      query: { page: '1' },
      hash: '#top',
    })
  })

  it('对象路由名 facade 关闭时直接 push 原对象', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '0' })
    pushErpPage(mockRouter as unknown as Router, { name: 'products' })
    expect(mockRouter.push).toHaveBeenCalledWith({ name: 'products' })
  })

  it('未知路由名 facade 开启时直接 push 原对象', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { name: 'unknown' })
    expect(mockRouter.push).toHaveBeenCalledWith({ name: 'unknown' })
  })

  it('wechat-contacts 路由名 facade 开启时 push 带 source 参数', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { name: 'wechat-contacts' })
    expect(mockRouter.push).toHaveBeenCalledWith({
      path: '/mod/xcagi-erp-domain-bridge/data-sources?source=wechat_local_db',
    })
  })

  it('对象无 path 和 name 时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { params: { id: '1' } })
    expect(mockRouter.push).toHaveBeenCalledWith({ params: { id: '1' } })
  })

  it('对象 path 为非字符串时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { path: undefined })
    expect(mockRouter.push).toHaveBeenCalledWith({ path: undefined })
  })

  it('对象 name 为非字符串时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, { name: undefined })
    expect(mockRouter.push).toHaveBeenCalledWith({ name: undefined })
  })

  it('null 对象时直接 push', async () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    pushErpPage(mockRouter as unknown as Router, null as never)
    expect(mockRouter.push).toHaveBeenCalledWith(null)
  })
})
