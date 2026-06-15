import { describe, it, expect, vi, beforeEach } from 'vitest'
import { listDocumentTemplates } from './documentTemplates'

vi.mock('./core', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ success: true, data: [] }),
  },
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
}))

describe('listDocumentTemplates', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls GET /api/document-templates without role', async () => {
    await listDocumentTemplates()
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/document-templates', {})
  })

  it('calls GET /api/document-templates with role', async () => {
    await listDocumentTemplates('shipping')
    const { api } = await import('./core')
    expect(api.get).toHaveBeenCalledWith('/api/document-templates', { role: 'shipping' })
  })

  it('returns empty data on 404 error', async () => {
    const { api, ApiError } = await import('./core')
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(404, 'Not found'))
    const result = await listDocumentTemplates()
    expect(result).toEqual({
      success: true,
      data: [],
      default_id: null,
      message: 'document-templates route not ready',
    })
  })

  it('re-throws non-404 errors', async () => {
    const { api, ApiError } = await import('./core')
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(500, 'Server error'))
    await expect(listDocumentTemplates()).rejects.toThrow('Server error')
  })
})
