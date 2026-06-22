import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const lowMocks = vi.hoisted(() => ({
  route: {
    params: { orderId: 'ord_1' } as Record<string, unknown>,
    query: {} as Record<string, unknown>,
  },
  router: {
    replace: vi.fn(),
    push: vi.fn(),
  },
  refreshSession: vi.fn(async () => undefined),
  isAdmin: { value: true },
  confirmDanger: vi.fn(async () => true),
  walletBalance: { value: null as number | null },
  membershipReferenceYuan: { value: 0 },
  walletSetBalance: vi.fn((value: number) => {
    lowMocks.walletBalance.value = Number(value)
  }),
  walletSetMembershipReferenceYuan: vi.fn((value: number) => {
    lowMocks.membershipReferenceYuan.value = Number(value)
  }),
  walletRefreshBalance: vi.fn(async () => 0),
  walletClear: vi.fn(),
  api: {
    paymentQuery: vi.fn(),
    paymentCancelOrder: vi.fn(),
    paymentCheckout: vi.fn(),
    developerListTokens: vi.fn(),
    developerCreateToken: vi.fn(),
    developerRevokeToken: vi.fn(),
    developerExportKeyBundle: vi.fn(),
    developerListKeyExportAudit: vi.fn(),
    adminEmployeeAutonomyDashboard: vi.fn(),
    adminEmployeeSuggestions: vi.fn(),
    adminEmployeeBriefTasks: vi.fn(),
    adminEmployeeCollabThreads: vi.fn(),
    adminEmployeeCollabMessages: vi.fn(),
    adminEmployeeSuggestionApprove: vi.fn(),
    adminEmployeeSuggestionReject: vi.fn(),
    adminEmployeeSuggestionBatchReview: vi.fn(),
    adminEmployeeDispatchBriefTasks: vi.fn(),
    adminEmployeeDispatchSuggestions: vi.fn(),
    adminEmployeeEvolutionScan: vi.fn(),
    adminEmployeeCreateCollabThread: vi.fn(),
    adminEmployeePostCollabMessage: vi.fn(),
    listMods: vi.fn(),
    adminListUsers: vi.fn(),
    createMod: vi.fn(),
    importZIP: vi.fn(),
    modAiScaffold: vi.fn(),
    registerWorkflowEmployeeCatalog: vi.fn(),
    deleteMod: vi.fn(),
    adminPurgeAllMods: vi.fn(),
    llmStatus: vi.fn(),
    llmCatalog: vi.fn(),
    llmSavePreferences: vi.fn(),
    llmSaveCredentials: vi.fn(),
    llmDeleteCredentials: vi.fn(),
    paymentMyPlan: vi.fn(),
    walletOverview: vi.fn(),
    paymentDismissNonActiveOrders: vi.fn(),
    transactions: vi.fn(),
  },
}))

vi.mock('vue-router', () => ({
  useRoute: () => lowMocks.route,
  useRouter: () => lowMocks.router,
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('./api', () => ({ api: lowMocks.api }))

vi.mock('./stores/auth', () => ({
  useAuthStore: () => ({
    isAdmin: lowMocks.isAdmin,
    refreshSession: lowMocks.refreshSession,
  }),
}))

vi.mock('./stores/wallet', () => ({
  useWalletStore: () => ({
    balance: lowMocks.walletBalance,
    membershipReferenceYuan: lowMocks.membershipReferenceYuan,
    setBalance: lowMocks.walletSetBalance,
    setMembershipReferenceYuan: lowMocks.walletSetMembershipReferenceYuan,
    refreshBalance: lowMocks.walletRefreshBalance,
    clear: lowMocks.walletClear,
  }),
}))

vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  const { isRef, ref } = await import('vue')
  return {
    ...actual,
    storeToRefs: (store: Record<string, unknown>) => {
      const out: Record<string, unknown> = {}
      for (const key of Object.keys(store)) {
        const value = store[key]
        if (isRef(value)) {
          out[key] = value
        } else if (value && typeof value === 'object' && 'value' in value) {
          ;(value as { __v_isRef?: boolean }).__v_isRef = true
          out[key] = value
        } else {
          out[key] = ref(value)
        }
      }
      return out
    },
  }
})

vi.mock('./composables/useDangerConfirm', () => ({
  confirmDanger: (...args: unknown[]) => lowMocks.confirmDanger(...args),
}))

vi.mock('./infrastructure/http/client', () => {
  class ApiError extends Error {}
  return {
    ApiError,
    requestJson: vi.fn(async () => ({ provider: 'openai' })),
  }
})

const globalOptions = {
  stubs: {
    RouterLink: { template: '<a><slot /></a>' },
    Transition: false,
    Teleport: true,
  },
}

async function flushPromises(times = 4) {
  for (let i = 0; i < times; i++) await Promise.resolve()
}

const pendingOrder = {
  out_trade_no: 'ord_1',
  subject: '企业版',
  total_amount: '99.00',
  status: 'pending',
  created_at: new Date(Date.now() - 16 * 60 * 1000).toISOString(),
  pay_type: 'page',
  plan_id: 'plan_enterprise',
  order_kind: 'plan',
}

const activeToken = {
  id: 1,
  name: 'CI',
  prefix: 'sk_ci',
  scopes: ['mod:sync', 'catalog:read', 'workflow:execute'],
  created_at: '2026-06-18T00:00:00Z',
  last_used_at: null,
  expires_at: null,
  revoked_at: null,
  is_active: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useRealTimers()
  lowMocks.route.params = { orderId: 'ord_1' }
  lowMocks.route.query = {}
  lowMocks.isAdmin.value = true
  lowMocks.walletBalance.value = null
  lowMocks.membershipReferenceYuan.value = 0
  Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
  Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
  Object.defineProperty(window, 'prompt', { configurable: true, value: vi.fn(() => '原因') })
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: vi.fn(async () => undefined) },
  })
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:bundle') })
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  sessionStorage.clear()
  localStorage.clear()
  document.body.innerHTML = ''
})

