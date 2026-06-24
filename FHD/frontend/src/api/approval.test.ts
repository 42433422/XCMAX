import { describe, it, expect, beforeEach, vi } from 'vitest'

const apiGetMock = vi.fn()
const apiPostMock = vi.fn()
const apiPutMock = vi.fn()
const apiPatchMock = vi.fn()
const apiDeleteMock = vi.fn()

vi.mock('./core', () => ({
  api: {
    get: (...a: unknown[]) => apiGetMock(...a),
    post: (...a: unknown[]) => apiPostMock(...a),
    put: (...a: unknown[]) => apiPutMock(...a),
    patch: (...a: unknown[]) => apiPatchMock(...a),
    delete: (...a: unknown[]) => apiDeleteMock(...a),
  },
}))

// 默认禁用 Mod 门面，使路径原样返回
vi.mock('@/utils/approvalPaths', () => ({
  resolveApprovalApiPath: (p: string) => p,
}))

import { approvalApi } from './approval'

describe('approvalApi', () => {
  beforeEach(() => {
    apiGetMock.mockReset()
    apiPostMock.mockReset()
    apiPutMock.mockReset()
    apiPatchMock.mockReset()
    apiDeleteMock.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    localStorage.clear()
  })

  describe('getPendingApprovals', () => {
    it('fetches pending approvals with approver_id', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: [{ id: 1 }] })
      const result = await approvalApi.getPendingApprovals(5)
      expect(apiGetMock).toHaveBeenCalledWith(
        '/api/approval/requests',
        { approver_id: 5, page: 1, page_size: 200 },
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result.success).toBe(true)
      expect(result.data.requests).toHaveLength(1)
    })

    it('wraps non-array data as empty requests', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: 'not-array' })
      const result = await approvalApi.getPendingApprovals(5)
      expect(result.data.requests).toEqual([])
    })

    it('handles null response', async () => {
      apiGetMock.mockResolvedValue(null)
      const result = await approvalApi.getPendingApprovals(5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('无效响应')
      expect(result.data.requests).toEqual([])
    })

    it('handles non-object response', async () => {
      apiGetMock.mockResolvedValue('string')
      const result = await approvalApi.getPendingApprovals(5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('无效响应')
    })

    it('returns error object on API failure', async () => {
      apiGetMock.mockRejectedValue(new Error('network'))
      const result = await approvalApi.getPendingApprovals(5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('获取待审批列表失败')
      expect(result.data.requests).toEqual([])
    })
  })

  describe('getMyRequests', () => {
    it('fetches my requests with applicant_id', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: [{ id: 1 }] })
      const result = await approvalApi.getMyRequests(3)
      expect(apiGetMock).toHaveBeenCalledWith(
        '/api/approval/requests',
        { applicant_id: 3, page: 1, page_size: 500 },
        { headers: { 'X-User-ID': '3' } },
      )
      expect(result.data.requests).toHaveLength(1)
    })

    it('returns error on API failure', async () => {
      apiGetMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.getMyRequests(3)
      expect(result.success).toBe(false)
      expect(result.message).toBe('获取我的请求失败')
    })
  })

  describe('getRequestDetails', () => {
    it('fetches request details by id', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: { id: 1 } })
      const result = await approvalApi.getRequestDetails(1)
      expect(apiGetMock).toHaveBeenCalledWith('/api/approval/requests/1')
      expect(result).toEqual({ success: true, data: { id: 1 } })
    })

    it('returns error object on failure', async () => {
      apiGetMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.getRequestDetails(1)
      expect(result.success).toBe(false)
      expect(result.message).toBe('获取请求详情失败')
    })
  })

  describe('approve', () => {
    it('posts approve action', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      const result = await approvalApi.approve(1, 5, 'ok')
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests/1/approve',
        { approver_id: 5, opinion: 'ok' },
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.approve(1, 5, 'ok')
      expect(result.success).toBe(false)
      expect(result.message).toBe('审批通过失败')
    })
  })

  describe('reject', () => {
    it('posts reject action', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      const result = await approvalApi.reject(1, 5, 'bad')
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests/1/reject',
        { approver_id: 5, reason: 'bad' },
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.reject(1, 5, 'bad')
      expect(result.success).toBe(false)
      expect(result.message).toBe('审批拒绝失败')
    })
  })

  describe('createFlow', () => {
    it('creates flow with nodes', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      const flowData = {
        flow_name: 'test',
        flow_key: 'test-key',
        business_type: 'leave',
        is_active: true,
      }
      const nodes = [
        {
          node_name: 'node1',
          node_type: 'approval',
          node_order: 1,
          approver_type: 'user',
          approver_ids: [1],
          is_active: true,
        },
      ]
      const result = await approvalApi.createFlow(flowData, nodes)
      expect(apiPostMock).toHaveBeenCalledWith('/api/approval/flows', {
        flow: flowData,
        nodes,
      })
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.createFlow(
        {
          flow_name: 't',
          flow_key: 'k',
          business_type: 'b',
          is_active: true,
        },
        [],
      )
      expect(result.success).toBe(false)
      expect(result.message).toBe('创建审批流程失败')
    })
  })

  describe('getFlowList', () => {
    it('fetches flow list', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: [{ id: 1 }] })
      const result = await approvalApi.getFlowList()
      expect(apiGetMock).toHaveBeenCalledWith('/api/approval/flows', {
        is_active: true,
      })
      expect(result.data.flows).toHaveLength(1)
    })

    it('wraps non-array data as empty flows', async () => {
      apiGetMock.mockResolvedValue({ success: true, data: null })
      const result = await approvalApi.getFlowList()
      expect(result.data.flows).toEqual([])
    })

    it('handles null response', async () => {
      apiGetMock.mockResolvedValue(null)
      const result = await approvalApi.getFlowList()
      expect(result.success).toBe(false)
      expect(result.message).toBe('无效响应')
    })

    it('returns error on failure', async () => {
      apiGetMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.getFlowList()
      expect(result.success).toBe(false)
      expect(result.message).toBe('获取流程列表失败')
    })
  })

  describe('submitRequest', () => {
    it('submits request with user_id from localStorage', async () => {
      localStorage.setItem('user_id', '42')
      apiPostMock.mockResolvedValue({ success: true })
      const data = {
        flow_key: 'leave',
        business_type: 'leave',
        title: 'test',
      }
      const result = await approvalApi.submitRequest(data)
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests',
        data,
        { headers: { 'X-User-ID': '42' } },
      )
      expect(result).toEqual({ success: true })
    })

    it('uses default user_id 4 when not in localStorage', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      await approvalApi.submitRequest({
        flow_key: 'k',
        business_type: 'b',
        title: 't',
      })
      expect(apiPostMock).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Object),
        { headers: { 'X-User-ID': '4' } },
      )
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.submitRequest({
        flow_key: 'k',
        business_type: 'b',
        title: 't',
      })
      expect(result.success).toBe(false)
      expect(result.message).toBe('提交审批请求失败')
    })
  })

  describe('withdraw', () => {
    it('posts withdraw action', async () => {
      apiPostMock.mockResolvedValue({ success: true })
      const result = await approvalApi.withdraw(1, 5)
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests/1/withdraw',
        {},
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.withdraw(1, 5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('撤回请求失败')
    })
  })

  describe('deleteRequest', () => {
    it('deletes request via DELETE', async () => {
      apiDeleteMock.mockResolvedValue({
        success: true,
        data: { deleted: 1, request_id: 1 },
      })
      const result = await approvalApi.deleteRequest(1, 5)
      expect(apiDeleteMock).toHaveBeenCalledWith(
        '/api/approval/requests/1',
        {},
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result.success).toBe(true)
    })

    it('returns error on failure', async () => {
      apiDeleteMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.deleteRequest(1, 5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('删除审批记录失败')
    })
  })

  describe('updateFlow', () => {
    it('updates flow via PUT', async () => {
      apiPutMock.mockResolvedValue({ success: true })
      const result = await approvalApi.updateFlow(1, { flow_name: 'updated' })
      expect(apiPutMock).toHaveBeenCalledWith('/api/approval/flows/1', {
        flow_name: 'updated',
      })
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPutMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.updateFlow(1, {})
      expect(result.success).toBe(false)
      expect(result.message).toBe('更新流程失败')
    })
  })

  describe('toggleFlowActive', () => {
    it('toggles flow active via PATCH', async () => {
      apiPatchMock.mockResolvedValue({ success: true })
      const result = await approvalApi.toggleFlowActive(1, false)
      expect(apiPatchMock).toHaveBeenCalledWith(
        '/api/approval/flows/1/active',
        { is_active: false },
      )
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiPatchMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.toggleFlowActive(1, true)
      expect(result.success).toBe(false)
      expect(result.message).toBe('切换流程状态失败')
    })
  })

  describe('deleteFlow', () => {
    it('deletes flow via DELETE', async () => {
      apiDeleteMock.mockResolvedValue({ success: true })
      const result = await approvalApi.deleteFlow(1)
      expect(apiDeleteMock).toHaveBeenCalledWith('/api/approval/flows/1')
      expect(result).toEqual({ success: true })
    })

    it('returns error on failure', async () => {
      apiDeleteMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.deleteFlow(1)
      expect(result.success).toBe(false)
      expect(result.message).toBe('删除流程失败')
    })
  })

  describe('cleanupCompleted', () => {
    it('posts cleanup with default options', async () => {
      apiPostMock.mockResolvedValue({
        success: true,
        data: { matched: 5, deleted: 3, dry_run: false, statuses: [], before_days: 0 },
      })
      const result = await approvalApi.cleanupCompleted(5)
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests/cleanup',
        {
          statuses: undefined,
          before_days: 0,
          dry_run: false,
          scope: 'self',
        },
        { headers: { 'X-User-ID': '5' } },
      )
      expect(result.success).toBe(true)
    })

    it('posts cleanup with custom options', async () => {
      apiPostMock.mockResolvedValue({ success: true, data: {} })
      await approvalApi.cleanupCompleted(5, {
        statuses: ['approved', 'rejected'],
        beforeDays: 30,
        dryRun: true,
      })
      expect(apiPostMock).toHaveBeenCalledWith(
        '/api/approval/requests/cleanup',
        {
          statuses: ['approved', 'rejected'],
          before_days: 30,
          dry_run: true,
          scope: 'self',
        },
        { headers: { 'X-User-ID': '5' } },
      )
    })

    it('returns error on failure', async () => {
      apiPostMock.mockRejectedValue(new Error('fail'))
      const result = await approvalApi.cleanupCompleted(5)
      expect(result.success).toBe(false)
      expect(result.message).toBe('清理审批记录失败')
    })
  })
})
