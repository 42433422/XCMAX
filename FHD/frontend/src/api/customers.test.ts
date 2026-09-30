import { describe, it, expect, vi, beforeEach } from 'vitest'
import { customersApi } from './customers'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { useCustomers } from '../../../mods/xcagi-erp-domain-bridge/frontend/views/customers/useCustomers'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, data: [] }),
    post: vi.fn().mockResolvedValue({ success: true, data: {} }),
    put: vi.fn().mockResolvedValue({ success: true, data: {} }),
    delete: vi.fn().mockResolvedValue({ success: true }),
    download: vi.fn().mockResolvedValue(new Response()),
  },
}))

vi.mock('@/utils/erpDomainPaths', () => ({
  resolveErpApiBase: vi.fn().mockReturnValue('/api/erp'),
}))

vi.mock('@/composables/useCoreNavLabel', () => ({ useCoreNavLabel: (key: string) => ({ value: key }) }))
vi.mock('@/api/orders', () => ({ default: { getShipmentRecordUnits: vi.fn().mockResolvedValue({ success: true, data: [] }) } }))
vi.mock('@/api/templatePreview', () => ({ default: { listTemplates: vi.fn().mockResolvedValue({ success: true, templates: [] }) } }))

describe('customersApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it.each(['data', 'customers'])('renders customer records from the %s list envelope', async (key) => {
    const row = { id: 77, customer_name: 'WIN-READBACK', contact_person: '验收员', contact_phone: '13800000001', contact_address: '隔离地址' }
    const { api } = await import('./core')
    vi.mocked(api.get).mockResolvedValueOnce({ success: true, [key]: [row], total: 1 })
    const wrapper = mount(defineComponent({ setup: useCustomers, template: '<div><p v-for="row in customers" :key="row.id">{{ row.customer_name }} {{ row.contact_person }} {{ row.contact_phone }} {{ row.contact_address }}</p><span>{{ totalCustomers }}</span></div>' }))
    await flushPromises()
    expect(wrapper.find('p').text()).toBe('WIN-READBACK 验收员 13800000001 隔离地址')
    expect(wrapper.find('span').text()).toBe('1')
    wrapper.unmount()
  })

  it.each([
    ['list', () => customersApi.getCustomers({ page: 1 }), 'get', ['/api/erp/customers/list', { page: 1 }]],
    ['detail', () => customersApi.getCustomer(42), 'get', ['/api/erp/customers/42']],
    ['create', () => customersApi.createCustomer({ name: 'Test' } as any), 'post', ['/api/erp/customers', { name: 'Test' }]],
    ['update', () => customersApi.updateCustomer(42, { name: 'Updated' } as any), 'put', ['/api/erp/customers/42', { name: 'Updated' }]],
    ['delete', () => customersApi.deleteCustomer(42), 'delete', ['/api/erp/customers/42']],
    ['batch delete', () => customersApi.batchDeleteCustomers([1, 2, 3]), 'post', ['/api/erp/customers/batch-delete', { ids: [1, 2, 3] }]],
  ] as const)('%s uses the customer API contract', async (_name, call, method, args) => {
    await call()
    const { api } = await import('./core')
    expect(api[method]).toHaveBeenCalledWith(...args)
  })

  it.each([undefined, 'tmpl-1'])('exports with optional template %s', async (template) => {
    await customersApi.exportCustomersXlsx(template)
    const { api } = await import('./core')
    expect(api.download).toHaveBeenCalledWith('/api/erp/customers/export', template ? { template_id: template } : {})
  })

  it('importCustomersExcel calls POST /customers/import', async () => {
    const formData = new FormData()
    await customersApi.importCustomersExcel(formData)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/erp/customers/import', formData)
  })
})
