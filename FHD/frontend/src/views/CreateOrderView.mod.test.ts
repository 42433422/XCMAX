import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useCreateOrder } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/create-order/useCreateOrder'

const { post, listTemplates, download, saveBlob } = vi.hoisted(() => ({ post: vi.fn(), listTemplates: vi.fn(), download: vi.fn(), saveBlob: vi.fn() }))
vi.mock('@/api/index', () => ({ default: { post, download, get: vi.fn().mockResolvedValue({ success: false }) } }))
vi.mock('@/api/products', () => ({ productsApi: { getProducts: vi.fn().mockResolvedValue({ success: true, data: [{ id: 1, name: '清漆', model_number: 'RX', specification: '25', price: 18 }] }) } }))
vi.mock('@/api/templatePreview', () => ({ templatePreviewApi: { listTemplates } }))
vi.mock('@/utils', () => ({ downloadBlob: saveBlob }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => { vi.useRealTimers() })

it('uses the selected template ID and preserves shipment values through generation', async () => {
  vi.useFakeTimers()
  listTemplates.mockResolvedValue({ success: true, templates: [
    { id: 'db:40', name: '客户表', category: 'excel', business_scope: 'customers' },
    ...['db:41', 'db:42'].map(id => ({ id, name: '送货单', category: 'excel', business_scope: 'orders' }))
  ] })
  post.mockResolvedValue({ success: true, doc_name: '验收单.xlsx' })
  let state!: ReturnType<typeof useCreateOrder>
  const wrapper = mount(defineComponent({ setup() { state = useCreateOrder(); return () => null } }))
  await state.loadTemplates()
  expect(state.templates.value.map(t => t.id)).toEqual(['db:41', 'db:42'])
  expect(state.form.templateName).toBe('db:41')
  Object.assign(state.form, { templateName: 'db:42', purchaseUnit: '验收客户', purchaseDate: '2026-09-13', orderNumber: 'ACCEPT-42' })
  state.selectProductForAdd(state.allProducts.value[0])
  state.products.value[0].quantityBox = 2
  state.calculateKg(0)
  await state.generateShipment()
  expect(post).toHaveBeenCalledWith('/api/shipment/generate', {
    unit_name: '验收客户', date: '2026-09-13', order_number: 'ACCEPT-42', template_id: 'db:42',
    products: [{ name: '清漆', model_number: 'RX', quantity_tins: 2, tin_spec: 25, quantity_kg: 50, unit_price: 18, amount: 900 }]
  })
  expect(state.result.value?.doc_name).toBe('验收单.xlsx')
  const blob = new Blob(['xlsx'])
  download.mockResolvedValue({ blob: async () => blob })
  await state.downloadShipment()
  expect(download).toHaveBeenCalledWith(`/api/shipment/download/${encodeURIComponent('验收单.xlsx')}`)
  expect(saveBlob).toHaveBeenCalledWith(blob, '验收单.xlsx')
  wrapper.unmount()
})
