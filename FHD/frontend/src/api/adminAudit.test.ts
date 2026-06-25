import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiGetMock = vi.fn()
vi.mock('@/api/core', () => ({
  default: {
    get: (...a: unknown[]) => apiGetMock(...a),
  },
}))

import { adminAuditApi } from './adminAudit'

describe('adminAuditApi', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
  })

  describe('list', () => {
    it('calls API with default limit and offset', async () => {
      apiGetMock.mockResolvedValue({
        success: true,
        data: { items: [{ id: 1 }], total: 1 },
      })
      const result = await adminAuditApi.list()
      expect(apiGetMock).toHaveBeenCalledWith(
        '/api/admin/audit-logs',
        { limit: 50, offset: 0 },
      )
      expect(result.success).toBe(true)
      expect(result.data.items).toHaveLength(1)
      expect(result.data.total).toBe(1)
    })

    it('calls API with custom limit and offset', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: { items: [], total: 0 } })
      await adminAuditApi.list(100, 200)
      expect(apiGetMock).toHaveBeenCalledWith(
        '/api/admin/audit-logs',
        { limit: 100, offset: 200 },
      )
    })

    it('handles zero limit and offset', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: { items: [], total: 0 } })
      await adminAuditApi.list(0, 0)
      expect(apiGetMock).toHaveBeenCalledWith(
        '/api/admin/audit-logs',
        { limit: 0, offset: 0 },
      )
    })

    it('propagates API errors', async () => {
      apiGetMock.mockRejectedValue(new Error('network'))
      await expect(adminAuditApi.list()).rejects.toThrow('network')
    })
  })

  describe('csvDownloadUrl', () => {
    it('returns URL with default limit', () => {
      const url = adminAuditApi.csvDownloadUrl()
      expect(url).toContain('/api/admin/audit-logs')
      expect(url).toContain('format=csv')
      expect(url).toContain('limit=500')
    })

    it('returns URL with custom limit', () => {
      const url = adminAuditApi.csvDownloadUrl(100)
      expect(url).toContain('limit=100')
    })

    it('returns URL with zero limit', () => {
      const url = adminAuditApi.csvDownloadUrl(0)
      expect(url).toContain('limit=0')
    })

    it('includes format=csv parameter', () => {
      const url = adminAuditApi.csvDownloadUrl()
      expect(url).toMatch(/format=csv/)
    })

    it('URL starts with /api/admin/audit-logs', () => {
      const url = adminAuditApi.csvDownloadUrl()
      expect(url).toMatch(/\/api\/admin\/audit-logs\?/)
    })
  })
})
