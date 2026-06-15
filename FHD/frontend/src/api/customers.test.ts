import { describe, it, expect, vi, beforeEach } from 'vitest'
import { customersApi } from './customers'

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

describe('customersApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getCustomers calls GET /customers/list', async () => {
    await customersApi.getCustomers({ page: 1 })
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/erp/customers/list', { page: 1 })
  })

  it('getCustomer calls GET /customers/:id', async () => {
    await customersApi.getCustomer(42)
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/erp/customers/42')
  })

  it('createCustomer calls POST /customers', async () => {
    const data = { name: 'Test' } as any
    await customersApi.createCustomer(data)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/erp/customers', data)
  })

  it('updateCustomer calls PUT /customers/:id', async () => {
    const data = { name: 'Updated' } as any
    await customersApi.updateCustomer(42, data)
    const { api } = await import('./core')
    expect(api.put).toHaveBeenCalledWith('/api/erp/customers/42', data)
  })

  it('deleteCustomer calls DELETE /customers/:id', async () => {
    await customersApi.deleteCustomer(42)
    const { api } = await import('./core')
    expect(api.delete).toHaveBeenCalledWith('/api/erp/customers/42')
  })

  it('batchDeleteCustomers calls POST /customers/batch-delete', async () => {
    await customersApi.batchDeleteCustomers([1, 2, 3])
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/erp/customers/batch-delete', { ids: [1, 2, 3] })
  })

  it('exportCustomersXlsx calls download with template_id when provided', async () => {
    await customersApi.exportCustomersXlsx('tmpl-1')
    const { api } = await import('./core')
    expect(api.download).toHaveBeenCalledWith('/api/erp/customers/export', { template_id: 'tmpl-1' })
  })

  it('exportCustomersXlsx calls download without template_id', async () => {
    await customersApi.exportCustomersXlsx()
    const { api } = await import('./core')
    expect(api.download).toHaveBeenCalledWith('/api/erp/customers/export', {})
  })

  it('importCustomersExcel calls POST /customers/import', async () => {
    const formData = new FormData()
    await customersApi.importCustomersExcel(formData)
    const { api } = await import('./core')
    expect(api.post).toHaveBeenCalledWith('/api/erp/customers/import', formData)
  })
})
