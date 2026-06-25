import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockApi, mockResolveApprovalApiPath } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  mockResolveApprovalApiPath: vi.fn((p: string) => p),
}))

vi.mock('./core', () => ({ api: mockApi }))
vi.mock('@/utils/approvalPaths', () => ({
  resolveApprovalApiPath: mockResolveApprovalApiPath,
}))

import { approvalApi } from './approval'

describe('approval API functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockResolveApprovalApiPath.mockImplementation((p: string) => p)
  })

  describe('getPendingApprovals', () => {
    it('returns data with requests list on success', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: [{ id: 1 }] })
      const result = await approvalApi.getPendingApprovals(42)
      expect(mockApi.get).toHaveBeenCalledWith(
        '/api/approval/requests',
        { approver_id: 42, page: 1, page_size: 200 },
        { headers: { 'X-User-ID': '42' } },
      )
      expect(result.success).toBe(true)
      expect(result.data.requests).toHaveLength(1)
    })

    it('returns empty requests list when data is not array', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: null })
      const result = await approvalApi.getPendingApprovals(1)
      expect(result.data.requests).toEqual([])
    })

    it('returns failure on API error', async () => {
      mockApi.get.mockRejectedValue(new Error('Network error'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.getPendingApprovals(1)
      expect(result.success).toBe(false)
      expect(result.data.requests).toEqual([])
      warnSpy.mockRestore()
    })

    it('returns failure when response is null', async () => {
      mockApi.get.mockResolvedValue(null)
      const result = await approvalApi.getPendingApprovals(1)
      expect(result.success).toBe(false)
      expect(result.message).toBe('无效响应')
    })
  })

  describe('getMyRequests', () => {
    it('returns data with requests list on success', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: [{ id: 1 }, { id: 2 }] })
      const result = await approvalApi.getMyRequests(10)
      expect(mockApi.get).toHaveBeenCalledWith(
        '/api/approval/requests',
        { applicant_id: 10, page: 1, page_size: 500 },
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.data.requests).toHaveLength(2)
    })

    it('returns failure on API error', async () => {
      mockApi.get.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.getMyRequests(1)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('getRequestDetails', () => {
    it('returns data on success', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: { id: 1, title: 'test' } })
      const result = await approvalApi.getRequestDetails(1)
      expect(mockApi.get).toHaveBeenCalledWith('/api/approval/requests/1')
      expect(result).toEqual({ success: true, data: { id: 1, title: 'test' } })
    })

    it('returns failure on API error', async () => {
      mockApi.get.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.getRequestDetails(1)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('approve', () => {
    it('calls POST with correct params', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const result = await approvalApi.approve(1, 10, '同意')
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/approval/requests/1/approve',
        { approver_id: 10, opinion: '同意' },
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.approve(1, 10, 'ok')
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('reject', () => {
    it('calls POST with correct params', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const result = await approvalApi.reject(1, 10, '不同意')
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/approval/requests/1/reject',
        { approver_id: 10, reason: '不同意' },
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.reject(1, 10, 'no')
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('createFlow', () => {
    it('calls POST with flow and nodes', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const flowData = {
        flow_name: 'Test',
        flow_key: 'test',
        business_type: 'order',
        is_active: true,
      }
      const nodes = [
        { node_name: 'N1', node_type: 'approve', node_order: 1, approver_type: 'user', approver_ids: [1], is_active: true },
      ]
      const result = await approvalApi.createFlow(flowData, nodes)
      expect(mockApi.post).toHaveBeenCalledWith('/api/approval/flows', {
        flow: flowData,
        nodes: nodes,
      })
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.createFlow({} as never, [])
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('getFlowList', () => {
    it('returns data with flows list on success', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: [{ id: 1 }] })
      const result = await approvalApi.getFlowList()
      expect(mockApi.get).toHaveBeenCalledWith('/api/approval/flows', { is_active: true })
      expect(result.data.flows).toHaveLength(1)
    })

    it('returns empty flows list when data is not array', async () => {
      mockApi.get.mockResolvedValue({ success: true, data: null })
      const result = await approvalApi.getFlowList()
      expect(result.data.flows).toEqual([])
    })

    it('returns failure on API error', async () => {
      mockApi.get.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.getFlowList()
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })

    it('returns failure when response is null', async () => {
      mockApi.get.mockResolvedValue(null)
      const result = await approvalApi.getFlowList()
      expect(result.success).toBe(false)
      expect(result.message).toBe('无效响应')
    })
  })

  describe('submitRequest', () => {
    it('calls POST with data and user ID from localStorage', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      localStorage.setItem('user_id', '99')
      const data = { flow_key: 'test', business_type: 'order', title: 'Test' }
      const result = await approvalApi.submitRequest(data)
      expect(mockApi.post).toHaveBeenCalledWith('/api/approval/requests', data, {
        headers: { 'X-User-ID': '99' },
      })
      expect(result.success).toBe(true)
    })

    it('uses default user ID 4 when localStorage empty', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      localStorage.removeItem('user_id')
      await approvalApi.submitRequest({ flow_key: 't', business_type: 'b', title: 't' })
      const [, , opts] = mockApi.post.mock.calls[0]
      expect(opts.headers['X-User-ID']).toBe('4')
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.submitRequest({ flow_key: 't', business_type: 'b', title: 't' })
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('withdraw', () => {
    it('calls POST with correct params', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const result = await approvalApi.withdraw(1, 10)
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/approval/requests/1/withdraw',
        {},
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.withdraw(1, 10)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('deleteRequest', () => {
    it('calls DELETE with correct params', async () => {
      mockApi.delete.mockResolvedValue({ success: true, data: { deleted: 1, request_id: 5 } })
      const result = await approvalApi.deleteRequest(5, 10)
      expect(mockApi.delete).toHaveBeenCalledWith(
        '/api/approval/requests/5',
        {},
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.delete.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.deleteRequest(5, 10)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('updateFlow', () => {
    it('calls PUT with correct params', async () => {
      mockApi.put.mockResolvedValue({ success: true })
      const data = { flow_name: 'Updated' }
      const result = await approvalApi.updateFlow(1, data)
      expect(mockApi.put).toHaveBeenCalledWith('/api/approval/flows/1', data)
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.put.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.updateFlow(1, {})
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('toggleFlowActive', () => {
    it('calls PATCH with is_active true', async () => {
      mockApi.patch.mockResolvedValue({ success: true })
      const result = await approvalApi.toggleFlowActive(1, true)
      expect(mockApi.patch).toHaveBeenCalledWith('/api/approval/flows/1/active', { is_active: true })
      expect(result.success).toBe(true)
    })

    it('calls PATCH with is_active false', async () => {
      mockApi.patch.mockResolvedValue({ success: true })
      await approvalApi.toggleFlowActive(2, false)
      expect(mockApi.patch).toHaveBeenCalledWith('/api/approval/flows/2/active', { is_active: false })
    })

    it('returns failure on API error', async () => {
      mockApi.patch.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.toggleFlowActive(1, true)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('deleteFlow', () => {
    it('calls DELETE with correct path', async () => {
      mockApi.delete.mockResolvedValue({ success: true })
      const result = await approvalApi.deleteFlow(1)
      expect(mockApi.delete).toHaveBeenCalledWith('/api/approval/flows/1')
      expect(result.success).toBe(true)
    })

    it('returns failure on API error', async () => {
      mockApi.delete.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.deleteFlow(1)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('cleanupCompleted', () => {
    it('calls POST with default options', async () => {
      mockApi.post.mockResolvedValue({ success: true, data: { matched: 5, deleted: 5, dry_run: false } })
      const result = await approvalApi.cleanupCompleted(10)
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/approval/requests/cleanup',
        { statuses: undefined, before_days: 0, dry_run: false, scope: 'self' },
        { headers: { 'X-User-ID': '10' } },
      )
      expect(result.success).toBe(true)
    })

    it('calls POST with custom options', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await approvalApi.cleanupCompleted(10, {
        statuses: ['approved', 'rejected'],
        beforeDays: 30,
        dryRun: true,
      })
      const [, body] = mockApi.post.mock.calls[0]
      expect(body).toEqual({
        statuses: ['approved', 'rejected'],
        before_days: 30,
        dry_run: true,
        scope: 'self',
      })
    })

    it('returns failure on API error', async () => {
      mockApi.post.mockRejectedValue(new Error('fail'))
      const warnSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      const result = await approvalApi.cleanupCompleted(10)
      expect(result.success).toBe(false)
      warnSpy.mockRestore()
    })
  })

  describe('resolveApprovalApiPath integration', () => {
    it('uses resolved path from resolveApprovalApiPath', async () => {
      mockResolveApprovalApiPath.mockReturnValue('/api/mod/approval-bridge/requests')
      mockApi.get.mockResolvedValue({ success: true, data: [] })
      await approvalApi.getPendingApprovals(1)
      expect(mockApi.get).toHaveBeenCalledWith(
        '/api/mod/approval-bridge/requests',
        expect.anything(),
        expect.anything(),
      )
    })
  })
})
