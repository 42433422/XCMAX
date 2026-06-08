import { describe, expect, it, vi } from 'vitest'
import { refreshLevelAndWalletAfterLlm } from './llmBillingRefresh'

vi.mock('../stores/auth', () => ({
  useAuthStore: vi.fn(() => ({
    refreshSession: vi.fn(),
  })),
}))

vi.mock('../stores/wallet', () => ({
  useWalletStore: vi.fn(() => ({
    refreshBalance: vi.fn(),
  })),
}))

describe('refreshLevelAndWalletAfterLlm', () => {
  it('calls refreshSession and refreshBalance via microtask', async () => {
    const { useAuthStore } = await import('../stores/auth')
    const { useWalletStore } = await import('../stores/wallet')
    const mockRefreshSession = vi.fn()
    const mockRefreshBalance = vi.fn()
    vi.mocked(useAuthStore).mockReturnValue({ refreshSession: mockRefreshSession } as any)
    vi.mocked(useWalletStore).mockReturnValue({ refreshBalance: mockRefreshBalance } as any)

    refreshLevelAndWalletAfterLlm()

    await new Promise((r) => setTimeout(r, 10))

    expect(mockRefreshSession).toHaveBeenCalledWith(true)
    expect(mockRefreshBalance).toHaveBeenCalled()
  })

  it('does not throw when stores are unavailable', async () => {
    const { useAuthStore } = await import('../stores/auth')
    vi.mocked(useAuthStore).mockImplementation(() => {
      throw new Error('Pinia not installed')
    })

    expect(() => refreshLevelAndWalletAfterLlm()).not.toThrow()
  })
})
