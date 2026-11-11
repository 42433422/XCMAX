import { beforeEach, describe, expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({
  mode: { enabled: true, mode: 'auto' }, identity: { localUserId: 7, tenantId: 3 },
  currentSession: true, details: vi.fn(), approve: vi.fn(),
}))
vi.mock('@/api/approval', () => ({ approvalApi: { getRequestDetails: mocks.details, approve: mocks.approve } }))
vi.mock('./useApprovalMode', () => ({ useApprovalMode: () => ({ state: mocks.mode }) }))
vi.mock('@/utils/authSessionCache', () => ({ captureAuthSession: () => () => mocks.currentSession }))
vi.mock('@/utils/tenantStorageScopeRuntime', () => ({ getRuntimeTenantStorageScopeInput: () => mocks.identity }))
import { approveDockingIfAutomatic } from './useAutomaticDockingApproval'
let sequence = 0
function batch() { return { success: true, batch_id: `batch-${++sequence}`, status: 'awaiting_approval', approval_id: sequence, approval_request_id: `request-${sequence}` } }
function ready(value: ReturnType<typeof batch>, overrides: Record<string, unknown> = {}) {
  mocks.details.mockResolvedValue({ success: true, data: { id: value.approval_id, request_no: value.approval_request_id,
    applicant_id: 7, business_type: 'workflow_tool', status: 'pending',
    business_data: { tool_id: 'data_docking', action: 'auto_ingest', params: { batch_id: value.batch_id } }, ...overrides } })
  mocks.approve.mockResolvedValue({ success: false, accepted: true, data: { id: value.approval_id, request_no: value.approval_request_id, status: 'approved' } })
}
beforeEach(() => { vi.clearAllMocks(); mocks.mode.enabled = true; mocks.mode.mode = 'auto'; mocks.currentSession = true; mocks.identity.localUserId = 7; mocks.identity.tenantId = 3 })
describe('automatic docking approval', () => {
  it('uses the normal authorized endpoint and accepts queued receipts without claiming import success', async () => {
    const value = batch(); ready(value)
    expect(await approveDockingIfAutomatic(value, () => true)).toEqual({ attempted: true, accepted: true })
    expect(mocks.approve).toHaveBeenCalledWith(value.approval_id, 7, expect.stringContaining('自动审批模式'))
    expect(value.status).toBe('awaiting_approval')
  })
  it.each(['manual', 'disabled'])('does not approve in %s mode', async (mode) => {
    const value = batch(); ready(value); mocks.mode.mode = mode === 'manual' ? 'manual' : 'auto'; mocks.mode.enabled = mode !== 'disabled'
    expect((await approveDockingIfAutomatic(value, () => true)).attempted).toBe(false)
    expect(mocks.details).not.toHaveBeenCalled(); expect(mocks.approve).not.toHaveBeenCalled()
  })
  it.each([{ applicant_id: 8 }, { request_no: 'other' }, { status: 'rejected' }, { business_data: { tool_id: 'other' } }])('rejects mismatched details %j', async (overrides) => {
    const value = batch(); ready(value, overrides)
    expect((await approveDockingIfAutomatic(value, () => true)).accepted).toBe(false)
    expect(mocks.approve).not.toHaveBeenCalled()
  })
  it('does not submit after account changes during the read', async () => {
    const value = batch(); ready(value); mocks.details.mockImplementationOnce(async () => { mocks.currentSession = false; return {} })
    await approveDockingIfAutomatic(value, () => true)
    expect(mocks.approve).not.toHaveBeenCalled()
  })
  it('does not submit after automatic mode is disabled during the read', async () => {
    const value = batch(); ready(value); mocks.details.mockImplementationOnce(async () => { mocks.mode.enabled = false; return {} })
    await approveDockingIfAutomatic(value, () => true)
    expect(mocks.approve).not.toHaveBeenCalled()
  })
  it('coalesces duplicate calls and never retries denied or uncertain decisions', async () => {
    const value = batch(); ready(value); mocks.approve.mockResolvedValue({ success: false, message: '当前用户无权审批' })
    const outcomes = await Promise.all([approveDockingIfAutomatic(value, () => true), approveDockingIfAutomatic(value, () => true)])
    expect(outcomes.every(result => result.accepted === false)).toBe(true)
    await approveDockingIfAutomatic(value, () => true)
    expect(mocks.approve).toHaveBeenCalledTimes(1)
  })
  it('does not accept an unrelated successful receipt', async () => {
    const value = batch(); ready(value); mocks.approve.mockResolvedValue({ success: true, data: { id: 99999, status: 'approved' } })
    expect((await approveDockingIfAutomatic(value, () => true)).accepted).toBe(false)
  })
})
