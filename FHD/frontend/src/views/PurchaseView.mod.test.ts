import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getMock, postMock, appAlert, appConfirm } = vi.hoisted(() => ({
  getMock: vi.fn(),
  postMock: vi.fn(),
  appAlert: vi.fn(),
  appConfirm: vi.fn(),
}))

vi.mock('@/api', () => ({
  get: getMock,
  post: postMock,
  productsApi: { getProducts: vi.fn().mockResolvedValue({ success: true, data: [{ id: 3, name: '商品 A', price: 5 }] }) },
}))
vi.mock('@/utils/appDialog', () => ({
  appAlert,
  appConfirm,
  appPrompt: vi.fn(),
}))

import PurchaseView from '../../../mods/bridge/xcagi-erp-domain-bridge/frontend/views/PurchaseView.vue'

describe('ERP purchase UI read/write guarantees', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    appAlert.mockResolvedValue(undefined)
    appConfirm.mockResolvedValue(true)
    getMock.mockImplementation((path: string) => Promise.resolve({
      success: true,
      data: path === '/api/purchase/suppliers' ? [{ id: 2, code: 'S-2', name: '供应商 A' }] : [],
    }))
    postMock.mockResolvedValue({ success: true, data: { id: 15 } })
  })

  it('ignores the older purchase filter result after a newer selection resolves', async () => {
    let finishOld!: (response: unknown) => void
    getMock.mockImplementation((path: string, params?: { status?: string }) => {
      if (path === '/api/purchase/orders' && params?.status === 'approved') {
        return new Promise((resolve) => { finishOld = resolve })
      }
      if (path === '/api/purchase/orders' && params?.status === 'draft') {
        return Promise.resolve({ success: true, data: [{ id: 2, order_no: 'NEW-DRAFT', total_amount: 3, status: 'draft' }] })
      }
      return Promise.resolve({ success: true, data: [] })
    })
    const wrapper = mount(PurchaseView)
    await flushPromises()
    const filter = wrapper.get('.search-box select')
    await filter.setValue('approved')
    await filter.setValue('draft')
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-DRAFT')
    finishOld({ success: true, data: [{ id: 1, order_no: 'OLD-APPROVED', total_amount: 9, status: 'approved' }] })
    await flushPromises()
    expect(wrapper.text()).toContain('NEW-DRAFT')
    expect(wrapper.text()).not.toContain('OLD-APPROVED')
    wrapper.unmount()
  })

  it('locks duplicate purchase form submission and refreshes the order list', async () => {
    let finishWrite!: (response: unknown) => void
    postMock.mockImplementation(() => new Promise((resolve) => { finishWrite = resolve }))
    const wrapper = mount(PurchaseView)
    await flushPromises()
    const state = wrapper.vm as unknown as {
      showOrderModal: () => void
      orderForm: { supplier_id: number; items: Array<{ product_id: number; quantity: number; unit_price: number; amount: number }> }
    }
    state.showOrderModal()
    state.orderForm.supplier_id = 2
    state.orderForm.items = [{ product_id: 3, quantity: 2, unit_price: 5, amount: 10 }]
    await flushPromises()
    const save = wrapper.get('.modal.active .modal-footer .btn-primary')
    await save.trigger('click')
    expect(save.attributes('disabled')).toBeDefined()
    await save.trigger('click')
    expect(postMock).toHaveBeenCalledTimes(1)
    finishWrite({ success: true, data: { id: 15 } })
    await flushPromises()
    expect(wrapper.find('.modal.active').exists()).toBe(false)
    expect(appAlert).toHaveBeenCalledWith('保存成功')
    expect(getMock.mock.calls.filter(([endpoint]) => endpoint === '/api/purchase/orders').length).toBeGreaterThan(1)
    wrapper.unmount()
  })

  it('rejects invalid quantity and negative purchase price before calling the server', async () => {
    const wrapper = mount(PurchaseView)
    await flushPromises()
    const state = wrapper.vm as unknown as {
      showOrderModal: () => void
      orderForm: { supplier_id: number; items: Array<{ product_id: number; quantity: number; unit_price: number; amount: number }> }
    }
    state.showOrderModal()
    state.orderForm.supplier_id = 2
    state.orderForm.items = [{ product_id: 3, quantity: 0, unit_price: -1, amount: 0 }]
    await flushPromises()
    await wrapper.get('.modal.active .modal-footer .btn-primary').trigger('click')
    await flushPromises()
    expect(postMock).not.toHaveBeenCalled()
    expect(appAlert).toHaveBeenCalledWith('第 1 行数量或单价无效')
    wrapper.unmount()
  })

  it('renders a retryable error instead of an empty order table after read failure', async () => {
    getMock.mockImplementation((path: string) => path === '/api/purchase/orders'
      ? Promise.reject(new Error('采购数据暂不可用'))
      : Promise.resolve({ success: true, data: [] }))
    const wrapper = mount(PurchaseView)
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('采购数据暂不可用')
    expect(wrapper.text()).not.toContain('暂无订单数据')
    wrapper.unmount()
  })
})
