import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useWalletStore } from './wallet'
import { api } from '../api'
import { useAuthStore } from './auth'

vi.mock('../api', () => ({
  api: {
    balance: vi.fn(),
  },
}))

describe('wallet store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-05T00:00:00Z'))
    vi.mocked(api.balance).mockReset()
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('refreshes and normalizes balance', async () => {
    vi.mocked(api.balance).mockResolvedValue({ balance: '12.30', membership_reference_yuan: '5000' })
    const store = useWalletStore()

    await expect(store.refreshBalance()).resolves.toBe(12.3)

    expect(store.balance).toBe(12.3)
    expect(store.membershipReferenceYuan).toBe(5000)
    expect(store.lastUpdated).toBe(Date.now())
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('keeps the first timed out balance unknown and ends loading', async () => {
    vi.mocked(api.balance).mockRejectedValue(new Error('余额读取超时，请重试'))
    const store = useWalletStore()

    const pending = store.refreshBalance(0)
    expect(store.loading).toBe(true)
    await expect(pending).resolves.toBeNull()

    expect(store.balance).toBeNull()
    expect(store.membershipReferenceYuan).toBeNull()
    expect(store.lastUpdated).toBeNull()
    expect(store.error).toContain('重试')
    expect(store.loading).toBe(false)
    expect(api.balance).toHaveBeenCalledTimes(1)
  })

  it.each([0, '0'])('treats a confirmed zero balance %s as successful data', async (balance) => {
    vi.mocked(api.balance).mockResolvedValue({ balance, membership_reference_yuan: 0 })
    const store = useWalletStore()

    await expect(store.refreshBalance(0)).resolves.toBe(0)

    expect(store.balance).toBe(0)
    expect(store.membershipReferenceYuan).toBe(0)
    expect(store.lastUpdated).toBe(Date.now())
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
  })

  it('retains the last confirmed balance, membership reference and timestamp after failure', async () => {
    vi.mocked(api.balance).mockResolvedValueOnce({ balance: 86.5, membership_reference_yuan: 3000 })
    const store = useWalletStore()
    await store.refreshBalance(0)
    const confirmedAt = store.lastUpdated
    vi.setSystemTime(Date.now() + 30_000)
    vi.mocked(api.balance).mockRejectedValueOnce(new Error('余额读取超时，请重试'))

    await expect(store.refreshBalance(0)).resolves.toBeNull()

    expect(store.balance).toBe(86.5)
    expect(store.membershipReferenceYuan).toBe(3000)
    expect(store.lastUpdated).toBe(confirmedAt)
    expect(store.error).toContain('重试')
    expect(store.loading).toBe(false)
  })

  it('clears a prior error and updates confirmed data when a manual retry succeeds', async () => {
    vi.mocked(api.balance).mockRejectedValueOnce(new Error('网络不可用'))
    const store = useWalletStore()
    await store.refreshBalance(0)
    vi.setSystemTime(Date.now() + 60_000)
    vi.mocked(api.balance).mockResolvedValueOnce({ balance: 15, membership_reference_yuan: 1200 })

    const pending = store.refreshBalance(0)
    expect(store.loading).toBe(true)
    await expect(pending).resolves.toBe(15)

    expect(store.balance).toBe(15)
    expect(store.membershipReferenceYuan).toBe(1200)
    expect(store.lastUpdated).toBe(Date.now())
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('keeps loading during automatic retry delay and clears it after retry success', async () => {
    vi.mocked(api.balance)
      .mockRejectedValueOnce(new Error('短暂断网'))
      .mockResolvedValueOnce({ balance: 9, membership_reference_yuan: 100 })
    const store = useWalletStore()
    const pending = store.refreshBalance()

    await vi.advanceTimersByTimeAsync(999)
    expect(api.balance).toHaveBeenCalledTimes(1)
    expect(store.loading).toBe(true)
    expect(store.balance).toBeNull()
    await vi.advanceTimersByTimeAsync(1)
    await expect(pending).resolves.toBe(9)

    expect(api.balance).toHaveBeenCalledTimes(2)
    expect(store.loading).toBe(false)
    expect(store.error).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('ends loading after all automatic retries fail without erasing confirmed data', async () => {
    const store = useWalletStore()
    store.setBalance(22)
    store.setMembershipReferenceYuan(800)
    const confirmedAt = store.lastUpdated
    vi.mocked(api.balance).mockRejectedValue(new Error('余额读取超时'))

    const pending = store.refreshBalance()
    await vi.advanceTimersByTimeAsync(1_000)
    expect(store.loading).toBe(true)
    expect(api.balance).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(2_000)
    await expect(pending).resolves.toBeNull()

    expect(api.balance).toHaveBeenCalledTimes(3)
    expect(store.balance).toBe(22)
    expect(store.membershipReferenceYuan).toBe(800)
    expect(store.lastUpdated).toBe(confirmedAt)
    expect(store.loading).toBe(false)
    expect(store.error).toContain('重试')
    expect(vi.getTimerCount()).toBe(0)
  })

  it.each([null, undefined, '', '   ', 'bad', Number.NaN, Number.POSITIVE_INFINITY])(
    'does not convert invalid balance %s into confirmed zero data',
    async (balance) => {
      const response = { balance, membership_reference_yuan: 100 } as unknown as Awaited<ReturnType<typeof api.balance>>
      vi.mocked(api.balance).mockResolvedValue(response)
      const store = useWalletStore()

      await expect(store.refreshBalance(0)).resolves.toBeNull()

      expect(store.balance).toBeNull()
      expect(store.membershipReferenceYuan).toBeNull()
      expect(store.lastUpdated).toBeNull()
      expect(store.error).toBeTruthy()
      expect(store.loading).toBe(false)
    },
  )

  it.each([null, undefined, '', '   ', 'bad'])('keeps invalid setter input %s unknown', (value) => {
    const store = useWalletStore()

    store.setBalance(value)
    store.setMembershipReferenceYuan(value)

    expect(store.balance).toBeNull()
    expect(store.membershipReferenceYuan).toBeNull()
    expect(store.lastUpdated).toBeNull()
  })

  it('marks confirmed data stale without changing its value or confirmation time', () => {
    const store = useWalletStore()
    store.setBalance(18)
    store.setMembershipReferenceYuan(600)
    const confirmedAt = store.lastUpdated
    vi.setSystemTime(Date.now() + 10_000)

    store.markBalanceStale('当前余额暂时无法刷新')

    expect(store.balance).toBe(18)
    expect(store.membershipReferenceYuan).toBe(600)
    expect(store.lastUpdated).toBe(confirmedAt)
    expect(store.error).toBe('当前余额暂时无法刷新')
    expect(store.loading).toBe(false)
  })

  it('clears stale status and refreshes the timestamp when setBalance receives confirmed zero', () => {
    const store = useWalletStore()
    store.setBalance(18)
    store.markBalanceStale('当前余额暂时无法刷新')
    const confirmedAt = store.lastUpdated
    vi.setSystemTime(Date.now() + 10_000)

    store.setBalance(0)

    expect(store.balance).toBe(0)
    expect(store.error).toBeNull()
    expect(store.lastUpdated).toBe(Date.now())
    expect(store.lastUpdated).not.toBe(confirmedAt)
  })

  it('clears another account balance and rejects its delayed refresh response', async () => {
    const auth = useAuthStore()
    auth.user = { id: 1 } as typeof auth.user
    const store = useWalletStore()
    store.setBalance(100)
    store.setMembershipReferenceYuan(200)
    let finishOld!: (value: { balance: number }) => void
    vi.mocked(api.balance).mockReturnValueOnce(new Promise((resolve) => { finishOld = resolve }))
    const pending = store.refreshBalance(0)
    auth.user = { id: 2 } as typeof auth.user
    expect(store.balance).toBeNull()
    expect(store.membershipReferenceYuan).toBeNull()
    expect(store.lastUpdated).toBeNull()
    vi.mocked(api.balance).mockResolvedValueOnce({ balance: 7 })
    await store.refreshBalance(0)
    finishOld({ balance: 999 })
    await pending
    expect(store.balance).toBe(7)
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })
})
