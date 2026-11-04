import { beforeEach, describe, expect, it, vi } from 'vitest'

const getRun = vi.fn()
const continueRun = vi.fn()
vi.mock('./agentRuns', () => ({ default: { getRun: (...a: unknown[]) => getRun(...a), continueRun: (...a: unknown[]) => continueRun(...a) } }))

import { APPROVAL_GRANT_MISSING_MESSAGE, APPROVAL_GRANT_REJECTED_MESSAGE, approveRunWithFreshGrant } from './agentRunApproval'

const waiting = (grant: string) => ({ data: { status: 'waiting_user' }, approval: { grant } })
const forbidden = () => Object.assign(new Error('approval_grant 无效、过期或与当前步骤不匹配'), { status: 403 })

describe('approveRunWithFreshGrant (#2289)', () => {
  beforeEach(() => {
    getRun.mockReset()
    continueRun.mockReset()
  })

  it('re-fetches a fresh grant once after a 403 and continues', async () => {
    getRun.mockResolvedValueOnce(waiting('old')).mockResolvedValueOnce(waiting('new'))
    continueRun.mockRejectedValueOnce(forbidden()).mockResolvedValueOnce({ success: true })
    await expect(approveRunWithFreshGrant('run_1')).resolves.toEqual({ success: true })
    expect(continueRun).toHaveBeenNthCalledWith(2, 'run_1', { approval_grant: 'new' })
  })

  it('surfaces a readable error instead of failing silently when 403 persists', async () => {
    getRun.mockResolvedValue(waiting('g'))
    continueRun.mockRejectedValue(forbidden())
    await expect(approveRunWithFreshGrant('run_1')).rejects.toThrow(APPROVAL_GRANT_REJECTED_MESSAGE)
    expect(continueRun).toHaveBeenCalledTimes(2)
  })

  it('does not call continue without a waiting step grant', async () => {
    getRun.mockResolvedValue({ data: { status: 'completed' } })
    await expect(approveRunWithFreshGrant('run_1')).rejects.toThrow(APPROVAL_GRANT_MISSING_MESSAGE)
    expect(continueRun).not.toHaveBeenCalled()
  })

  it('abandons the approval when the caller is no longer current', async () => {
    getRun.mockResolvedValue(waiting('g'))
    await expect(approveRunWithFreshGrant('run_1', { isCurrent: () => false })).resolves.toBeNull()
    expect(continueRun).not.toHaveBeenCalled()
  })

  it('does not retry non-approval errors', async () => {
    getRun.mockResolvedValue(waiting('g'))
    continueRun.mockRejectedValue(Object.assign(new Error('busy'), { status: 503 }))
    await expect(approveRunWithFreshGrant('run_1', { runtimeContext: { source: 'x' } })).rejects.toThrow('busy')
    expect(continueRun).toHaveBeenCalledWith('run_1', { approval_grant: 'g', runtime_context: { source: 'x' } })
    expect(continueRun).toHaveBeenCalledTimes(1)
  })
})
