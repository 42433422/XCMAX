import { describe, it, expect } from 'vitest'
import { XCAGI_VERSION_LABEL, loginEyebrow, normalizeLoginSku } from './loginBranding'

describe('loginBranding', () => {
  it('XCAGI_VERSION_LABEL uses major from package.json', () => {
    expect(XCAGI_VERSION_LABEL).toMatch(/^V\d+$/)
  })

  it('normalizeLoginSku', () => {
    expect(normalizeLoginSku('enterprise')).toBe('enterprise')
    expect(normalizeLoginSku('unknown')).toBe('generic')
  })

  it('loginEyebrow for skus', () => {
    expect(loginEyebrow('enterprise')).toContain('企业版')
    expect(loginEyebrow('personal')).toContain('个人版')
  })
})
