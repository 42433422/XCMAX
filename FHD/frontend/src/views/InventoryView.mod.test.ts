import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getMock, productsGetMock, downloadMock, downloadBlobMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  productsGetMock: vi.fn(),
  downloadMock: vi.fn(),
  downloadBlobMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  get: getMock,
  post: vi.fn(),
  api: { download: downloadMock },
}))

vi.mock('@/utils', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/utils')>()),
  downloadBlob: downloadBlobMock,
}))

vi.mock('@/api/products', () => ({
  default: {
    getProducts: productsGetMock,
  },
}))

vi.mock('@/utils/appDialog', () => ({
  appAlert: vi.fn(),
}))

import InventoryView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/InventoryView.vue'

describe('ERP domain bridge InventoryView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    downloadMock.mockReset()
    productsGetMock.mockResolvedValue({
      success: true,
      data: [{ id: 7, name: 'A 产品', model_number: 'A-001' }],
    })
    getMock.mockImplementation((path: string) => {
      if (path === '/api/inventory/warehouses') {
        return Promise.resolve({ success: true, data: [{ id: 3, name: '主仓' }] })
      }
      return Promise.resolve({ success: true, data: [], total: 0 })
    })
  })

  it('loads products from the ERP product SSOT for the stock-in form', async () => {
    const wrapper = mount(InventoryView)
    await flushPromises()

    await wrapper.get('button.btn-primary').trigger('click')

    expect(productsGetMock).toHaveBeenCalledWith({ page: 1, per_page: 1000 })
    expect(wrapper.text()).toContain('A 产品 - A-001')
    expect(wrapper.text()).toContain('主仓')
  })

  it('exports all filtered rows with progress and preserves the active filters', async () => {
    let resolveDownload!: (response: Response) => void
    downloadMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveDownload = resolve
      }),
    )
    const wrapper = mount(InventoryView)
    await flushPromises()
    await wrapper.get('.search-box select').setValue('3')
    await wrapper.get('.search-box input').setValue('涂料')
    await flushPromises()

    await wrapper.get('[data-testid="inventory-export"]').trigger('click')
    expect(wrapper.get('[data-testid="inventory-export"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在生成')
    expect(downloadMock).toHaveBeenCalledWith('/api/inventory/export.xlsx', { warehouse_id: '3', keyword: '涂料' }, { timeoutMs: 60000 })
    resolveDownload(
      new Response('excel-bytes', {
        headers: {
          'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'Content-Disposition': "attachment; filename*=UTF-8''%E5%BA%93%E5%AD%98%E6%98%8E%E7%BB%86.xlsx",
          'X-Inventory-Row-Count': '60',
        },
      }),
    )
    await flushPromises()

    expect(downloadBlobMock).toHaveBeenCalledWith(expect.objectContaining({ size: 11 }), '库存明细.xlsx')
    expect(wrapper.text()).toContain('60 条库存明细')
    expect(wrapper.text()).toContain('已发起下载')
    expect(wrapper.get('[data-testid="inventory-export"]').attributes('disabled')).toBeUndefined()
    expect((wrapper.get('.search-box select').element as HTMLSelectElement).value).toBe('3')
    expect((wrapper.get('.search-box input').element as HTMLInputElement).value).toBe('涂料')
  })

  it.each(['当前筛选条件下没有库存数据可导出。', '库存导出最多支持 50,000 条，请缩小筛选范围。', '连接失败，请稍后重试。'])(
    'does not download on an export failure: %s',
    async (message) => {
      downloadMock.mockRejectedValue(new Error(message))
      const wrapper = mount(InventoryView)
      await flushPromises()
      await wrapper.get('[data-testid="inventory-export"]').trigger('click')
      await flushPromises()
      expect(downloadBlobMock).not.toHaveBeenCalled()
      expect(wrapper.get('[role="alert"]').text()).toContain(message)
      expect(wrapper.get('[data-testid="inventory-export"]').attributes('disabled')).toBeUndefined()
    },
  )

  it('rejects a successful HTTP response containing an error page instead of Excel', async () => {
    downloadMock.mockResolvedValue(new Response('login required', { headers: { 'Content-Type': 'text/html' } }))
    const wrapper = mount(InventoryView)
    await flushPromises()
    await wrapper.get('[data-testid="inventory-export"]').trigger('click')
    await flushPromises()
    expect(downloadBlobMock).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('有效的库存 Excel')
  })

  it('does not download an empty file even when the server sends an Excel content type', async () => {
    downloadMock.mockResolvedValue(
      new Response('', { headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } }),
    )
    const wrapper = mount(InventoryView)
    await flushPromises()
    await wrapper.get('[data-testid="inventory-export"]').trigger('click')
    await flushPromises()
    expect(downloadBlobMock).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('文件为空')
  })

  it('resets pagination when filters change and sends the keyword to the server', async () => {
    getMock.mockImplementation((path: string) =>
      Promise.resolve(
        path === '/api/inventory'
          ? { success: true, data: [{ id: 1, product_name: '库存', quantity: 1, available_quantity: 1 }], total: 60 }
          : { success: true, data: [] },
      ),
    )
    const wrapper = mount(InventoryView)
    await flushPromises()
    await wrapper.get('.pagination button:last-child').trigger('click')
    await flushPromises()
    expect(getMock).toHaveBeenCalledWith('/api/inventory', { page: 2, per_page: 50 })
    await wrapper.get('.search-box input').setValue(' SKU-003 ')
    await flushPromises()
    expect(getMock).toHaveBeenLastCalledWith('/api/inventory', { page: 1, per_page: 50, keyword: 'SKU-003' })
    expect((wrapper.get('.search-box input').element as HTMLInputElement).value).toBe(' SKU-003 ')
  })

  it('keeps the newest search result if an older request completes later', async () => {
    let resolveOlder!: (result: unknown) => void
    getMock.mockImplementation((path: string, params?: { keyword?: string }) => {
      if (path !== '/api/inventory') return Promise.resolve({ success: true, data: [] })
      if (params?.keyword === '旧')
        return new Promise((resolve) => {
          resolveOlder = resolve
        })
      if (params?.keyword === '新') return Promise.resolve({ success: true, data: [{ id: 2, product_name: '新库存结果' }], total: 1 })
      return Promise.resolve({ success: true, data: [], total: 0 })
    })
    const wrapper = mount(InventoryView)
    await flushPromises()
    await wrapper.get('.search-box input').setValue('旧')
    await wrapper.get('.search-box input').setValue('新')
    await flushPromises()
    resolveOlder({ success: true, data: [{ id: 1, product_name: '旧库存结果' }], total: 1 })
    await flushPromises()
    expect(wrapper.text()).toContain('新库存结果')
    expect(wrapper.text()).not.toContain('旧库存结果')
  })
})
