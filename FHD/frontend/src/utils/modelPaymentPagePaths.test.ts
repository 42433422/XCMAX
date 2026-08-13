import { describe, expect, it, vi, afterEach } from 'vitest'
import {
  resolveModelPaymentPagePath,
  resolveModelPaymentPageRedirectForRouteName,
} from './modelPaymentPagePaths'

describe('modelPaymentPagePaths', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('maps model-payment page when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPagePath('/model-payment')).toBe(
      '/settings?section=model-payment',
    )
    expect(resolveModelPaymentPagePath('/kitten-finance')).toBe(
      '/mod/xcagi-model-payment-bridge/kitten-finance',
    )
  })

  it('normalizes a host path without a leading slash', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPagePath('model-payment')).toBe('/settings?section=model-payment')
  })

  it('keeps the query suffix on the model-payment redirect', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPagePath('/model-payment?tab=bills')).toBe(
      '/settings?tab=bills',
    )
  })

  it('keeps host path when facade off', () => {
    vi.stubGlobal('localStorage', { getItem: () => null })
    expect(resolveModelPaymentPagePath('/kitten-finance')).toBe('/kitten-finance')
    expect(resolveModelPaymentPageRedirectForRouteName('kitten-finance')).toBeNull()
  })

  it('keeps unknown host path unchanged when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPagePath('/unknown/page')).toBe('/unknown/page')
  })

  it('maps redirect route name when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPageRedirectForRouteName('model-payment')).toBe(
      '/settings?section=model-payment',
    )
    expect(resolveModelPaymentPageRedirectForRouteName('kitten-finance')).toBe(
      '/mod/xcagi-model-payment-bridge/kitten-finance',
    )
  })

  it('returns null for unmapped redirect route name when facade on', () => {
    vi.stubGlobal('localStorage', { getItem: () => '1' })
    expect(resolveModelPaymentPageRedirectForRouteName('some-unknown-route')).toBeNull()
  })
})
