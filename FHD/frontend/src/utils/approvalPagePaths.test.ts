import { describe, expect, it, vi, afterEach } from 'vitest'
import { resolveApprovalPagePath, resolveApprovalPageRedirectForRouteName } from './approvalPagePaths'

describe('approvalPagePaths', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('maps approval hub when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveApprovalPagePath('/approval-hub/workspace')).toBe(
      '/mod/xcagi-approval-bridge/approval-hub/workspace',
    )
    expect(resolveApprovalPageRedirectForRouteName('approval-workspace')).toBe(
      '/mod/xcagi-approval-bridge/approval-hub/workspace',
    )
  })

  it('keeps host path when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(resolveApprovalPagePath('/approval-hub/workspace')).toBe('/approval-hub/workspace')
    expect(resolveApprovalPageRedirectForRouteName('approval-workspace')).toBeNull()
  })

  it('normalizes a host path without a leading slash', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveApprovalPagePath('approval-hub/workspace')).toBe(
      '/mod/xcagi-approval-bridge/approval-hub/workspace',
    )
  })

  it('keeps unknown host path unchanged when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveApprovalPagePath('/unknown/page')).toBe('/unknown/page')
  })

  it('returns null for unmapped route name when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveApprovalPageRedirectForRouteName('some-unknown-route')).toBeNull()
  })

  it('preserves query string when mapping a known host path', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveApprovalPagePath('/approval-hub/workspace?tab=pending')).toBe(
      '/mod/xcagi-approval-bridge/approval-hub/workspace?tab=pending',
    )
  })
})
