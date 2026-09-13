import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { useCreateOrder } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/create-order/useCreateOrder'

const { post, listTemplates } = vi.hoisted(() => ({ post: vi.fn(), listTemplates: vi.fn() }))
vi.mock('@/api/index', () => ({ default: { post } }))
vi.mock('@/api/templatePreview', () => ({ templatePreviewApi: { listTemplates } }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

it('uses the selected template ID and preserves shipment values through generation', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ json: async () => ({ success: false }) }))
  listTemplates.mockResolvedValue({ success: true, templates: [
    { id: 'db:41', name: '送货单' }, { id: 'db:42', name: '送货单' }
  ] })
  post.mockResolvedValue({ success: true, doc_name: '验收单.xlsx' })
  let state!: ReturnType<typeof useCreateOrder>
  const wrapper = mount(defineComponent({ setup() { state = useCreateOrder(); return () => null } }))
  await state.loadTemplates()
  expect(state.form.templateName).toBe('db:41')
  Object.assign(state.form, { templateName: 'db:42', purchaseUnit: '验收客户', purchaseDate: '2026-09-13', orderNumber: 'ACCEPT-42' })
  state.products.value = [{ id: 1, nameId: 1, name: '清漆', model: 'RX', quantityBox: 2, specification: 25, quantityKg: 50, unitPrice: 18, amount: 900 }]
  await state.generateShipment()
  expect(post).toHaveBeenCalledWith('/api/shipment/generate', {
    unit_name: '验收客户', date: '2026-09-13', order_number: 'ACCEPT-42', template_id: 'db:42',
    products: [{ name: '清漆', model_number: 'RX', quantity_tins: 2, tin_spec: 25, quantity_kg: 50, unit_price: 18, amount: 900 }]
  })
  expect(state.result.value?.doc_name).toBe('验收单.xlsx')
  wrapper.unmount()
})
