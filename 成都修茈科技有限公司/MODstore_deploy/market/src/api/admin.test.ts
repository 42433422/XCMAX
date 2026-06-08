import { describe, expect, it, vi } from 'vitest'
import { admin } from './admin'

vi.mock('./shared', () => ({
  req: vi.fn(() => Promise.resolve({})),
}))

import { req } from './shared'

const m = vi.mocked(req)

describe('admin API', () => {
  beforeEach(() => { m.mockClear() })

  it('adminStatus', async () => {
    await admin.adminStatus()
    expect(m).toHaveBeenCalledWith('/api/admin/status')
  })

  it('adminResearchSettings', async () => {
    await admin.adminResearchSettings()
    expect(m).toHaveBeenCalledWith('/api/admin/research-settings')
  })

  it('adminSaveResearchSettings', async () => {
    await admin.adminSaveResearchSettings({ key: 'val' })
    expect(m).toHaveBeenCalledWith('/api/admin/research-settings', expect.objectContaining({ method: 'PUT' }))
  })

  it('adminVectorSettings', async () => {
    await admin.adminVectorSettings()
    expect(m).toHaveBeenCalledWith('/api/admin/vector-settings')
  })

  it('adminSaveVectorSettings', async () => {
    await admin.adminSaveVectorSettings({ key: 'val' })
    expect(m).toHaveBeenCalledWith('/api/admin/vector-settings', expect.objectContaining({ method: 'PUT' }))
  })

  it('adminUpload', async () => {
    const fd = new FormData()
    await admin.adminUpload(fd)
    expect(m).toHaveBeenCalledWith('/api/admin/catalog', expect.objectContaining({ method: 'POST', body: fd }))
  })

  it('adminListCatalog with defaults', async () => {
    await admin.adminListCatalog()
    expect(m).toHaveBeenCalledWith('/api/admin/catalog?limit=200&offset=0')
  })

  it('adminListCatalog with custom params', async () => {
    await admin.adminListCatalog(10, 5)
    expect(m).toHaveBeenCalledWith('/api/admin/catalog?limit=10&offset=5')
  })

  it('adminDeleteCatalog', async () => {
    await admin.adminDeleteCatalog(42)
    expect(m).toHaveBeenCalledWith('/api/admin/catalog/42', expect.objectContaining({ method: 'DELETE' }))
  })

  it('adminDeleteEmployeePack', async () => {
    await admin.adminDeleteEmployeePack('pkg-1')
    expect(m).toHaveBeenCalledWith('/api/admin/employee-packs/pkg-1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('adminPurgeAllEmployeePacks', async () => {
    await admin.adminPurgeAllEmployeePacks()
    expect(m).toHaveBeenCalledWith('/api/admin/employee-packs/purge-all', expect.objectContaining({ method: 'POST' }))
  })

  it('adminAlignEmployeeLlmFromDeepseek dry run', async () => {
    await admin.adminAlignEmployeeLlmFromDeepseek(true)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('dry_run=true'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminAlignEmployeeLlmFromDeepseek not dry run', async () => {
    await admin.adminAlignEmployeeLlmFromDeepseek(false)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('dry_run=false'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminAlignEmployeeLlmToAuto', async () => {
    await admin.adminAlignEmployeeLlmToAuto(false)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('align-llm-to-auto'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminAlignSingleEmployeeLlmToAuto', async () => {
    await admin.adminAlignSingleEmployeeLlmToAuto('pkg-1', true)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('pkg-1'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminListNoKeyEmployees', async () => {
    await admin.adminListNoKeyEmployees()
    expect(m).toHaveBeenCalledWith('/api/admin/duty-graph/no-key-employees')
  })

  it('verifyAdminDigestCode', async () => {
    await admin.verifyAdminDigestCode('abc123')
    expect(m).toHaveBeenCalledWith('/api/auth/verify-admin-digest-code', expect.objectContaining({ method: 'POST' }))
  })

  it('adminOpsAuditLogs with params', async () => {
    await admin.adminOpsAuditLogs({ employee_id: 'emp-1', limit: 10 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('employee_id=emp-1'))
  })

  it('adminOpsAuditLogs without params', async () => {
    await admin.adminOpsAuditLogs()
    expect(m).toHaveBeenCalledWith('/api/admin/ops/audit')
  })

  it('adminOpsStagedChanges', async () => {
    await admin.adminOpsStagedChanges({ status: 'pending', limit: 5 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('staged-changes'))
  })

  it('adminOpsApprovalTokens', async () => {
    await admin.adminOpsApprovalTokens({ limit: 10 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('approval-tokens'))
  })

  it('adminEmployeeExecutionMetrics', async () => {
    await admin.adminEmployeeExecutionMetrics('emp-1', { limit: 10, offset: 0 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('emp-1/execution-metrics'))
  })

  it('adminEmployeeExecutionCapability', async () => {
    await admin.adminEmployeeExecutionCapability('emp-1')
    expect(m).toHaveBeenCalledWith(expect.stringContaining('emp-1/execution-capability'))
  })

  it('adminEmployeeExecutionCapabilities', async () => {
    await admin.adminEmployeeExecutionCapabilities(['a', 'b'])
    expect(m).toHaveBeenCalledWith(expect.stringContaining('execution-capabilities'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminDutyGraphRunStart', async () => {
    await admin.adminDutyGraphRunStart({ target_employee_id: 'e1', task: 'test' })
    expect(m).toHaveBeenCalledWith('/api/admin/duty-graph/runs', expect.objectContaining({ method: 'POST' }))
  })

  it('adminDutyGraphRunDetail', async () => {
    await admin.adminDutyGraphRunDetail(42)
    expect(m).toHaveBeenCalledWith('/api/admin/duty-graph/runs/42')
  })

  it('adminDutyGraphHealth', async () => {
    await admin.adminDutyGraphHealth()
    expect(m).toHaveBeenCalledWith('/api/admin/duty-graph/health')
  })

  it('adminEmployeeAutonomyDashboard', async () => {
    await admin.adminEmployeeAutonomyDashboard(50)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('employee-autonomy/dashboard'))
  })

  it('adminEmployeeSuggestions', async () => {
    await admin.adminEmployeeSuggestions({ status: 'pending', limit: 10 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('employee-autonomy/suggestions'))
  })

  it('adminEmployeeSuggestionApprove', async () => {
    await admin.adminEmployeeSuggestionApprove(1, true)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('/approve'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeSuggestionReject', async () => {
    await admin.adminEmployeeSuggestionReject(1, 'bad')
    expect(m).toHaveBeenCalledWith(expect.stringContaining('/reject'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeSuggestionBatchReview', async () => {
    await admin.adminEmployeeSuggestionBatchReview({ ids: [1, 2], action: 'approve' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('batch-review'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeBriefTasks', async () => {
    await admin.adminEmployeeBriefTasks({ status: 'active' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('brief-tasks'))
  })

  it('adminEmployeeDispatchBriefTasks', async () => {
    await admin.adminEmployeeDispatchBriefTasks(10)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('dispatch/brief-tasks'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeDispatchSuggestions', async () => {
    await admin.adminEmployeeDispatchSuggestions(5)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('dispatch/suggestions'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeEvolutionScan', async () => {
    await admin.adminEmployeeEvolutionScan({ lookback_hours: 24 })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('evolution/scan'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeCollabThreads', async () => {
    await admin.adminEmployeeCollabThreads({ status: 'open' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('collab/threads'))
  })

  it('adminEmployeeCreateCollabThread', async () => {
    await admin.adminEmployeeCreateCollabThread({ title: 'test', participants: ['a'] })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('collab/threads'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminEmployeeCollabMessages', async () => {
    await admin.adminEmployeeCollabMessages(1, 50)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('threads/1/messages'))
  })

  it('adminEmployeePostCollabMessage', async () => {
    await admin.adminEmployeePostCollabMessage(1, { content: 'hello' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('threads/1/messages'), expect.objectContaining({ method: 'POST' }))
  })

  it('opsOrchestrateAsync', async () => {
    await admin.opsOrchestrateAsync({ task_description: 'test' })
    expect(m).toHaveBeenCalledWith('/api/ops/orchestrate/async', expect.objectContaining({ method: 'POST' }))
  })

  it('opsOrchestrateJob', async () => {
    await admin.opsOrchestrateJob('job-1')
    expect(m).toHaveBeenCalledWith('/api/ops/orchestrate/jobs/job-1')
  })

  it('opsOrchestrateJobs', async () => {
    await admin.opsOrchestrateJobs(10)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('jobs?limit=10'))
  })

  it('adminChangeRequestsList', async () => {
    await admin.adminChangeRequestsList({ status: 'pending' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('change-requests'))
  })

  it('adminChangeRequestDetail', async () => {
    await admin.adminChangeRequestDetail(1)
    expect(m).toHaveBeenCalledWith('/api/admin/change-requests/1')
  })

  it('adminChangeRequestApprove', async () => {
    await admin.adminChangeRequestApprove(1)
    expect(m).toHaveBeenCalledWith('/api/admin/change-requests/1/approve', expect.objectContaining({ method: 'POST' }))
  })

  it('adminChangeRequestReject', async () => {
    await admin.adminChangeRequestReject(1, { reason: 'bad' })
    expect(m).toHaveBeenCalledWith('/api/admin/change-requests/1/reject', expect.objectContaining({ method: 'POST' }))
  })

  it('adminListAiAccounts', async () => {
    await admin.adminListAiAccounts({ platform: 'wechat' })
    expect(m).toHaveBeenCalledWith(expect.stringContaining('ai-accounts'))
  })

  it('adminCreateAiAccount', async () => {
    await admin.adminCreateAiAccount({ platform: 'wechat', external_id: 'x', employee_id: 'e1', secret: {} })
    expect(m).toHaveBeenCalledWith('/api/admin/ai-accounts', expect.objectContaining({ method: 'POST' }))
  })

  it('adminUpdateAiAccount', async () => {
    await admin.adminUpdateAiAccount(1, { display_name: 'new' })
    expect(m).toHaveBeenCalledWith('/api/admin/ai-accounts/1', expect.objectContaining({ method: 'PATCH' }))
  })

  it('adminRotateAiAccountSecret', async () => {
    await admin.adminRotateAiAccountSecret(1, { key: 'val' })
    expect(m).toHaveBeenCalledWith('/api/admin/ai-accounts/1/rotate', expect.objectContaining({ method: 'POST' }))
  })

  it('adminDeleteAiAccount', async () => {
    await admin.adminDeleteAiAccount(1)
    expect(m).toHaveBeenCalledWith('/api/admin/ai-accounts/1', expect.objectContaining({ method: 'DELETE' }))
  })

  it('butlerQqStatus', async () => {
    await admin.butlerQqStatus()
    expect(m).toHaveBeenCalledWith('/api/agent/butler/qq/status')
  })

  it('adminYuangonOnboardStatus', async () => {
    await admin.adminYuangonOnboardStatus()
    expect(m).toHaveBeenCalledWith('/api/admin/yuangon-onboard/status')
  })

  it('adminYuangonOnboardRun', async () => {
    await admin.adminYuangonOnboardRun({ dry_run: true })
    expect(m).toHaveBeenCalledWith('/api/admin/yuangon-onboard/run', expect.objectContaining({ method: 'POST' }))
  })

  it('adminPurgeAllMods', async () => {
    await admin.adminPurgeAllMods()
    expect(m).toHaveBeenCalledWith('/api/admin/mods/purge-all', expect.objectContaining({ method: 'POST' }))
  })

  it('adminListCatalogComplaints', async () => {
    await admin.adminListCatalogComplaints('open', 10, 0)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('complaints'))
  })

  it('adminReviewCatalogComplaint', async () => {
    await admin.adminReviewCatalogComplaint(1, 'dismiss', 'note')
    expect(m).toHaveBeenCalledWith(expect.stringContaining('complaints/1/review'), expect.objectContaining({ method: 'POST' }))
  })

  it('adminListUsers', async () => {
    await admin.adminListUsers(50, 10)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('users?limit=50'))
  })

  it('adminSetUserAdmin', async () => {
    await admin.adminSetUserAdmin(1, true)
    expect(m).toHaveBeenCalledWith(expect.stringContaining('users/1/admin'), expect.objectContaining({ method: 'PUT' }))
  })

  it('adminListWallets', async () => {
    await admin.adminListWallets()
    expect(m).toHaveBeenCalledWith(expect.stringContaining('wallets'))
  })

  it('adminListTransactions', async () => {
    await admin.adminListTransactions()
    expect(m).toHaveBeenCalledWith(expect.stringContaining('transactions'))
  })
})
