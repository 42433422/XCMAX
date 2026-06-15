import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { salesContractApi } from '@/api/salesContract'

vi.mock('@/api/core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true }),
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { api } from '@/api/core'

describe('salesContractApi', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('listTemplates calls GET /api/sales-contract/templates', async () => {
    await salesContractApi.listTemplates()
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/templates')
  })

  it('resolveFromText calls POST /api/sales-contract/resolve-from-text', async () => {
    await salesContractApi.resolveFromText({ text: '订货话术' })
    expect(api.post).toHaveBeenCalledWith('/api/sales-contract/resolve-from-text', { text: '订货话术' })
  })

  it('getTemplatePreview calls GET /api/sales-contract/template-preview', async () => {
    await salesContractApi.getTemplatePreview()
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/template-preview', {})
  })

  it('getTemplatePreview passes params', async () => {
    await salesContractApi.getTemplatePreview({ template_id: 'abc' })
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/template-preview', { template_id: 'abc' })
  })

  it('generate calls POST /api/sales-contract/generate', async () => {
    const data = {
      customer_name: '测试客户',
      products: [{ model_number: 'M1', name: '产品', spec: 'S', unit: '个', quantity: '10', unit_price: '100', amount: '1000' }],
    }
    await salesContractApi.generate(data)
    expect(api.post).toHaveBeenCalledWith('/api/sales-contract/generate', data)
  })

  it('previewUpdate calls POST /api/sales-contract/preview-update', async () => {
    const body = {
      products: [{ model_number: 'M1', name: '产品', spec: 'S', unit: '个', quantity: '10', unit_price: '100', amount: '1000' }],
      customer_name: '测试客户',
    }
    await salesContractApi.previewUpdate(body)
    expect(api.post).toHaveBeenCalledWith('/api/sales-contract/preview-update', body)
  })

  it('print calls POST /api/sales-contract/print', async () => {
    await salesContractApi.print({ filename: 'test.docx' })
    expect(api.post).toHaveBeenCalledWith('/api/sales-contract/print', { filename: 'test.docx' })
  })

  it('download returns correct URL', () => {
    const url = salesContractApi.download('test file.docx')
    expect(url).toBe('/api/sales-contract/download/test%20file.docx')
  })

  it('list calls GET /api/sales-contract/list', async () => {
    await salesContractApi.list()
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/list')
  })

  it('preview with filename calls GET with encoded filename', async () => {
    await salesContractApi.preview('test.docx')
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/preview/test.docx')
  })

  it('preview without filename calls GET default', async () => {
    await salesContractApi.preview()
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/preview/default')
  })

  it('previewDefault calls GET /api/sales-contract/preview/default', async () => {
    await salesContractApi.previewDefault()
    expect(api.get).toHaveBeenCalledWith('/api/sales-contract/preview/default')
  })
})
