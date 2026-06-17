import { afterEach, describe, expect, it, vi } from 'vitest'
import { shouldRouteToProductOnboarding } from './useProductFlow'

describe('useProductFlow', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    localStorage.clear()
  })

  it('routes enterprise generic host builds through product onboarding', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    vi.stubEnv('VITE_XCAGI_EDITION', 'generic')
    vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '1')
    expect(shouldRouteToProductOnboarding('chat')).toBe(true)
  })

  it('does not route enterprise full host builds through product onboarding', () => {
    vi.stubEnv('VITE_XCAGI_PRODUCT_SKU', 'enterprise')
    vi.stubEnv('VITE_XCAGI_EDITION', 'full')
    vi.stubEnv('VITE_XCAGI_DEFAULT_PLATFORM_SHELL', '')
    expect(shouldRouteToProductOnboarding('chat')).toBe(false)
  })
})
