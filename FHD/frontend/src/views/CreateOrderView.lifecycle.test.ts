import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCreateOrder } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/create-order/useCreateOrder'
import CreateOrderView from '../../../mods/xcagi-erp-domain-bridge/frontend/views/CreateOrderView.vue'
import type { Product } from '@/types/product'

const { post, listTemplates } = vi.hoisted(() => ({ post: vi.fn(), listTemplates: vi.fn() }))
vi.mock('@/api/index', () => ({ default: { post, get: vi.fn().mockResolvedValue({ success: false }) } }))
vi.mock('@/api/templatePreview', () => ({ templatePreviewApi: { listTemplates } }))
vi.mock('@/api/products', () => ({ productsApi: { getProducts: vi.fn().mockResolvedValue({ success: true, data: [] }) } }))
vi.mock('@/utils', () => ({ downloadBlob: vi.fn() }))
vi.mock('@/utils/appDialog', () => ({ appAlert: vi.fn().mockResolvedValue(undefined) }))
vi.mock('vue-router', async original => ({ ...await original<typeof import('vue-router')>(), useRouter: () => ({ push: vi.fn() }) }))
const wrappers: VueWrapper[] = []
const productA = { id: 1, name: 'A', model_number: 'A-model', specification: '10', price: 100 } as Product
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function order() {
  let state!: ReturnType<typeof useCreateOrder>
  const wrapper = mount(defineComponent({ setup() { state = useCreateOrder(); return () => null } }))
  wrappers.push(wrapper)
  await flushPromises()
  state.allProducts.value = [productA]
  state.selectProductForAdd(productA)
  state.form.purchaseUnit = 'Synthetic customer'
  return { state, wrapper }
}
beforeEach(() => {
  vi.useFakeTimers()
  post.mockReset()
  listTemplates.mockResolvedValue({ success: true, templates: [{ id: 'db:tpl', name: 'Orders', category: 'excel', business_scope: 'orders' }] })
})
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount())
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('shipment product snapshot and submission lifecycle', () => {
  it.each([
    { model_number: '', specification: 0, price: 0 },
    { model_number: undefined, specification: undefined, price: undefined },
  ])('replaces all catalog fields, including empty and zero values: %j', async fields => {
    const { state } = await order()
    const replacement = { id: 2, name: 'B', ...fields } as Product
    state.allProducts.value.push(replacement)
    state.products.value[0].nameId = 2
    state.onProductNameSelect(state.products.value[0], 0)
    post.mockResolvedValue({ success: true, doc_name: 'B.xlsx' })
    await state.generateShipment()
    expect(post.mock.calls[0][1].products).toEqual([{ name: 'B', model_number: '', quantity_tins: 1, tin_spec: 0, quantity_kg: 0, unit_price: 0, amount: 0 }])
  })

  it('clears a removed product selection instead of retaining its previous catalog values', async () => {
    const { state } = await order()
    state.products.value[0].nameId = ''
    state.onProductNameSelect(state.products.value[0], 0)
    expect(state.products.value[0]).toMatchObject({ name: '', model: '', specification: 0, quantityKg: 0, unitPrice: 0, amount: 0 })
  })

  it('allows one in-flight submission and permits a deliberate retry after rejection', async () => {
    const { state } = await order()
    const response = deferred<{ success: boolean }>()
    post.mockReturnValueOnce(response.promise)
    const pending = state.generateShipment()
    await state.generateShipment()
    expect(post).toHaveBeenCalledTimes(1)
    response.reject(new Error('Synthetic offline'))
    await pending
    expect(state.status.message).toContain('Synthetic offline')
    post.mockResolvedValueOnce({ success: true, doc_name: 'retry.xlsx' })
    await state.generateShipment()
    expect(post).toHaveBeenCalledTimes(2)
    expect(state.result.value?.doc_name).toBe('retry.xlsx')
  })

  it('removes the old mounted form event handler without deleting a newer form handoff', async () => {
    const first = await order()
    const second = await order()
    first.wrapper.unmount()
    window.dispatchEvent(new CustomEvent('xcagi:ai-fill-order', { detail: { purchaseUnit: 'Second form only' } }))
    expect(first.state.form.purchaseUnit).toBe('Synthetic customer')
    expect(second.state.form.purchaseUnit).toBe('Second form only')
    expect(window.__VUE_FILL_ORDER__).toBeTypeOf('function')
    second.wrapper.unmount()
    expect(window.__VUE_FILL_ORDER__).toBeUndefined()
  })

  it('disables generation and reset while the submitted document is pending', async () => {
    const wrapper = mount(CreateOrderView, { global: { stubs: { RouterLink: true } } })
    wrappers.push(wrapper)
    await flushPromises()
    const vm = wrapper.vm as any
    vm.allProducts = [productA]
    vm.selectProductForAdd(productA)
    vm.form.purchaseUnit = 'Synthetic customer'
    const response = deferred<{ success: boolean; doc_name: string }>()
    post.mockReturnValueOnce(response.promise)
    const generate = wrapper.findAll('button').find(button => button.text() === '生成发货单')!
    const reset = wrapper.findAll('button').find(button => button.text() === '重置')!
    await generate.trigger('click')
    expect(generate.attributes('disabled')).toBeDefined()
    expect(reset.attributes('disabled')).toBeDefined()
    vm.resetForm()
    expect(vm.form.purchaseUnit).toBe('Synthetic customer')
    response.resolve({ success: true, doc_name: 'done.xlsx' })
    await flushPromises()
    expect(generate.attributes('disabled')).toBeUndefined()
  })
})