describe('low coverage view business branches', () => {
  it('covers checkout pending, manual reconciliation, paid flash, and precreate retry', async () => {
    vi.useFakeTimers()
    lowMocks.api.paymentQuery
      .mockResolvedValueOnce({ ...pendingOrder })
      .mockResolvedValueOnce({ ...pendingOrder, status: 'paid' })
      .mockResolvedValueOnce({ ...pendingOrder, status: 'closed' })
      .mockResolvedValueOnce({ ...pendingOrder, out_trade_no: 'ord_2', qr_code: 'qr://new', pay_type: 'precreate' })
    lowMocks.api.paymentCheckout.mockResolvedValueOnce({ ok: true, type: 'precreate', order_id: 'ord_2' })
    lowMocks.api.paymentCancelOrder.mockRejectedValueOnce(new Error('already closed'))
    const { default: PaymentCheckoutView } = await import('./views/PaymentCheckoutView.vue')
    const wrapper = mount(PaymentCheckoutView, { global: globalOptions })
    await flushPromises()

    expect(wrapper.text()).toContain('待支付')
    expect(wrapper.text()).toContain('浏览器跳转支付宝')
    await (wrapper.vm as unknown as { manualRefreshStatus: () => Promise<void> }).manualRefreshStatus()
    await flushPromises()
    expect(lowMocks.refreshSession).toHaveBeenCalledWith(true)
    expect(sessionStorage.getItem('modstore_svip_ladder_reveal')).toBe('1')
    expect(wrapper.text()).toContain('支付成功')

    await vi.advanceTimersByTimeAsync(14_000)
    await (wrapper.vm as unknown as { fetchOrder: () => Promise<void> }).fetchOrder()
    await flushPromises()
    expect(wrapper.text()).toContain('已关闭')

    await (wrapper.vm as unknown as { retryPayment: () => Promise<void> }).retryPayment()
    await flushPromises()
    expect(lowMocks.api.paymentCancelOrder).toHaveBeenCalledWith('ord_1')
    expect(lowMocks.router.replace).toHaveBeenCalledWith({ name: 'checkout', params: { orderId: 'ord_2' } })
    expect(wrapper.text()).toContain('打开支付宝扫码支付')
    wrapper.unmount()
  })

  it('covers checkout failed envelopes, transient warnings, polling errors and labels', async () => {
    lowMocks.route.query = { sign: 'x'.repeat(24), method: 'alipay.trade.page.pay', trade_no: '202606180000' }
    lowMocks.api.paymentQuery
      .mockResolvedValueOnce({ ok: false, message: '订单不存在' })
      .mockResolvedValueOnce({ ...pendingOrder, qr_code: '', pay_type: 'wap' })
      .mockResolvedValueOnce({ ok: false, message: '暂时无法确认' })
      .mockRejectedValueOnce(new Error('poll down'))
    const { default: PaymentCheckoutView } = await import('./views/PaymentCheckoutView.vue')
    const wrapper = mount(PaymentCheckoutView, { global: globalOptions })
    await flushPromises()
    expect(wrapper.text()).toContain('订单不存在')

    await (wrapper.vm as unknown as { fetchOrder: () => Promise<void> }).fetchOrder()
    await flushPromises()
    expect(wrapper.text()).toContain('支付宝（手机网站）')
    await (wrapper.vm as unknown as { pollOrder: () => Promise<void> }).pollOrder()
    await flushPromises()
    expect(wrapper.text()).toContain('暂时无法确认')
    await (wrapper.vm as unknown as { pollOrder: () => Promise<void> }).pollOrder()
    await flushPromises()
    expect((wrapper.vm as unknown as { statusText: (v?: string) => string }).statusText('missing')).toBe('missing')
    expect((wrapper.vm as unknown as { payTypeLabel: (v?: string) => string }).payTypeLabel('wechat_native')).toContain('微信')
    wrapper.unmount()
  })

  it('covers checkout retry failure, unsupported payment type, expiry, and visibility guards', async () => {
    const closedWalletOrder = {
      ...pendingOrder,
      status: 'closed',
      order_kind: 'wallet',
      item_id: 0,
      plan_id: '',
      total_amount: '25.50',
      pay_type: 'precreate',
      created_at: new Date(Date.now() - 20 * 60 * 1000).toISOString(),
    }
    lowMocks.api.paymentQuery.mockResolvedValue({ ...closedWalletOrder })
    lowMocks.api.paymentCancelOrder.mockResolvedValue({ ok: true })
    lowMocks.api.paymentCheckout
      .mockResolvedValueOnce({ ok: false, message: 'checkout denied' })
      .mockResolvedValueOnce({ ok: true, type: 'bank_transfer' })
      .mockRejectedValueOnce(new Error('checkout down'))

    const { default: PaymentCheckoutView } = await import('./views/PaymentCheckoutView.vue')
    const wrapper = mount(PaymentCheckoutView, { global: globalOptions })
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      retryPayment: () => Promise<void>
      manualRefreshStatus: () => Promise<void>
      refetchVisiblePending: () => Promise<void>
      looksLikeAlipayReturnQuery: (q: Record<string, string>) => boolean
      order: typeof closedWalletOrder | null
      refreshing: boolean
      error: string
      isExpired: boolean
      payTypeLabel: (v?: string) => string
    }

    expect(vm.isExpired).toBe(false)
    vm.order = { ...closedWalletOrder, status: 'pending' }
    await wrapper.vm.$nextTick()
    expect(vm.isExpired).toBe(true)

    await vm.retryPayment()
    expect(lowMocks.api.paymentCheckout).toHaveBeenCalledWith(expect.objectContaining({
      wallet_recharge: true,
      total_amount: 25.5,
    }))
    expect(vm.error).toContain('checkout denied')

    vm.order = { ...closedWalletOrder }
    await vm.retryPayment()
    expect(vm.error).toContain('不支持')

    vm.order = { ...closedWalletOrder }
    await vm.retryPayment()
    expect(vm.error).toContain('checkout down')

    vm.refreshing = true
    await vm.manualRefreshStatus()
    expect(vm.refreshing).toBe(true)
    vm.refreshing = false

    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    vm.order = { ...closedWalletOrder, status: 'pending' }
    await vm.refetchVisiblePending()
    expect(lowMocks.api.paymentQuery).toHaveBeenCalled()
    expect(vm.looksLikeAlipayReturnQuery({ sign: 'x'.repeat(21) })).toBe(true)
    expect(vm.looksLikeAlipayReturnQuery({ method: 'alipay.trade.page.pay' })).toBe(true)
    expect(vm.looksLikeAlipayReturnQuery({ trade_no: '202606180000' })).toBe(true)
    expect(vm.looksLikeAlipayReturnQuery({})).toBe(false)
    expect(vm.payTypeLabel(undefined)).toBe('—')
    wrapper.unmount()
  })

  it('covers checkout alipay return burst sync, fetch warnings, and paid polling', async () => {
    vi.useFakeTimers()
    lowMocks.route.query = { sign: 'x'.repeat(24), trade_no: '202606180001' }
    lowMocks.api.paymentQuery
      .mockResolvedValueOnce({ ...pendingOrder, status: 'pending', qr_code: '' })
      .mockResolvedValueOnce({ ...pendingOrder, status: 'pending', qr_code: '' })
      .mockResolvedValueOnce({ ...pendingOrder, status: 'paid', qr_code: 'qr://paid', plan_id: 'plan_enterprise' })

    const { default: PaymentCheckoutView } = await import('./views/PaymentCheckoutView.vue')
    const wrapper = mount(PaymentCheckoutView, { global: globalOptions })
    const vm = wrapper.vm as unknown as {
      burstSyncActive: boolean
      error: string
      fetchOrder: () => Promise<void>
      order: typeof pendingOrder | null
      pollOrder: () => Promise<void>
      qrCode: string
      transientWarning: string
    }
    await flushPromises()

    expect(vm.burstSyncActive).toBe(true)
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1700)
    await flushPromises()
    expect(lowMocks.refreshSession).toHaveBeenCalledWith(true)
    expect(vm.qrCode).toBe('qr://paid')

    lowMocks.api.paymentQuery.mockRejectedValueOnce(new Error('fetch jitter'))
    vm.order = { ...pendingOrder, status: 'pending' }
    await vm.fetchOrder()
    expect(vm.transientWarning).toContain('fetch jitter')

    lowMocks.api.paymentQuery.mockRejectedValueOnce(new Error('cold fetch down'))
    vm.order = null
    await vm.fetchOrder()
    expect(vm.error).toContain('cold fetch down')

    lowMocks.api.paymentQuery.mockResolvedValueOnce({ ...pendingOrder, status: 'pending', qr_code: '' })
    await vm.pollOrder()
    expect(vm.qrCode).toBe('')
    wrapper.unmount()
  })

  it('covers developer token create, copy, revoke, encrypted export, and audit', async () => {
    lowMocks.api.developerListTokens.mockResolvedValue([activeToken, {
      ...activeToken,
      id: 2,
      name: 'Expired',
      expires_at: '2000-01-01T00:00:00Z',
      is_active: true,
    }, {
      ...activeToken,
      id: 3,
      name: 'Revoked',
      revoked_at: '2026-01-01T00:00:00Z',
      is_active: false,
    }])
    lowMocks.api.developerCreateToken.mockResolvedValue({
      ...activeToken,
      id: 4,
      name: 'Local',
      scopes: ['catalog:read'],
      token: 'sk_full_once',
    })
    lowMocks.api.developerExportKeyBundle.mockResolvedValue({
      cipher_b64: Buffer.from('bundle').toString('base64'),
    })
    lowMocks.api.developerListKeyExportAudit.mockResolvedValue({
      events: [{ id: 1, created_at: '2026-06-18T00:00:00Z', action: 'export', success: true, detail: 'ok', client_ip: '127.0.0.1' }],
    })
    const { default: DeveloperTokensPanel } = await import('./views/developer/DeveloperTokensPanel.vue')
    const wrapper = mount(DeveloperTokensPanel, { global: globalOptions })
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      openCreate: () => void
      addScope: (s: string) => void
      submitCreate: () => Promise<void>
      copyJustCreated: () => Promise<void>
      dismissJustCreated: () => void
      selectAllActiveForExport: () => void
      runExportBundle: () => Promise<void>
      toggleAudit: () => Promise<void>
      revoke: (row: typeof activeToken) => Promise<void>
      draft: { name: string; scopesCsv: string; expiresDays: string }
      desktopPubB64: string
      exportPassword: string
      exportSelected: number[]
      errMsg: string
      formatTime: (iso: string | null) => string
      formatExpiresShort: (iso: string | null) => string
      scopesSummary: (scopes: string[]) => string
      statusOf: (row: typeof activeToken) => { text: string }
    }

    expect(wrapper.text()).toContain('CI')
    vm.openCreate()
    vm.addScope('llm:use')
    vm.draft.name = 'Local'
    vm.draft.expiresDays = ''
    await vm.submitCreate()
    await flushPromises()
    expect(lowMocks.confirmDanger).toHaveBeenCalled()
    expect(lowMocks.api.developerCreateToken).toHaveBeenCalledWith('Local', expect.arrayContaining(['llm:use']), null)
    expect(wrapper.text()).toContain('sk_full_once')
    await vm.copyJustCreated()
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('sk_full_once')
    vm.dismissJustCreated()

    vm.selectAllActiveForExport()
    expect(vm.exportSelected).toEqual([1, 2])
    vm.desktopPubB64 = 'MFkw'
    vm.exportPassword = 'pw'
    await vm.runExportBundle()
    await flushPromises()
    expect(lowMocks.api.developerExportKeyBundle).toHaveBeenCalledWith(expect.objectContaining({
      token_ids: [1, 2],
      rotate_source_tokens: true,
    }))
    expect(URL.createObjectURL).toHaveBeenCalled()

    await vm.toggleAudit()
    await flushPromises()
    expect(lowMocks.api.developerListKeyExportAudit).toHaveBeenCalledWith(30)
    await vm.revoke(activeToken)
    expect(lowMocks.api.developerRevokeToken).toHaveBeenCalledWith(1)
    expect(vm.formatTime(null)).toBe('—')
    expect(vm.formatExpiresShort(null)).toBe('永不过期')
    expect(vm.scopesSummary([])).toBe('未配置权限')
    expect(vm.statusOf({ ...activeToken, revoked_at: 'x' }).text).toBe('已吊销')
    wrapper.unmount()
  })

  it('covers developer token validation, fallback copy, export errors, and rejected actions', async () => {
    lowMocks.api.developerListTokens
      .mockRejectedValueOnce({ detail: 'list failed' })
      .mockResolvedValueOnce([activeToken])
      .mockResolvedValueOnce([activeToken])
      .mockResolvedValueOnce([activeToken])
    lowMocks.api.developerCreateToken.mockRejectedValueOnce(new Error('create failed'))
    lowMocks.api.developerExportKeyBundle
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('export failed'))
    lowMocks.api.developerListKeyExportAudit.mockRejectedValueOnce(new Error('audit failed'))
    lowMocks.api.developerRevokeToken.mockRejectedValueOnce(new Error('revoke failed'))
    lowMocks.confirmDanger.mockResolvedValueOnce(false).mockResolvedValue(true)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: vi.fn(async () => { throw new Error('clipboard denied') }) },
    })
    Object.defineProperty(document, 'execCommand', {
      configurable: true,
      value: vi.fn(() => true),
    })

    const { default: DeveloperTokensPanel } = await import('./views/developer/DeveloperTokensPanel.vue')
    const wrapper = mount(DeveloperTokensPanel, { global: globalOptions })
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      refresh: () => Promise<void>
      openCreate: () => void
      closeCreate: () => void
      addScope: (s: string) => void
      submitCreate: () => Promise<void>
      copyJustCreated: () => Promise<void>
      dismissJustCreated: () => void
      onExportCheck: (id: number, ev: Event) => void
      runExportBundle: () => Promise<void>
      toggleAudit: () => Promise<void>
      revoke: (row: typeof activeToken) => Promise<void>
      errMsg: string
      showDialog: boolean
      submitBusy: boolean
      draft: { name: string; scopesCsv: string; expiresDays: string }
      justCreated: { token: string; meta: typeof activeToken } | null
      copied: boolean
      desktopPubB64: string
      exportPassword: string
      exportSelected: number[]
      exportAudit: unknown[]
      statusOf: (row: typeof activeToken) => { text: string }
      scopesSummary: (scopes: string[]) => string
      formatTime: (iso: string | null) => string
      formatExpiresShort: (iso: string | null) => string
    }

    expect(vm.errMsg).toContain('list failed')
    await vm.refresh()
    expect(vm.errMsg).toBe('')

    vm.openCreate()
    await vm.submitCreate()
    expect(vm.errMsg).toContain('请填写')
    vm.draft.name = 'Denied'
    await vm.submitCreate()
    expect(lowMocks.api.developerCreateToken).not.toHaveBeenCalled()
    vm.draft.name = 'Will Fail'
    await vm.submitCreate()
    expect(vm.errMsg).toContain('create failed')
    vm.submitBusy = true
    vm.closeCreate()
    expect(vm.showDialog).toBe(true)
    vm.submitBusy = false
    vm.closeCreate()
    expect(vm.showDialog).toBe(false)

    vm.justCreated = { token: 'sk_once', meta: { ...activeToken, scopes: ['catalog:read'] } }
    await vm.copyJustCreated()
    expect(document.execCommand).toHaveBeenCalledWith('copy')
    expect(vm.copied).toBe(true)
    vm.copied = false
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => false) })
    vm.dismissJustCreated()
    expect(vm.justCreated).toBeTruthy()
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
    vm.dismissJustCreated()
    expect(vm.justCreated).toBeNull()

    vm.desktopPubB64 = ''
    await vm.runExportBundle()
    expect(vm.errMsg).toContain('公钥')
    vm.desktopPubB64 = 'MFkw'
    vm.exportPassword = ''
    await vm.runExportBundle()
    expect(vm.errMsg).toContain('密码')
    vm.exportPassword = 'pw'
    vm.exportSelected = []
    await vm.runExportBundle()
    expect(vm.errMsg).toContain('至少')
    vm.onExportCheck(1, { target: { checked: true } } as unknown as Event)
    expect(vm.exportSelected).toEqual([1])
    vm.onExportCheck(1, { target: { checked: false } } as unknown as Event)
    expect(vm.exportSelected).toEqual([])
    vm.exportSelected = [1]
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => false) })
    await vm.runExportBundle()
    expect(lowMocks.api.developerExportKeyBundle).not.toHaveBeenCalled()
    Object.defineProperty(window, 'confirm', { configurable: true, value: vi.fn(() => true) })
    await vm.runExportBundle()
    expect(vm.errMsg).toContain('cipher_b64')
    await vm.runExportBundle()
    expect(vm.errMsg).toContain('export failed')

    await vm.toggleAudit()
    await flushPromises()
    expect(vm.exportAudit).toEqual([])
    await vm.revoke(activeToken)
    expect(vm.errMsg).toContain('revoke failed')
    expect(vm.statusOf({ ...activeToken, expires_at: '2000-01-01T00:00:00Z' }).text).toBe('已过期')
    expect(vm.scopesSummary(['a', 'b', 'c'])).toBe('a · b +1')
    expect(vm.formatTime('not-a-date')).toBeTruthy()
    expect(vm.formatExpiresShort('not-a-date')).toBeTruthy()
    wrapper.unmount()
  })

  it('covers admin employee autonomy dashboard actions and collaboration flows', async () => {
    const suggestion = {
      id: 10,
      source_employee_id: 'emp-a',
      target_employee_ids: ['emp-b'],
      kind: 'patch',
      risk_level: 'low',
      status: 'pending',
      summary: '建议修复',
    }
    lowMocks.api.adminEmployeeAutonomyDashboard.mockResolvedValue({ counts: { suggestions_pending: 1 } })
    lowMocks.api.adminEmployeeSuggestions.mockResolvedValue({ items: [suggestion] })
    lowMocks.api.adminEmployeeBriefTasks.mockResolvedValue({ items: [{ id: 1, owner_employee_id: 'emp-a', task_brief: '写摘要' }] })
    lowMocks.api.adminEmployeeCollabThreads.mockResolvedValue({ items: [{ id: 7, title: '协作' }] })
    lowMocks.api.adminEmployeeCollabMessages.mockResolvedValue({ items: [{ id: 1, sender_employee_id: 'emp-a', content: 'hello' }] })
    lowMocks.api.adminEmployeeEvolutionScan.mockResolvedValue({ processed: 2, created: 1 })
    lowMocks.api.adminEmployeeDispatchBriefTasks.mockResolvedValue({ queued: 1 })
    lowMocks.api.adminEmployeeDispatchSuggestions.mockResolvedValue({ queued: 2 })
    lowMocks.api.adminEmployeeCreateCollabThread.mockResolvedValue({ thread_id: 8 })
    const { default: AdminEmployeeAutonomyView } = await import('./views/AdminEmployeeAutonomyView.vue')
    const wrapper = mount(AdminEmployeeAutonomyView, { global: globalOptions })
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      toggleSuggestion: (id: number) => void
      approveSuggestion: (id: number) => Promise<void>
      rejectSuggestion: (id: number) => Promise<void>
      batchReview: (action: 'approve' | 'reject') => Promise<void>
      dispatchQueues: () => Promise<void>
      triggerEvolutionScan: () => Promise<void>
      createThread: () => Promise<void>
      sendMessage: () => Promise<void>
      loadMessages: () => Promise<void>
      selectedSuggestionIds: number[]
      selectedThreadId: number
      newThreadTitle: string
      newThreadParticipants: string
      messageDraft: string
      info: string
    }

    expect(wrapper.text()).toContain('员工自治统一面板')
    vm.toggleSuggestion(10)
    expect(vm.selectedSuggestionIds).toEqual([10])
    vm.toggleSuggestion(10)
    expect(vm.selectedSuggestionIds).toEqual([])
    await vm.approveSuggestion(10)
    expect(lowMocks.api.adminEmployeeSuggestionApprove).toHaveBeenCalledWith(10, true)
    await vm.rejectSuggestion(10)
    expect(lowMocks.api.adminEmployeeSuggestionReject).toHaveBeenCalledWith(10, '原因')

    await vm.batchReview('approve')
    expect(vm.info).toContain('请先勾选')
    vm.selectedSuggestionIds = [10]
    await vm.batchReview('reject')
    expect(lowMocks.api.adminEmployeeSuggestionBatchReview).toHaveBeenCalledWith(expect.objectContaining({
      ids: [10],
      action: 'reject',
      dispatch_now: true,
    }))
    await vm.dispatchQueues()
    expect(lowMocks.api.adminEmployeeDispatchBriefTasks).toHaveBeenCalledWith(40)
    expect(lowMocks.api.adminEmployeeDispatchSuggestions).toHaveBeenCalledWith(40)
    await vm.triggerEvolutionScan()
    expect(lowMocks.api.adminEmployeeEvolutionScan).toHaveBeenCalledWith(expect.objectContaining({ lookback_hours: 24 }))

    vm.newThreadTitle = ''
    await vm.createThread()
    expect(vm.info).toContain('请输入线程标题')
    vm.newThreadTitle = '新协作'
    vm.newThreadParticipants = 'emp-a, emp-b emp-c'
    await vm.createThread()
    expect(lowMocks.api.adminEmployeeCreateCollabThread).toHaveBeenCalledWith(expect.objectContaining({
      title: '新协作',
      participants: ['emp-a', 'emp-b', 'emp-c'],
    }))
    vm.selectedThreadId = 8
    vm.messageDraft = '请处理'
    await vm.sendMessage()
    expect(lowMocks.api.adminEmployeePostCollabMessage).toHaveBeenCalledWith(8, expect.objectContaining({
      content: '请处理',
    }))
    vm.selectedThreadId = 0
    await vm.loadMessages()
    wrapper.unmount()
  })

  it('covers repository filters, scaffold, import, register, delete, and purge flows', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(new Date('2026-06-18T12:00:00Z').getTime())
    const modA = {
      id: 'mod-a',
      name: 'Alpha 能力',
      version: '1.2.0',
      artifact: 'mod',
      ok: true,
      primary: true,
      industry: { id: 'retail', name: '零售' },
      library_blurb: '货架简介',
      description: '备用描述',
      updated_at: '2026-06-18T11:59:30Z',
      usage_scene: '',
      path: '/tmp/library/alpha-folder',
      workflow_employees: [{ id: 'emp-a', label: '客服员工', panel_summary: '负责咨询' }],
    }
    const modB = {
      id: 'bundle-b',
      name: 'Bundle',
      version: '2.0.0',
      artifact: 'bundle',
      ok: false,
      description: '很长的描述 '.repeat(30),
      industry_id: 'finance',
      workflow_employees: [],
    }
    lowMocks.api.listMods.mockResolvedValue({ data: [modA, modB] })
    lowMocks.api.adminListUsers.mockResolvedValue({
      users: [
        { id: 1, username: '企业一', mod_ids: ['mod-a'] },
        { id: 2, email: 'corp@example.com', mod_ids: ['mod-a', 'bundle-b'] },
      ],
    })
    lowMocks.api.registerWorkflowEmployeeCatalog.mockResolvedValue({ package: { id: 'pkg-a', version: '1.0.0' } })
    lowMocks.api.deleteMod.mockResolvedValue({ ok: true })
    lowMocks.api.adminPurgeAllMods.mockResolvedValue({ removed_dir_count: 2, removed_user_mod_rows: 3 })
    lowMocks.api.modAiScaffold.mockResolvedValue({ id: 'ai-mod' })
    lowMocks.api.importZIP.mockResolvedValue({ id: 'zip-mod' })
    lowMocks.api.createMod
      .mockRejectedValueOnce(new Error('已存在'))
      .mockResolvedValueOnce({ id: 'new-mod-2' })
    const { default: RepositoryView } = await import('./views/RepositoryView.vue')
    const wrapper = mount(RepositoryView, { global: globalOptions })
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      mods: typeof modA[]
      filteredMods: typeof modA[]
      versionOptions: string[]
      hasActiveShelfFilters: boolean
      shelfQ: string
      shelfIndustry: string
      shelfStatus: string
      shelfVersion: string
      shelfTest: string
      shelfScope: string
      usageLoadError: string
      authoringIndustryId: string
      createIndustryId: string
      createName: string
      showCreate: boolean
      scaffoldBrief: string
      scaffoldIndustryId: string
      scaffoldIdHint: string
      showScaffold: boolean
      message: string
      headerMoreOpen: boolean
      openCardMenuId: string
      persistAuthoringIndustry: () => void
      clearShelfFilters: () => void
      toggleCardMenu: (id: string) => void
      onDocumentPointerDown: (ev: PointerEvent) => void
      formatUpdatedAt: (raw?: string) => string
      getUsageScene: (m: typeof modA) => string
      modIndustryId: (m: typeof modA) => string
      modIndustryLabel: (m: typeof modA) => string
      modShelfStatus: (m: typeof modA) => string
      usageText: (id: string) => string
      modIdFromDisplayName: (name: string) => string
      isCreateModConflictError: (e: unknown) => boolean
      flash: (msg: string, ok?: boolean) => void
      libraryFolderForDeleteApi: (m?: typeof modA | null) => string
      modIdForDeleteApi: (m?: typeof modA | null) => string
      getBlurb: (m: typeof modA) => string
      artifactLabel: (a?: string) => string
      isBundle: (m: typeof modA) => boolean
      viewMod: (id: string) => void
      testModInSandbox: (id: string) => void
      registerKey: (id: string, idx: number) => string
      registerWorkflowToCatalog: (id: string, idx: number) => Promise<void>
      goEmployeePrefill: (id: string, emp: Record<string, unknown>, idx?: number) => void
      openScaffoldModal: () => void
      submitScaffold: () => Promise<void>
      load: (opts?: { cacheBust?: boolean }) => Promise<void>
      loadEnterpriseUsage: () => Promise<void>
      submitCreate: () => Promise<void>
      onImport: (ev: Event) => Promise<void>
      deleteModFromLibrary: (m: typeof modA) => Promise<void>
      purgeRepoLibraryAndLocalState: () => Promise<void>
      onPurgeFromMenu: () => Promise<void>
      onDeleteFromCardMenu: (m: typeof modA) => Promise<void>
    }

    expect(vm.mods).toHaveLength(2)
    expect(vm.versionOptions).toEqual(['2.0.0', '1.2.0'])
    vm.shelfQ = 'alpha'
    vm.shelfIndustry = 'retail'
    vm.shelfStatus = 'primary'
    vm.shelfVersion = '1.2.0'
    vm.shelfTest = 'pass'
    vm.shelfScope = 'assigned'
    expect(vm.hasActiveShelfFilters).toBe(true)
    expect(vm.filteredMods.map((m) => m.id)).toEqual(['mod-a'])
    vm.clearShelfFilters()
    expect(vm.hasActiveShelfFilters).toBe(false)
    vm.shelfStatus = 'bundle'
    expect(vm.filteredMods.map((m) => m.id)).toEqual(['bundle-b'])
    vm.clearShelfFilters()
    vm.shelfTest = 'fix'
    expect(vm.filteredMods.map((m) => m.id)).toEqual(['bundle-b'])
    vm.clearShelfFilters()
    vm.shelfScope = 'unassigned'
    expect(vm.filteredMods).toHaveLength(0)
    vm.clearShelfFilters()
    vm.shelfVersion = 'missing'
    expect(vm.filteredMods).toHaveLength(0)
    vm.clearShelfFilters()

    expect(vm.modIndustryId(modA)).toBe('retail')
    expect(vm.modIndustryLabel(modA)).toContain('retail')
    expect(vm.modIndustryLabel({ ...modA, industry: '制造业' })).toBe('制造业')
    expect(vm.modShelfStatus(modA)).toBe('primary')
    expect(vm.modShelfStatus(modB)).toBe('bundle')
    expect(vm.usageText('mod-a')).toContain('企业一')
    vm.usageLoadError = '403'
    expect(vm.usageText('missing')).toContain('未读取')
    vm.usageLoadError = ''
    expect(vm.formatUpdatedAt('2026-06-18T11:59:30Z')).toBe('刚刚')
    expect(vm.formatUpdatedAt('2026-06-18T11:30:00Z')).toContain('分钟前')
    expect(vm.formatUpdatedAt('2026-06-18T08:00:00Z')).toContain('小时前')
    expect(vm.formatUpdatedAt('2026-06-10T12:00:00Z')).toContain('天前')
    expect(vm.formatUpdatedAt('2026-05-01T12:00:00Z')).toContain('2026')
    expect(vm.formatUpdatedAt('bad')).toBe('')
    expect(vm.getUsageScene(modA)).toContain('工作流员工')
    expect(vm.getUsageScene({ ...modA, workflow_employees: [], primary: false, artifact: 'bundle' })).toContain('组合包')
    expect(vm.modIdFromDisplayName('123 中文 Name')).toMatch(/^m-/)
    expect(vm.isCreateModConflictError(new Error('409'))).toBe(true)
    expect(vm.libraryFolderForDeleteApi(modA)).toBe('alpha-folder')
    expect(vm.modIdForDeleteApi(modA)).toBe('mod-a')
    expect(vm.getBlurb({ ...modA, library_blurb: '', description: 'abc '.repeat(80) }).endsWith('…')).toBe(true)
    expect(vm.artifactLabel('employee_pack')).toBe('员工包')
    expect(vm.artifactLabel('bundle')).toBe('组合包')
    expect(vm.isBundle(modB)).toBe(true)

    vm.toggleCardMenu('mod-a')
    expect(vm.openCardMenuId).toBe('mod-a')
    vm.headerMoreOpen = true
    vm.onDocumentPointerDown(new PointerEvent('pointerdown', { bubbles: true }))
    expect(vm.openCardMenuId).toBe('')
    expect(vm.headerMoreOpen).toBe(false)

    vm.viewMod('mod-a')
    vm.testModInSandbox('mod-a')
    vm.testModInSandbox('')
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'mod-authoring', params: { modId: 'mod-a' } })
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'sandbox', query: { modId: 'mod-a', host: '/sandbox', autoPush: '1' } })
    expect(vm.registerKey('mod-a', 1)).toBe('mod-a:1')
    vm.goEmployeePrefill('mod-a', { id: 'emp-a', panel_summary: '负责咨询' }, 2)
    expect(sessionStorage.getItem('modstore_employee_prefill')).toContain('mod-a')

    localStorage.removeItem('modstore_token')
    await vm.registerWorkflowToCatalog('mod-a', 0)
    expect(vm.message).toContain('请先登录')
    localStorage.setItem('modstore_token', 'token')
    await vm.registerWorkflowToCatalog('mod-a', 0)
    expect(lowMocks.api.registerWorkflowEmployeeCatalog).toHaveBeenCalledWith('mod-a', 0)

    await vm.deleteModFromLibrary(modA)
    expect(lowMocks.api.deleteMod).toHaveBeenCalledWith('mod-a')
    localStorage.removeItem('modstore_token')
    await vm.deleteModFromLibrary(modA)
    expect(vm.message).toContain('请先登录')
    localStorage.setItem('modstore_token', 'token')
    await vm.deleteModFromLibrary({ ...modA, id: '', path: '' })
    lowMocks.api.deleteMod.mockRejectedValueOnce(new Error('delete down'))
    await vm.deleteModFromLibrary(modA)
    expect(vm.message).toContain('delete down')
    vm.headerMoreOpen = true
    await vm.onPurgeFromMenu()
    expect(lowMocks.api.adminPurgeAllMods).toHaveBeenCalled()
    localStorage.removeItem('modstore_token')
    await vm.purgeRepoLibraryAndLocalState()
    expect(vm.message).toContain('请先登录')
    localStorage.setItem('modstore_token', 'token')
    lowMocks.api.adminPurgeAllMods.mockRejectedValueOnce(new Error('purge down'))
    await vm.purgeRepoLibraryAndLocalState()
    expect(vm.message).toContain('purge down')
    await vm.onDeleteFromCardMenu(modA)
    expect(lowMocks.api.deleteMod).toHaveBeenCalled()

    vm.openScaffoldModal()
    expect(vm.showScaffold).toBe(true)
    vm.scaffoldBrief = '短'
    await vm.submitScaffold()
    expect(vm.message).toContain('至少')
    vm.scaffoldBrief = '生成零售客服员工包'
    vm.scaffoldIndustryId = ''
    await vm.submitScaffold()
    expect(vm.message).toContain('目标行业')
    vm.scaffoldBrief = '生成零售客服员工包'
    vm.scaffoldIndustryId = 'retail'
    vm.scaffoldIdHint = 'ai-mod'
    await vm.submitScaffold()
    expect(lowMocks.api.modAiScaffold).toHaveBeenCalledWith(expect.stringContaining('目标行业'), 'ai-mod', true, 'retail')
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'mod-authoring', params: { modId: 'ai-mod' } })

    vm.createName = ''
    await vm.submitCreate()
    expect(vm.message).toContain('请填写名称')
    vm.createName = '123 New Mod'
    vm.createIndustryId = 'retail'
    await vm.submitCreate()
    expect(lowMocks.api.createMod).toHaveBeenNthCalledWith(1, expect.stringMatching(/^m-/), '123 New Mod', 'retail')
    expect(lowMocks.api.createMod).toHaveBeenNthCalledWith(2, expect.stringContaining('-2'), '123 New Mod', 'retail')
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'mod-authoring', params: { modId: 'new-mod-2' } })
    lowMocks.api.createMod.mockRejectedValueOnce(new Error('create down'))
    vm.createName = 'Broken Mod'
    await vm.submitCreate()
    expect(vm.message).toContain('create down')

    await vm.onImport({ target: { files: [], value: 'x' } } as unknown as Event)
    const fileInput = { files: [new File(['zip'], 'mod.zip', { type: 'application/zip' })], value: 'x' }
    await vm.onImport({ target: fileInput } as unknown as Event)
    expect(fileInput.value).toBe('')
    expect(lowMocks.api.importZIP).toHaveBeenCalledWith(fileInput.files[0], true)
    lowMocks.api.importZIP.mockRejectedValueOnce(new Error('import down'))
    const badImport = { files: [new File(['zip'], 'bad.zip', { type: 'application/zip' })], value: 'x' }
    await vm.onImport({ target: badImport } as unknown as Event)
    expect(vm.message).toContain('import down')

    lowMocks.api.adminListUsers.mockRejectedValueOnce(new Error('no auth'))
    await vm.loadEnterpriseUsage()
    expect(vm.usageLoadError).toBe('no auth')
    vm.authoringIndustryId = 'retail'
    vm.persistAuthoringIndustry()
    expect(localStorage.getItem('modstore_authoring_industry_id')).toBe('retail')
    wrapper.unmount()
  })

  it('covers wallet overview, recharge, LLM catalog, BYOK, and formatting branches', async () => {
    localStorage.setItem('modstore_token', 'token')
    const catalog = {
      fernet_configured: true,
      cache_ttl_seconds: 600,
      preferences: { provider: 'openai', model: 'gpt-4o' },
      category_labels: { llm: '语言', image: '图像', video: '视频' },
      billing_settings: { service_fee_multiplier: 1.2 },
      providers: [
        {
          provider: 'openai',
          label: 'OpenAI',
          models: ['gpt-4o', 'gpt-image-1'],
          models_detailed: [
            {
              id: 'gpt-4o',
              category: 'llm',
              capability: { l3_status: 'approved', l1_status: 'pending', platform_billing_ok: false },
              pricing: { input_per_million: 2, output_per_million: 8 },
            },
            { id: 'gpt-image-1', category: 'image', capability: {}, pricing: { image_per_1k: 40 } },
          ],
          media_counts: { image: 1, video: 0 },
          fetched_at: '2026-06-18T10:00:00Z',
        },
        {
          provider: 'deepseek',
          label: 'Deep Seek',
          models: ['deepseek-chat'],
          models_detailed: [{ id: 'deepseek-chat', category: 'llm' }],
          media_counts: { image: 0, video: 0 },
          fetched_at: 'bad-date',
          error: 'quota expired',
          fetch_source: 'live_error',
        },
      ],
    }
    lowMocks.api.llmStatus.mockResolvedValue({
      providers: [
        { provider: 'openai', has_user_override: true, has_platform_key: true },
        { provider: 'deepseek', has_user_override: true, has_platform_key: false },
      ],
    })
    lowMocks.api.llmCatalog.mockResolvedValue(catalog)
    lowMocks.api.llmSavePreferences.mockResolvedValue({ ok: true })
    lowMocks.api.llmSaveCredentials.mockResolvedValue({ ok: true })
    lowMocks.api.llmDeleteCredentials.mockResolvedValue({ ok: true })
    lowMocks.api.paymentMyPlan.mockResolvedValue({
      plan: { name: 'Pro', expires_at: '2026-07-01T00:00:00Z' },
      quotas: [{ quota_type: 'llm_calls', remaining: 9, total: 10 }],
    })
    lowMocks.api.walletOverview.mockResolvedValue({
      wallet: { balance: 88, membership_reference_yuan: 100 },
      transactions: [
        { id: 1, type: 'recharge', amount: '10', created_at: '2026-06-18T00:00:00Z', description: '入账' },
        { id: 2, type: 'llm_wallet_charge', amount: '-2.5', created_at: '2026-06-18T01:00:00Z', description: '扣费' },
      ],
      orders: [
        { out_trade_no: 'ord_1', subject: '订单', total_amount: '9.9', status: 'paid' },
        { out_trade_no: 'ord_2', subject: '关闭单', total_amount: '1', status: 'closed' },
      ],
      order_total: 8,
      refunds: [{ id: 1, refund_no: 'rf_1', order_no: 'ord_1', amount: '1.2', status: 'approved' }],
    })
    lowMocks.api.paymentDismissNonActiveOrders.mockResolvedValue({ ok: true, dismissed: 2 })
    lowMocks.api.transactions.mockResolvedValue({ transactions: [{ id: 3, type: 'purchase', amount: '3' }] })
    lowMocks.api.paymentCheckout
      .mockResolvedValueOnce({ ok: false, message: '下单失败' })
      .mockResolvedValueOnce({ ok: true, type: 'precreate', order_id: 'recharge_1' })
    const { default: WalletView } = await import('./views/WalletView.vue')
    const wrapper = mount(WalletView, { global: globalOptions })
    await flushPromises(8)

    const vm = wrapper.vm as unknown as {
      payAmount: number | null
      payNote: string
      amountError: string
      payErr: string
      payHint: string
      byokBulkPaste: string
      byokKey: Record<string, string>
      byokBaseUrl: Record<string, string>
      llmProviderFilter: 'all' | 'image' | 'video'
      selectedProvider: string
      selectedModel: string
      iconLoadFailed: Record<string, boolean>
      llmNote: string
      llmErr: string
      catalog: typeof catalog
      transactions: Array<{ amount: number }>
      visibleTransactions: Array<unknown>
      hiddenTxCount: number
      balanceGaugeFill: number
      currentProviderBlock: unknown
      catalogProvidersSorted: Array<{ provider: string }>
      byokConfiguredCount: number
      byokImportDisabled: boolean
      catalogSyncMeta: { ttlSec: number } | null
      categoryLabel: (cat: string) => string
      modelOptionLabel: (row: Record<string, unknown>) => string
      providerTilePriceHint: (block: Record<string, unknown>) => string
      modelsForCategory: (cat: string) => Array<unknown>
      providerTileMediaTags: (block: Record<string, unknown>) => Array<{ kind: string }>
      formatCatalogFetchedAt: (iso?: string) => string
      llmTileShowsImg: (block: Record<string, unknown>) => boolean
      providerTileState: (block: Record<string, unknown>) => string
      llmTileIconFailKey: (block: Record<string, unknown>) => string
      providerTileTitle: (block: Record<string, unknown>) => string
      llmByokCatalogDanger: (provider: string) => boolean
      llmInitials: (label: string) => string
      syncSelectionFromServerPrefs: () => void
      validateSelectionAfterRefresh: () => void
      refreshCatalog: (manual: boolean) => Promise<void>
      selectProvider: (id: string) => void
      persistPreferences: () => Promise<void>
      saveByok: (provider: string) => Promise<void>
      importByokBulk: () => Promise<void>
      clearByok: (provider: string) => Promise<void>
      onVisibilityRefresh: () => void
      loadMyPlan: () => Promise<void>
      quotaLabel: (t: string) => string
      txnTypeLabel: (t: string) => string
      orderStatusText: (s: string) => string
      refundStatusText: (s: string) => string
      money: (v: unknown) => string
      goOrder: (order: Record<string, unknown>) => void
      loadWalletOverview: () => Promise<void>
      dismissNonActiveOrders: () => Promise<void>
      loadBalance: () => Promise<void>
      loadTransactions: () => Promise<void>
      normalizeTransaction: (t: Record<string, unknown>) => { amount: number }
      validateAmount: () => void
      startAlipayRecharge: () => Promise<void>
      formatDate: (iso?: string) => string
    }

    expect(vm.balanceGaugeFill).toBe(88)
    expect(vm.transactions[0].amount).toBe(10)
    expect(vm.categoryLabel('llm')).toBe('语言')
    expect(vm.modelOptionLabel(catalog.providers[0].models_detailed[0])).toContain('L3已通过')
    expect(vm.providerTilePriceHint(catalog.providers[0])).toBeNull()
    expect(vm.modelsForCategory('image')).toHaveLength(1)
    expect(vm.providerTileMediaTags(catalog.providers[0]).map((t) => t.kind)).toContain('image')
    expect(vm.formatCatalogFetchedAt('bad')).toBe('bad')
    expect(vm.providerTileState(catalog.providers[0])).toBe('ok')
    expect(vm.providerTileTitle(catalog.providers[1])).toContain('已过期')
    expect(vm.llmByokCatalogDanger('deepseek')).toBe(true)
    expect(vm.llmInitials('Deep Seek')).toBe('DS')
    vm.iconLoadFailed[vm.llmTileIconFailKey(catalog.providers[0])] = true
    expect(vm.llmTileShowsImg(catalog.providers[0])).toBe(false)
    vm.llmProviderFilter = 'image'
    expect(vm.catalogProvidersSorted.map((p) => p.provider)).toEqual(['openai'])

    vm.selectProvider('deepseek')
    expect(vm.selectedModel).toBe('deepseek-chat')
    await vm.persistPreferences()
    expect(lowMocks.api.llmSavePreferences).toHaveBeenCalledWith('deepseek', 'deepseek-chat')
    vm.byokKey.openai = ''
    await vm.saveByok('openai')
    expect(vm.llmErr).toContain('请先粘贴')
    vm.byokKey.openai = 'sk-openai'
    vm.byokBaseUrl.openai = 'https://api.openai.test'
    await vm.saveByok('openai')
    expect(lowMocks.api.llmSaveCredentials).toHaveBeenCalledWith('openai', 'sk-openai', 'https://api.openai.test')

    vm.byokBulkPaste = 'OPENAI_API_KEY=sk-bulk\nDEEPSEEK_API_KEY=sk-deep'
    expect(vm.byokImportDisabled).toBe(false)
    await vm.importByokBulk()
    expect(lowMocks.api.llmSaveCredentials).toHaveBeenCalledWith('deepseek', 'sk-deep', null)
    await vm.clearByok('openai')
    expect(lowMocks.api.llmDeleteCredentials).toHaveBeenCalledWith('openai')
    await vm.refreshCatalog(true)
    expect(lowMocks.api.llmCatalog).toHaveBeenCalledWith(true)

    expect(vm.quotaLabel('storage_mb')).toContain('存储')
    expect(vm.txnTypeLabel('wallet_refund')).toBe('退款入账')
    expect(vm.orderStatusText('partial_refunded')).toBe('部分退款')
    expect(vm.refundStatusText('rejected')).toBe('已拒绝')
    expect(vm.money('abc')).toBe('0.00')
    vm.goOrder({ out_trade_no: 'ord_1' })
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'order-detail', params: { orderId: 'ord_1' } })
    await vm.dismissNonActiveOrders()
    expect(lowMocks.api.paymentDismissNonActiveOrders).toHaveBeenCalled()

    lowMocks.walletRefreshBalance.mockResolvedValueOnce(99)
    await vm.loadBalance()
    expect(lowMocks.walletSetBalance).toHaveBeenCalled()
    lowMocks.api.transactions.mockRejectedValueOnce(new Error('tx down'))
    await vm.loadTransactions()
    expect(vm.transactions).toEqual([])
    expect(vm.normalizeTransaction({ amount: '7.5' }).amount).toBe(7.5)

    localStorage.removeItem('modstore_token')
    await vm.startAlipayRecharge()
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/wallet' } })
    localStorage.setItem('modstore_token', 'token')
    vm.payAmount = 0
    vm.validateAmount()
    expect(vm.amountError).toContain('大于 0')
    vm.payAmount = 1_000_000
    vm.validateAmount()
    expect(vm.amountError).toContain('不能超过')
    vm.payAmount = 12
    vm.payNote = '测试充值'
    await vm.startAlipayRecharge()
    expect(vm.payErr).toBe('下单失败')
    await vm.startAlipayRecharge()
    expect(lowMocks.router.push).toHaveBeenCalledWith({ name: 'checkout', params: { orderId: 'recharge_1' } })
    expect(vm.formatDate()).toBe('')

    const anyVm = vm as any
    lowMocks.membershipReferenceYuan.value = 0
    lowMocks.walletBalance.value = -10
    expect(vm.money(-10)).toBe('-10.00')
    anyVm.transactions = Array.from({ length: 8 }, (_, i) => ({
      id: `tx-${i}`,
      type: i % 2 ? 'wallet_refund' : 'purchase',
      amount: i + 1,
      created_at: '2026-06-18T00:00:00Z',
      order_no: i === 0 ? 'ord-ref' : '',
      refund_no: i === 1 ? 'rf-ref' : '',
    }))
    anyVm.txListExpanded = false
    expect(anyVm.visibleTransactions.length).toBeLessThan(anyVm.transactions.length)
    expect(anyVm.hiddenTxCount).toBeGreaterThan(0)
    anyVm.txListExpanded = true
    expect(anyVm.visibleTransactions.length).toBe(anyVm.transactions.length)

    expect(vm.modelOptionLabel({ id: 'pending-model', capability: { l3_status: 'pending', l1_status: 'ok' } })).toContain('L3审核中')
    expect(vm.modelOptionLabel({})).toBe('')
    expect(vm.providerTileMediaTags({ media_counts: { image: 1, video: 1 }, models_detailed: [] }).map((t) => t.kind)).toEqual(['image', 'video'])
    expect(vm.formatCatalogFetchedAt('2026-06-18T10:00:00Z')).toContain('18')
    expect(vm.providerTileState({ provider: 'openai', error: 'invalid api key', fetch_source: 'live_error' })).toBe('danger')
    expect(vm.providerTileState({ provider: 'openai', error: 'rate limit', fetch_source: 'static_fallback_merged' })).toBe('warn')
    expect(vm.providerTileTitle({ provider: 'openai', label: 'OpenAI', error: 'quota exhausted', fetch_source: 'live_error' })).toContain('不可用')
    expect(vm.providerTileTitle({ provider: 'openai', label: 'OpenAI', fetch_source: 'static_fallback_merged' })).toContain('静态兜底')
    anyVm.catalog = { ...catalog, providers: [], preferences: { provider: '', model: '' }, fernet_configured: false, gate_hints: '需要配置 Fernet' }
    expect(anyVm.currentProviderBlock).toBeNull()
    expect(anyVm.catalogProvidersSorted).toEqual([])
    anyVm.syncSelectionFromServerPrefs()
    anyVm.validateSelectionAfterRefresh()

    lowMocks.api.llmCatalog.mockRejectedValueOnce(new Error('catalog down'))
    await vm.refreshCatalog(false)
    expect(vm.llmErr).toContain('catalog down')
    anyVm.catalog = catalog
    vm.selectedProvider = 'openai'
    vm.selectedModel = 'gpt-4o'
    lowMocks.api.llmSavePreferences.mockRejectedValueOnce(new Error('pref down'))
    await vm.persistPreferences()
    expect(vm.llmErr).toContain('pref down')
    vm.byokKey.openai = 'sk-openai'
    lowMocks.api.llmSaveCredentials.mockRejectedValueOnce(new Error('byok down'))
    await vm.saveByok('openai')
    expect(vm.llmErr).toContain('byok down')
    lowMocks.confirmDanger.mockResolvedValueOnce(false)
    await vm.clearByok('deepseek')
    lowMocks.api.llmDeleteCredentials.mockRejectedValueOnce(new Error('delete down'))
    await vm.clearByok('deepseek')
    expect(vm.llmErr).toContain('delete down')
    vm.byokBulkPaste = ''
    await vm.importByokBulk()
    expect(vm.llmNote).toBeTruthy()

    lowMocks.api.paymentMyPlan.mockRejectedValueOnce(new Error('plan down'))
    await vm.loadMyPlan()
    expect(anyVm.myQuotas).toEqual([])
    localStorage.removeItem('modstore_token')
    await vm.loadWalletOverview()
    expect(anyVm.recentOrders.length).toBeGreaterThanOrEqual(0)
    localStorage.setItem('modstore_token', 'token')

    anyVm.dismissOrdersLoading = true
    await vm.dismissNonActiveOrders()
    anyVm.dismissOrdersLoading = false
    anyVm.recentOrders = []
    await vm.dismissNonActiveOrders()
    anyVm.recentOrders = [{ out_trade_no: 'ord_closed', status: 'closed' }]
    lowMocks.api.paymentDismissNonActiveOrders.mockResolvedValueOnce({ ok: false, message: 'dismiss failed' })
    await vm.dismissNonActiveOrders()
    expect(vm.payErr).toContain('dismiss failed')
    lowMocks.api.paymentDismissNonActiveOrders.mockRejectedValueOnce(new Error('dismiss down'))
    await vm.dismissNonActiveOrders()
    expect(vm.payErr).toContain('dismiss down')

    vm.payAmount = 0
    await vm.startAlipayRecharge()
    expect(vm.amountError).toContain('大于 0')
    vm.payAmount = 12
    vm.payNote = ''
    lowMocks.api.paymentCheckout
      .mockResolvedValueOnce({ ok: true, type: 'page' })
      .mockResolvedValueOnce({ ok: true, type: 'mystery' })
      .mockRejectedValueOnce(new Error('pay down'))
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('未返回支付跳转地址')
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('未知的支付类型')
    await vm.startAlipayRecharge()
    expect(vm.payErr).toContain('pay down')

    anyVm.catalog = {
      ...catalog,
      providers: [
        ...catalog.providers,
        {
          provider: 'videoai',
          label: 'Video AI',
          models: ['video-gen'],
          models_detailed: [{ id: 'video-gen', category: 'video', pricing: { video_per_1k: 120 } }],
          media_counts: { image: 0, video: 1 },
          fetched_at: '2026-06-18T11:00:00Z',
        },
      ],
    }
    anyVm.llmStatusList = [
      { provider: 'openai', has_user_override: true, has_platform_key: true },
      { provider: 'deepseek', has_user_override: true, has_platform_key: false },
      { provider: 'videoai', has_user_override: true, has_platform_key: false },
    ]
    vm.llmProviderFilter = 'video'
    expect(vm.catalogProvidersSorted.map((p) => p.provider)).toEqual(['videoai'])
    vm.selectProvider('videoai')
    expect(vm.selectedModel).toBe('video-gen')
    expect(anyVm.selectedModelPricingDetail || '').toBeTruthy()
    expect(vm.providerTileMediaTags({ media_counts: { image: 0, video: 2 } }).map((t) => t.kind)).toEqual(['video'])
    expect(vm.providerTileTitle({ provider: 'openai', label: 'OpenAI', fetch_source: 'static_fallback_merged' })).toContain('静态兜底')
    expect(vm.providerTileTitle({ provider: 'openai', label: 'OpenAI', error: 'rate limit', fetch_source: 'live_error' })).toContain('降级')
    expect(vm.providerTileTitle({ provider: 'openai', label: 'OpenAI', error: 'credit exhausted', fetch_source: 'live_error' })).toContain('不可用')

    lowMocks.api.llmSaveCredentials.mockReset()
    lowMocks.api.llmSaveCredentials
      .mockResolvedValueOnce({ ok: true })
      .mockRejectedValueOnce(new Error('bulk bad'))
    vm.byokBulkPaste = 'OPENAI_API_KEY=sk-ok\nDEEPSEEK_API_KEY=sk-bad\nsk-bare-auto'
    const httpClient = await import('./infrastructure/http/client')
    vi.mocked(httpClient.requestJson).mockResolvedValueOnce({ provider: 'openai' })
    await vm.importByokBulk()
    expect(vm.llmNote).toContain('自动识别命中')
    expect(vm.llmNote).toContain('失败 1')
    expect(vm.byokBulkPaste).toContain('sk-bad')

    lowMocks.api.llmCatalog.mockClear()
    localStorage.setItem('modstore_token', 'token')
    vm.onVisibilityRefresh()
    await flushPromises(2)
    expect(lowMocks.api.llmCatalog).toHaveBeenCalled()
    lowMocks.api.llmCatalog.mockClear()
    localStorage.removeItem('modstore_token')
    vm.onVisibilityRefresh()
    await flushPromises(2)
    expect(lowMocks.api.llmCatalog).not.toHaveBeenCalled()

    anyVm.catalog = { providers: [], cache_ttl_seconds: 1 }
    expect(anyVm.catalogSyncMeta).toBeNull()

    wrapper.unmount()
  })
})
