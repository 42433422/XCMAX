import { describe, expect, it } from 'vitest'

import { desktopOpsDeepLink } from './opsDeepLinks'

describe('opsDeepLinks', () => {
  it('builds base desktop duty URL', () => {
    expect(desktopOpsDeepLink()).toBe('xcagi://ops/duty')
  })

  it('encodes employee id in desktop duty URL', () => {
    expect(desktopOpsDeepLink('change-request-auditor')).toBe(
      'xcagi://ops/duty?employee=change-request-auditor',
    )
    expect(desktopOpsDeepLink('a/b c')).toBe('xcagi://ops/duty?employee=a%2Fb%20c')
  })
})
