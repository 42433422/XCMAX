import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import WalletView from './WalletView.vue'
import { api } from '../api'
import { ApiError } from '../infrastructure/http/client'
import { useWalletStore } from '../stores/wallet'
import { useAuthStore } from '../stores/auth'
enableAutoUnmount(afterEach)

vi.mock('../api', () => ({ api: {
  walletOverview: vi.fn(), paymentMyPlan: vi.fn(), balance: vi.fn(), transactions: vi.fn(),
  paymentCheckout: vi.fn(), paymentDismissNonActiveOrders: vi.fn(), paymentOrders: vi.fn(), refundsMy: vi.fn(),
} }))
vi.mock('../stores/auth', async () => {
  const { reactive } = await import('vue')
  const auth = reactive({ isAdmin: false, user: { id: 1 } })
  return { useAuthStore: () => auth }
})
vi.mock('../composables/useWalletLlm', () => ({ useWalletLlm: () => ({}) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const emptyOverview = () => ({ wallet: { balance: 0, membership_reference_yuan: 0 }, transactions: [], orders: [], order_total: 0, refunds: [] })
const timeout = () => new ApiError('transport timeout details', 408)
const snapshot = () => ({
  wallet: { balance: 123.45, membership_reference_yuan: 200 },
  transactions: [{ id: 1, amount: 23.45, description: '已核对充值流水', type: 'recharge' }],
  orders: [{ out_trade_no: 'order-known', subject: '已核对订单', total_amount: 25, status: 'paid' }],
  order_total: 1,
  refunds: [{ id: 1, refund_no: 'refund-known', order_no: 'order-known', amount: 1, status: 'approved' }],
})
const mountWallet = () => mount(WalletView, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' }, WalletLlmCard: true } } })

beforeEach(() => {
  vi.clearAllMocks()
  const auth = useAuthStore()
  auth.user = { id: 1 } as typeof auth.user
  vi.mocked(api.paymentOrders).mockResolvedValue({ orders: [], total: 0 })
  vi.mocked(api.refundsMy).mockResolvedValue({ refunds: [] })
  vi.mocked(api.walletOverview).mockResolvedValue(emptyOverview())
  vi.mocked(api.paymentMyPlan).mockResolvedValue({ plan: null, quotas: [] })
  vi.mocked(api.transactions).mockResolvedValue({ transactions: [] })
})

describe('wallet read states', () => {
  it('shows confirmed zero and empty records only after successful reads', async () => {
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥0.00')
    expect(wrapper.text()).toContain('暂无订单')
    expect(wrapper.text()).toContain('暂无退款记录')
    expect(wrapper.text()).toContain('暂无交易记录')
    expect(wrapper.text()).not.toContain('加载失败')
    expect(wrapper.text()).not.toContain('ALIPAY_NOTIFY_URL')
    expect(api.paymentCheckout).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('ends an initial timeout with unknown balance and retry, without inventing empty records', async () => {
    vi.mocked(api.walletOverview).mockRejectedValue(timeout())
    vi.mocked(api.paymentMyPlan).mockRejectedValue(timeout())
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥--')
    expect(wrapper.text()).toContain('余额加载失败')
    expect(wrapper.text()).toContain('订单与退款记录加载失败')
    expect(wrapper.text()).toContain('套餐信息加载失败')
    expect(wrapper.text()).not.toContain('暂无订单')
    expect(wrapper.text()).not.toContain('暂无退款记录')
    expect(wrapper.text()).not.toContain('暂无交易记录')
    expect(wrapper.text()).not.toContain('刷新中')
    expect(wrapper.text()).not.toContain('transport timeout')
    expect(api.balance).not.toHaveBeenCalled()
    expect(api.transactions).not.toHaveBeenCalled()
    const retry = wrapper.get('.finance-head button')
    expect(retry.text()).toBe('重试')
    expect(retry.attributes('disabled')).toBeUndefined()

    vi.mocked(api.walletOverview).mockResolvedValue(emptyOverview())
    await retry.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('¥0.00')
    expect(wrapper.text()).toContain('暂无订单')
    expect(wrapper.text()).not.toContain('余额加载失败')
    expect(wrapper.text()).not.toContain('订单与退款记录加载失败')
    wrapper.unmount()
  })

  it('retains the last confirmed balance, orders, refunds, transactions and plan on refresh failure', async () => {
    vi.mocked(api.walletOverview).mockResolvedValue(snapshot())
    vi.mocked(api.paymentMyPlan).mockResolvedValue({ plan: { id: 'pro', name: '已核对套餐', price: 100 }, quotas: [{ quota_type: 'llm_calls', remaining: 9, total: 10 }] })
    const wrapper = mountWallet()
    await flushPromises()
    const store = useWalletStore()
    const updated = store.lastUpdated
    vi.mocked(api.walletOverview).mockRejectedValue(timeout())
    vi.mocked(api.paymentMyPlan).mockRejectedValue(timeout())
    await wrapper.get('.finance-head button').trigger('click')
    await flushPromises()
    await (wrapper.vm as unknown as { loadMyPlan(): Promise<void> }).loadMyPlan()
    await flushPromises()
    for (const expected of ['¥123.45', '已核对订单', 'refund-known', '已核对充值流水', '已核对套餐', '9/10', '上次读取的余额', '上次加载的记录', '上次读取的套餐信息']) {
      expect(wrapper.text()).toContain(expected)
    }
    expect(store.lastUpdated).toBe(updated)
    expect(store.membershipReferenceYuan).toBe(200)
    expect(wrapper.text()).not.toContain('暂无订单')
    vi.mocked(api.transactions).mockRejectedValue(timeout())
    const txRetry = wrapper.findAll('button').find((button) => button.text() === '重试读取交易')!
    await txRetry.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('已核对充值流水')
    expect(wrapper.text()).toContain('交易记录加载失败')

    vi.mocked(api.walletOverview).mockResolvedValue(emptyOverview())
    vi.mocked(api.paymentMyPlan).mockResolvedValue({ plan: null, quotas: [] })
    await wrapper.get('.finance-head button').trigger('click')
    await (wrapper.vm as unknown as { loadMyPlan(): Promise<void> }).loadMyPlan()
    await flushPromises()
    expect(wrapper.text()).toContain('¥0.00')
    expect(wrapper.text()).toContain('暂无订单')
    expect(wrapper.text()).toContain('暂无退款记录')
    expect(wrapper.text()).toContain('暂无交易记录')
    expect(wrapper.text()).not.toContain('已核对套餐')
    expect(wrapper.text()).not.toContain('加载失败')
    expect(store.error).toBeNull()
    wrapper.unmount()
  })

  it('does not treat a malformed successful response as a zero balance or empty records', async () => {
    vi.mocked(api.walletOverview).mockResolvedValue({ wallet: { balance: ' ' } })
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥--')
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).not.toContain('暂无订单')
    wrapper.unmount()
  })

  it('uses legacy read fallbacks only for a missing overview and keeps missing orders explicit', async () => {
    vi.mocked(api.walletOverview).mockRejectedValue(new ApiError('missing', 404))
    vi.mocked(api.balance).mockResolvedValue({ balance: 5 })
    vi.mocked(api.transactions).mockResolvedValue({ transactions: [] })
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥5.00')
    expect(wrapper.text()).toContain('暂无交易记录')
    expect(wrapper.text()).toContain('订单与退款记录加载失败')
    expect(wrapper.text()).not.toContain('暂无订单')
    expect(api.balance).toHaveBeenCalledTimes(1)
    expect(api.transactions).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('reads real orders and refunds when the deployed overview only returns wallet and transactions', async () => {
    vi.mocked(api.walletOverview).mockResolvedValue({ wallet: { balance: 5 }, transactions: [] })
    vi.mocked(api.paymentOrders).mockResolvedValue({ orders: snapshot().orders, total: 30 })
    vi.mocked(api.refundsMy).mockResolvedValue({ refunds: snapshot().refunds })
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥5.00')
    expect(wrapper.text()).toContain('已核对订单')
    expect(wrapper.text()).toContain('refund-known')
    expect(wrapper.text()).toContain('30')
    expect(api.paymentOrders).toHaveBeenCalledWith('', 20, 0, { timeoutMs: 10_000 })
    expect(api.refundsMy).toHaveBeenCalledWith({ timeoutMs: 10_000 })
    expect(wrapper.text()).not.toContain('暂无订单')
  })

  it('keeps a successful balance and transaction read when only the finance supplement fails', async () => {
    vi.mocked(api.walletOverview).mockResolvedValue({ wallet: { balance: 5 }, transactions: [] })
    vi.mocked(api.paymentOrders).mockRejectedValue(timeout())
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥5.00')
    expect(wrapper.text()).toContain('暂无交易记录')
    expect(wrapper.text()).toContain('订单与退款记录加载失败')
    expect(wrapper.text()).not.toContain('余额加载失败')
    expect(wrapper.text()).not.toContain('暂无订单')
    expect(wrapper.text()).not.toContain('暂无退款记录')
  })

  it('clears the previous account snapshot before a new account read fails', async () => {
    vi.mocked(api.walletOverview).mockResolvedValue(snapshot())
    vi.mocked(api.paymentMyPlan).mockResolvedValue({ plan: { id: 'old', name: '上个账号套餐', price: 10 }, quotas: [] })
    const wrapper = mountWallet()
    await flushPromises()
    expect(wrapper.text()).toContain('¥123.45')
    vi.mocked(api.walletOverview).mockRejectedValue(timeout())
    vi.mocked(api.paymentMyPlan).mockRejectedValue(timeout())
    const auth = useAuthStore()
    auth.user = { id: 2 } as typeof auth.user
    expect(useWalletStore().balance).toBeNull()
    await flushPromises()
    expect(wrapper.text()).toContain('¥--')
    for (const old of ['已核对订单', 'refund-known', '已核对充值流水', '上个账号套餐', '¥123.45']) expect(wrapper.text()).not.toContain(old)
    expect(wrapper.text()).toContain('加载失败')
  })

  it('discards delayed overview and plan results from the previous account', async () => {
    let resolveOld!: (value: ReturnType<typeof snapshot>) => void
    let resolvePlan!: (value: { plan: { id: string; name: string; price: number }; quotas: [] }) => void
    vi.mocked(api.walletOverview).mockReturnValueOnce(new Promise((resolve) => { resolveOld = resolve }))
    vi.mocked(api.paymentMyPlan).mockReturnValueOnce(new Promise((resolve) => { resolvePlan = resolve }))
    const wrapper = mountWallet()
    vi.mocked(api.walletOverview).mockResolvedValue({ ...emptyOverview(), wallet: { balance: 7 } })
    const auth = useAuthStore()
    auth.user = { id: 2 } as typeof auth.user
    await flushPromises()
    expect(wrapper.text()).toContain('¥7.00')
    resolveOld(snapshot())
    resolvePlan({ plan: { id: 'old', name: '上个账号套餐', price: 10 }, quotas: [] })
    await flushPromises()
    expect(wrapper.text()).toContain('¥7.00')
    for (const old of ['已核对订单', 'refund-known', '上个账号套餐', '¥123.45']) expect(wrapper.text()).not.toContain(old)
  })
})
