import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PurchaseView from '../../../XCAGI/mods/xcagi-erp-domain-bridge/frontend/views/PurchaseView.vue'
const mocks = vi.hoisted(() => ({ get: vi.fn(async () => ({ success: true, data: [] })), post: vi.fn(), alert: vi.fn(async () => {}), prompt: vi.fn(), confirm: vi.fn() }))
vi.mock('@/api', () => ({ get: mocks.get, post: mocks.post, productsApi: { getProducts: mocks.get } }))
vi.mock('@/utils/appDialog', () => ({ appAlert: mocks.alert, appConfirm: mocks.confirm, appPrompt: mocks.prompt }))
describe('purchase receipt', () => {
  it('receives remaining order quantity into an explicitly selected warehouse and reads it back', async () => {
    const wrapper = mount(PurchaseView)
    await flushPromises()
    const vm = wrapper.vm as any
    const order = { id: 8, supplier_id: 3, status: 'approved', items: [{ id: 9, product_id: 4, quantity: 10, received_quantity: 2, unit_price: 12.5 }] }
    mocks.get.mockResolvedValueOnce({ success: true, data: [{ id: 5, name: '验收仓库' }] } as any)
    await vm.receiveOrder(order)
    expect(vm.orderForm.items[0]).toMatchObject({ order_item_id: 9, quantity: 8 })
    await vm.saveOrder()
    expect(mocks.post).not.toHaveBeenCalled()
    vm.receiveWarehouse = 5
    vm.orderForm.items[0].quantity = 9
    await vm.saveOrder()
    expect(mocks.post).not.toHaveBeenCalled()
    vm.orderForm.items[0].quantity = 8
    mocks.prompt.mockResolvedValueOnce(null)
    await vm.createWarehouse()
    expect(mocks.post).not.toHaveBeenCalled()
    mocks.post.mockResolvedValueOnce({ success: true, data: { id: 12 } })
    await vm.saveOrder()
    expect(mocks.post).toHaveBeenCalledWith('/api/purchase/inbounds', expect.objectContaining({ order_id: 8, supplier_id: 3, warehouse_id: 5, items: [expect.objectContaining({ order_item_id: 9, quantity: 8 })] }))
    expect(vm.activeTab).toBe('inbounds')
    expect(mocks.get).toHaveBeenCalledWith('/api/purchase/inbounds', {})
    wrapper.unmount()
  })
})
