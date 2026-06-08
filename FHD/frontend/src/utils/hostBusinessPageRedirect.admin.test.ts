import { describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: () => true,
}))

describe('hostBusinessPageRedirect admin console', () => {
  it('keeps host paths on admin SPA', async () => {
    const { resolveHostBusinessPagePath, resolveHostBusinessPageRedirect } = await import(
      '@/utils/hostBusinessPageRedirect'
    )
    expect(resolveHostBusinessPageRedirect('internal-customer-service')).toBeNull()
    expect(resolveHostBusinessPageRedirect('data-sources')).toBeNull()
    expect(resolveHostBusinessPagePath('/internal-customer-service')).toBe('/internal-customer-service')
  })
})
