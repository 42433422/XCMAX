import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getMock, productsGetMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  productsGetMock: vi.fn(),
}))

vi.mock('@/api', () => ({
  get: getMock,
  post: vi.fn(),
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
})
