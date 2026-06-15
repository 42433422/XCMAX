import { describe, expect, it } from 'vitest'
import {
  BRAND_LOGO_ICON_CANDIDATES,
  BRAND_LOGO_WORDMARK_CANDIDATES,
  startupAssetUrl,
} from './brandLogo'

describe('brandLogo', () => {
  it('startupAssetUrl joins base and startup path', () => {
    const url = startupAssetUrl('xc-logo-text.png')
    expect(url).toContain('startup/xc-logo-text.png')
    expect(url).not.toContain('//startup')
  })

  it('startupAssetUrl collapses duplicate slashes after base', () => {
    const url = startupAssetUrl('xc-logo-base.jpg')
    expect(url).toMatch(/startup\/xc-logo-base\.jpg$/)
  })

  it('wordmark candidates include png and jpg fallbacks', () => {
    expect(BRAND_LOGO_WORDMARK_CANDIDATES.length).toBeGreaterThanOrEqual(2)
    expect(BRAND_LOGO_WORDMARK_CANDIDATES.some((u) => u.includes('xc-logo-text.png'))).toBe(true)
  })

  it('icon candidates prefer base jpg', () => {
    expect(BRAND_LOGO_ICON_CANDIDATES[0]).toContain('xc-logo-base.jpg')
  })
})
