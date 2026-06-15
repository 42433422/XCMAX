import { describe, it, expect, vi } from 'vitest'

vi.mock('./core', () => ({
  default: {
    post: vi.fn().mockResolvedValue({ success: true }),
  },
}))

import { manualInductApi } from './manualInduct'
import api from './core'

describe('manualInductApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('preview calls api.post with payload', async () => {
    const payload = {
      target_scope: 'products',
      rows: [{ name: 'Product A' }],
    }
    await manualInductApi.preview(payload)
    expect(api.post).toHaveBeenCalledWith('/api/excel/manual-induct/preview', payload)
  })

  it('preview includes optional purchase_unit', async () => {
    const payload = {
      target_scope: 'products',
      purchase_unit: 'unit1',
      rows: [{ name: 'Product A' }],
    }
    await manualInductApi.preview(payload)
    expect(api.post).toHaveBeenCalledWith('/api/excel/manual-induct/preview', payload)
  })

  it('commit calls api.post with payload', async () => {
    const payload = {
      target_scope: 'customers',
      rows: [{ name: 'Customer A' }],
      create_missing: { purchase_units: ['unit1'] },
    }
    await manualInductApi.commit(payload)
    expect(api.post).toHaveBeenCalledWith('/api/excel/manual-induct/commit', payload)
  })

  it('extractUpload calls api.post with FormData', async () => {
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    await manualInductApi.extractUpload(file, 'Sheet1')
    expect(api.post).toHaveBeenCalledWith('/api/excel/data/extract/upload', expect.any(FormData))
  })

  it('extractUpload omits sheet_name when empty', async () => {
    const file = new File(['data'], 'test.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    await manualInductApi.extractUpload(file, '')
    const formData = (api.post as ReturnType<typeof vi.fn>).mock.calls[0][1] as FormData
    expect(formData.has('sheet_name')).toBe(false)
  })
})
