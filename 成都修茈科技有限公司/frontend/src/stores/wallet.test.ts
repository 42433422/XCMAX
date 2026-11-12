import { describe, expect, it, vi } from 'vitest'
import { useWalletStore } from './wallet'
import { api } from '../api'

vi.mock('../api', () => ({
  api: {
    balance: vi.fn(),
  },
}))

describe('wallet store', () => {
  it('刷新并归一化余额（字符串数字 → number）', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: '12.30' })
    const store = useWalletStore()

    await store.refreshBalance()

    expect(store.balance).toBe(12.3)
  })

  it('refreshBalance 失败时清空 balance', async () => {
    vi.mocked(api.balance).mockRejectedValue(new Error('network'))
    const store = useWalletStore()
    store.setBalance(99)

    const result = await store.refreshBalance()

    expect(result).toBeNull()
    expect(store.balance).toBeNull()
  })

  it('setBalance 拒绝非法值', () => {
    const store = useWalletStore()
    store.setBalance('not-a-number')
    expect(store.balance).toBeNull()
  })

  it('setBalance 接受合法数值', () => {
    const store = useWalletStore()
    store.setBalance('42.5')
    expect(store.balance).toBe(42.5)
  })

  it('clear 重置余额', () => {
    const store = useWalletStore()
    store.setBalance(100)
    store.clear()
    expect(store.balance).toBeNull()
  })
})
