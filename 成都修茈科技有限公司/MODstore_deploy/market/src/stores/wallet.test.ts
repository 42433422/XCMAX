import { describe, expect, it, vi } from 'vitest'
import { useWalletStore } from './wallet'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    balance: vi.fn(),
  },
}))

describe('wallet store', () => {
  it('refreshes and normalizes balance', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: 12.3 })
    const store = useWalletStore()

    await store.refreshBalance()

    expect(store.balance).toBe(12.3)
  })

  it('clears invalid balance values', () => {
    const store = useWalletStore()

    store.setBalance('bad')

    expect(store.balance).toBeNull()
  })
})
