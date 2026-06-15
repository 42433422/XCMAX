import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useImUnreadBadge } from './useImUnreadBadge'

vi.mock('@/api/im', () => ({
  fetchImUnreadTotal: vi.fn().mockResolvedValue(5),
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  isAdminConsoleSpa: vi.fn().mockReturnValue(false),
}))

vi.mock('vue-router', () => ({
  useRoute: vi.fn().mockReturnValue({ name: 'chat' }),
}))

describe('useImUnreadBadge', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('returns imUnreadTotal ref', () => {
    const { imUnreadTotal } = useImUnreadBadge()
    expect(imUnreadTotal).toBeDefined()
    expect(typeof imUnreadTotal.value).toBe('number')
  })

  it('returns refreshImUnreadTotal function', () => {
    const { refreshImUnreadTotal } = useImUnreadBadge()
    expect(typeof refreshImUnreadTotal).toBe('function')
  })

  it('refreshImUnreadTotal fetches and sets total', async () => {
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(5)
  })

  it('refreshImUnreadTotal sets 0 on public routes', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'login' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on login-prefixed routes', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'login-help' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on lan-gate route', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'lan-gate' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 on product-onboarding route', async () => {
    const { useRoute } = await import('vue-router')
    vi.mocked(useRoute).mockReturnValue({ name: 'product-onboarding' } as any)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
  })

  it('refreshImUnreadTotal sets 0 for admin console SPA', async () => {
    const { isAdminConsoleSpa } = await import('@/utils/adminConsoleUrl')
    vi.mocked(isAdminConsoleSpa).mockReturnValue(true)
    const { imUnreadTotal, refreshImUnreadTotal } = useImUnreadBadge()
    await refreshImUnreadTotal()
    expect(imUnreadTotal.value).toBe(0)
    vi.mocked(isAdminConsoleSpa).mockReturnValue(false)
  })
})
