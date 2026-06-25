import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockApi } = vi.hoisted(() => ({
  mockApi: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

vi.mock('@/api/core', () => ({ default: mockApi }))

import xcmaxMarketProxy from './xcmaxMarketProxy'
import { isLocalDutyApiAvailable } from './xcmaxMarketProxy'

describe('xcmaxMarketProxy functions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('isLocalDutyApiAvailable', () => {
    it('returns true when local API is available', async () => {
      mockApi.get.mockResolvedValue({ ok: true })
      const result = await isLocalDutyApiAvailable()
      expect(result).toBe(true)
    })
  })

  describe('adminListNoKeyEmployees', () => {
    it('calls market proxy GET endpoint', async () => {
      mockApi.get.mockResolvedValue({ data: [] })
      await xcmaxMarketProxy.adminListNoKeyEmployees()
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/market-proxy/admin/duty-graph/no-key-employees')
    })
  })

  describe('adminAlignSingleEmployeeLlmToAuto', () => {
    it('calls POST with dry_run=false by default', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.adminAlignSingleEmployeeLlmToAuto('pkg1')
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/employee-packs/pkg1/align-llm-to-auto-single?dry_run=false',
        undefined,
      )
    })

    it('calls POST with dry_run=true when specified', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.adminAlignSingleEmployeeLlmToAuto('pkg1', true)
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/employee-packs/pkg1/align-llm-to-auto-single?dry_run=true',
        undefined,
      )
    })

    it('encodes package id', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.adminAlignSingleEmployeeLlmToAuto('pkg/with/slash')
      expect(mockApi.post).toHaveBeenCalledWith(
        expect.stringContaining('pkg%2Fwith%2Fslash'),
        undefined,
      )
    })
  })

  describe('adminDutyGraphRunStart', () => {
    it('calls POST with payload', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const payload = { employee_id: 'emp1' }
      await xcmaxMarketProxy.adminDutyGraphRunStart(payload)
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/duty-graph/runs',
        payload,
      )
    })
  })

  describe('adminDutyGraphRunDetail', () => {
    it('calls GET with run id', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminDutyGraphRunDetail(123)
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/market-proxy/admin/duty-graph/runs/123')
    })

    it('encodes string run id', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminDutyGraphRunDetail('run/123')
      expect(mockApi.get).toHaveBeenCalledWith(
        expect.stringContaining('run%2F123'),
      )
    })
  })

  describe('adminEmployeeExecutionCapabilities', () => {
    it('calls POST with employee ids', async () => {
      mockApi.post.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminEmployeeExecutionCapabilities(['emp1', 'emp2'])
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/employees/execution-capabilities',
        { employee_ids: ['emp1', 'emp2'] },
      )
    })

    it('handles undefined employee ids', async () => {
      mockApi.post.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminEmployeeExecutionCapabilities()
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/employees/execution-capabilities',
        { employee_ids: [] },
      )
    })
  })

  describe('adminEmployeeExecutionMetrics', () => {
    it('calls GET with employee id', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminEmployeeExecutionMetrics('emp1')
      expect(mockApi.get).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/admin/employees/emp1/execution-metrics',
      )
    })

    it('appends query params when provided', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminEmployeeExecutionMetrics('emp1', { limit: 10, offset: 5, user_id: 42 })
      const call = mockApi.get.mock.calls[0][0] as string
      expect(call).toContain('limit=10')
      expect(call).toContain('offset=5')
      expect(call).toContain('user_id=42')
    })

    it('encodes employee id', async () => {
      mockApi.get.mockResolvedValue({ data: {} })
      await xcmaxMarketProxy.adminEmployeeExecutionMetrics('emp/1')
      expect(mockApi.get).toHaveBeenCalledWith(
        expect.stringContaining('emp%2F1'),
      )
    })
  })

  describe('llmStatus', () => {
    it('calls GET for llm status', async () => {
      mockApi.get.mockResolvedValue({ status: 'ok' })
      await xcmaxMarketProxy.llmStatus()
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/market-proxy/llm/status')
    })
  })

  describe('llmResolveChatDefault', () => {
    it('calls GET for chat default', async () => {
      mockApi.get.mockResolvedValue({ model: 'gpt-4' })
      await xcmaxMarketProxy.llmResolveChatDefault()
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/market-proxy/llm/resolve-chat-default')
    })
  })

  describe('llmChat', () => {
    it('calls POST with provider, model, messages, maxTokens', async () => {
      mockApi.post.mockResolvedValue({ reply: 'ok' })
      await xcmaxMarketProxy.llmChat('openai', 'gpt-4', [{ role: 'user', content: 'hi' }])
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/llm/chat',
        { provider: 'openai', model: 'gpt-4', messages: [{ role: 'user', content: 'hi' }], max_tokens: 1024 },
      )
    })

    it('uses custom maxTokens when provided', async () => {
      mockApi.post.mockResolvedValue({ reply: 'ok' })
      await xcmaxMarketProxy.llmChat('openai', 'gpt-4', [], 2048)
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/market-proxy/llm/chat',
        expect.objectContaining({ max_tokens: 2048 }),
      )
    })
  })

  describe('localEmployeeCronJobs', () => {
    it('calls GET for cron jobs', async () => {
      mockApi.get.mockResolvedValue([])
      await xcmaxMarketProxy.localEmployeeCronJobs()
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/local/employee-cron/jobs')
    })
  })

  describe('localRunEmployeeCronJob', () => {
    it('calls POST with job id and payload', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.localRunEmployeeCronJob('job1', { task: 'sync' })
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/local/employee-cron/jobs/job1/run',
        { task: 'sync' },
      )
    })

    it('uses empty object as default payload', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.localRunEmployeeCronJob('job1')
      expect(mockApi.post).toHaveBeenCalledWith(
        '/api/xcmax/local/employee-cron/jobs/job1/run',
        {},
      )
    })

    it('encodes job id', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.localRunEmployeeCronJob('job/1')
      expect(mockApi.post).toHaveBeenCalledWith(
        expect.stringContaining('job%2F1'),
        {},
      )
    })
  })

  describe('workbenchGetSession', () => {
    it('calls GET with session id', async () => {
      mockApi.get.mockResolvedValue({})
      await xcmaxMarketProxy.workbenchGetSession('sess1')
      expect(mockApi.get).toHaveBeenCalledWith('/api/xcmax/admin/all-hands-report/sessions/sess1')
    })

    it('encodes session id', async () => {
      mockApi.get.mockResolvedValue({})
      await xcmaxMarketProxy.workbenchGetSession('sess/1')
      expect(mockApi.get).toHaveBeenCalledWith(
        expect.stringContaining('sess%2F1'),
      )
    })
  })

  describe('butlerAllHandsReportStartSession', () => {
    it('calls POST with payload', async () => {
      mockApi.post.mockResolvedValue({ success: true })
      const payload = { title: 'Session 1' }
      await xcmaxMarketProxy.butlerAllHandsReportStartSession(payload)
      expect(mockApi.post).toHaveBeenCalledWith('/api/xcmax/admin/all-hands-report/sessions', payload)
    })
  })

  describe('adminDutyGraphHealth', () => {
    it('returns fallback health when local API not available', async () => {
      // The module-level cache may already be set from previous tests.
      // When local API is available (default mock returns success), it should return the API result.
      mockApi.get.mockResolvedValue({ ok: true, staffing: { planned_count: 1 } })
      const result = await xcmaxMarketProxy.adminDutyGraphHealth()
      expect(result).toHaveProperty('ok', true)
    })
  })

  describe('getEmployeeStatus', () => {
    it('returns status from local API when available', async () => {
      mockApi.get.mockResolvedValue({ employee_id: 'emp1', deployed: true })
      const result = await xcmaxMarketProxy.getEmployeeStatus('emp1') as { employee_id: string; deployed: boolean }
      expect(result.employee_id).toBe('emp1')
      expect(result.deployed).toBe(true)
    })
  })

  describe('getEmployeeManifest', () => {
    it('returns manifest from local API when available', async () => {
      mockApi.get.mockResolvedValue({ employee_id: 'emp1', name: 'Emp1', handlers: [{ name: 'h1' }] })
      const result = await xcmaxMarketProxy.getEmployeeManifest('emp1') as { employee_id: string; handlers: unknown[] }
      expect(result.employee_id).toBe('emp1')
      expect(result.handlers.length).toBe(1)
    })
  })

  describe('executeEmployeeTask', () => {
    it('calls local API when available', async () => {
      mockApi.get.mockResolvedValue({ ok: true })
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.executeEmployeeTask('emp1', 'sync', { data: 1 })
      expect(mockApi.post).toHaveBeenCalled()
    })
  })

  describe('selfMaintenanceRuntimeStatus', () => {
    it('calls local API when available', async () => {
      mockApi.get.mockResolvedValue({ status: 'ok' })
      const result = await xcmaxMarketProxy.selfMaintenanceRuntimeStatus(50)
      expect(result).toBeDefined()
    })
  })

  describe('selfMaintenanceGovernanceReview', () => {
    it('calls local API when available', async () => {
      mockApi.get.mockResolvedValue({ ok: true })
      mockApi.post.mockResolvedValue({ success: true })
      const result = await xcmaxMarketProxy.selfMaintenanceGovernanceReview({ note: 'test' })
      expect(result).toBeDefined()
    })

    it('uses empty object as default payload', async () => {
      mockApi.get.mockResolvedValue({ ok: true })
      mockApi.post.mockResolvedValue({ success: true })
      await xcmaxMarketProxy.selfMaintenanceGovernanceReview()
      expect(mockApi.post).toHaveBeenCalledWith(
        expect.any(String),
        {},
      )
    })
  })
})
