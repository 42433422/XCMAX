import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

// --- Mocks ---

const mockListUsers = vi.fn()
const mockListAssignableMods = vi.fn()
const mockListUserMods = vi.fn()
const mockBindUserMod = vi.fn()
const mockUnbindUserMod = vi.fn()
const mockSetUserEnterprise = vi.fn()
const mockStartImpersonate = vi.fn()
const mockGetUserProfiles = vi.fn()
const mockSetUserProfile = vi.fn()
const mockListWallets = vi.fn()
const mockForcePushUserEntitlements = vi.fn()
const mockCreateMarketUser = vi.fn()
const mockCreditWallet = vi.fn()

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    createMarketUser: (...args: unknown[]) => mockCreateMarketUser(...args),
    creditWallet: (...args: unknown[]) => mockCreditWallet(...args),
    listUsers: () => mockListUsers(),
    listAssignableMods: () => mockListAssignableMods(),
    listUserMods: (id: number) => mockListUserMods(id),
    bindUserMod: (uid: number, mid: string) => mockBindUserMod(uid, mid),
    unbindUserMod: (uid: number, mid: string) => mockUnbindUserMod(uid, mid),
    setUserEnterprise: (uid: number, val: boolean) => mockSetUserEnterprise(uid, val),
    startImpersonate: (uid: number, name: string) => mockStartImpersonate(uid, name),
    getUserProfiles: () => mockGetUserProfiles(),
    setUserProfile: (uid: number, payload: unknown) => mockSetUserProfile(uid, payload),
    listWallets: () => mockListWallets(),
    forcePushUserEntitlements: (uid: number, payload: unknown) => mockForcePushUserEntitlements(uid, payload),
  },
}))

const mockAppAlert = vi.fn().mockResolvedValue(undefined)
vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => mockAppAlert(...args),
}))

const mockApiFetch = vi.fn()
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (url: string) => mockApiFetch(url),
}))

vi.mock('@/stores/accountProfile', () => ({
  useAccountProfileStore: () => ({
    refreshFromServer: vi.fn().mockResolvedValue(undefined),
  }),
}))

import AdminEntitlementsView from './AdminEntitlementsView.vue'

function setupDefaultMocks() {
  mockCreateMarketUser.mockResolvedValue({ success: true })
  mockCreditWallet.mockResolvedValue({ success: true })
  mockListUsers.mockResolvedValue({
    users: [
      { id: 1, username: 'admin', is_admin: true, mod_ids: [] },
      { id: 2, username: 'enterprise', is_enterprise: true, mod_ids: ['mod1'] },
      { id: 3, username: 'normal', mod_ids: [] },
    ],
  })
  mockListAssignableMods.mockResolvedValue({
    mods: [
      { id: 'mod1', name: 'Mod 1' },
      { id: 'mod2', name: 'Mod 2' },
    ],
  })
  mockListUserMods.mockResolvedValue({ mod_ids: [] })
  mockGetUserProfiles.mockResolvedValue({ data: {} })
  mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: 100.5 }] })
  mockForcePushUserEntitlements.mockResolvedValue({ data: { push: { sent: 1, failed: 0 } } })
  mockApiFetch.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: { installed: [], available: [], last_sync_at: '' } }),
  })
}

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => wrappers.splice(0).forEach((wrapper) => wrapper.unmount()))

async function mountComponent() {
  const wrapper = mount(AdminEntitlementsView, {
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: true },
    },
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

async function selectUser(wrapper: ReturnType<typeof mount>) {
  const cards = wrapper.findAll('.admin-user-card')
  if (cards.length > 0) {
    await cards[0].trigger('click')
    await flushPromises()
  }
}

async function mountVm(selected = false) {
  const wrapper = await mountComponent()
  if (selected) await selectUser(wrapper)
  return wrapper.vm as any
}

describe('AdminEntitlementsView functions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    setupDefaultMocks()
  })

  it.each(['enter', 'space'])('selects an account using the %s key after filtering its industry', async (key) => {
    mockListUsers.mockResolvedValue({ users: [{ id: 1, username: 'admin', industry_id: '考勤' }] })
    const wrapper = await mountComponent()
    await wrapper.get('[aria-label="按行业筛选"]').setValue('考勤')
    await wrapper.get('.admin-user-card').trigger(`keydown.${key}`)
    await flushPromises()
    expect(mockListUserMods).toHaveBeenCalledWith(1)
    expect(wrapper.get('.admin-user-detail h3').text()).toBe('admin')
  })

  // --- walletBalance ---

  it.each([
    [100.5, '¥100.50'], [null, '¥0.00'], ['250.75', '¥250.75'], ['abc', '—'],
  ])('formats wallet balance %s as %s', async (balance, expected) => {
    mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance }] })
    expect((await mountVm()).walletBalance({ id: 1 })).toBe(expected)
  })

  it('walletBalance returns zero for an account without a materialized wallet row', async () => {
    expect((await mountVm()).walletBalance({ id: 999 })).toBe('¥0.00')
  })

  // --- saveProfile ---

  it('saveProfile calls setUserProfile and shows alert', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    await wrapper.get('.admin-user-profile select').setValue('enterprise')
    const selects = wrapper.findAll('.admin-user-profile select')
    await selects[1].setValue('考勤')
    await selects[2].setValue('pro')
    await selects[3].setValue('1–5 万')
    await wrapper.get('.admin-user-profile__chip input').setValue(true)
    mockSetUserProfile.mockResolvedValue({ success: true })
    await wrapper.get('.admin-user-profile button').trigger('click')
    await flushPromises()
    expect(mockSetUserProfile).toHaveBeenCalledWith(1, expect.objectContaining({ tier: 'enterprise', industry_id: '考勤', account_tier: 'pro', budget_range: '1–5 万' }))
    expect(mockAppAlert).toHaveBeenCalledWith('已保存')
  })

  it('saveProfile auto-includes current industry in entitled_industries', async () => {
    const vm = await mountVm(true)
    vm.profileEditing.industry_id = '制造业'
    vm.profileEditing.entitled_industries = []
    mockSetUserProfile.mockResolvedValue({ success: true })
    await vm.saveProfile()
    const callArgs = mockSetUserProfile.mock.calls[0][1] as any
    expect(callArgs.entitled_industries).toContain('制造业')
  })

  it('saveProfile shows error on failure', async () => {
    const vm = await mountVm(true)
    mockSetUserProfile.mockRejectedValue(new Error('Server error'))
    await vm.saveProfile()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
  })

  it('saveProfile does nothing when no user selected', async () => {
    const vm = await mountVm()
    vm.selectedUserId = null
    await vm.saveProfile()
    expect(mockSetUserProfile).not.toHaveBeenCalled()
  })

  // --- bindMod ---

  it('bindMod calls bindUserMod and updates userModIds', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    await wrapper.get('.admin-mod-select').setValue('mod2')
    mockBindUserMod.mockResolvedValue({ success: true })
    await wrapper.get('.admin-mod-assign button').trigger('click')
    await flushPromises()
    expect(mockBindUserMod).toHaveBeenCalledWith(expect.any(Number), 'mod2')
    expect(vm.userModIds).toContain('mod2')
    expect(mockAppAlert).toHaveBeenCalledWith('已绑定')
  })

  it('bindMod shows error on failure', async () => {
    const vm = await mountVm(true)
    vm.modToBind = 'mod2'
    mockBindUserMod.mockRejectedValue(new Error('Bind failed'))
    await vm.bindMod()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('绑定失败'))
  })

  it('bindMod does nothing without selectedUserId', async () => {
    const vm = await mountVm()
    vm.selectedUserId = null
    vm.modToBind = 'mod2'
    await vm.bindMod()
    expect(mockBindUserMod).not.toHaveBeenCalled()
  })

  it('bindMod does nothing without modToBind', async () => {
    const vm = await mountVm(true)
    vm.modToBind = ''
    await vm.bindMod()
    expect(mockBindUserMod).not.toHaveBeenCalled()
  })

  // --- toggleEnterprise ---

  it('toggleEnterprise calls setUserEnterprise with checked value', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    mockSetUserEnterprise.mockResolvedValue({ success: true })
    await wrapper.get('.admin-user-detail__actions input').setValue(true)
    await flushPromises()
    expect(mockSetUserEnterprise).toHaveBeenCalledWith(expect.any(Number), true)
  })

  it('toggleEnterprise shows error on failure', async () => {
    const vm = await mountVm(true)
    mockSetUserEnterprise.mockRejectedValue(new Error('Update failed'))
    const fakeEvent = { target: { checked: false } } as unknown as Event
    await vm.toggleEnterprise(fakeEvent)
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('更新失败'))
  })

  it('toggleEnterprise does nothing when no user selected', async () => {
    const vm = await mountVm()
    vm.selectedUserId = null
    const fakeEvent = { target: { checked: true } } as unknown as Event
    await vm.toggleEnterprise(fakeEvent)
    expect(mockSetUserEnterprise).not.toHaveBeenCalled()
  })

  // --- startImpersonate ---

  it('startImpersonate calls API and redirects', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    mockStartImpersonate.mockResolvedValue({ bridge_token: 'tok' })
    await wrapper.get('.admin-user-detail__actions button').trigger('click')
    await flushPromises()
    expect(mockStartImpersonate).toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('已进入代管'))
  })

  it('startImpersonate shows error on failure', async () => {
    const vm = await mountVm(true)
    mockStartImpersonate.mockRejectedValue(new Error('Impersonate failed'))
    await vm.startImpersonate()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('代管失败'))
  })

  it('startImpersonate does nothing when no user selected', async () => {
    const vm = await mountVm()
    vm.selectedUserId = null
    await vm.startImpersonate()
    expect(mockStartImpersonate).not.toHaveBeenCalled()
  })

  // --- normalizeLocalCatalogRows ---

  it.each([
    [{ data: { installed: [{ id: 'mod1', name: 'Mod 1', version: '1.0', is_installed: true }], available: [{ id: 'mod2', is_installed: false }] } }, ['mod1']],
    [{ installed: [{ id: 'mod1', is_installed: true }], available: [] }, ['mod1']],
    [{}, []],
    [{ data: { installed: [null, 'invalid', { id: 'mod1', is_installed: true }], available: [] } }, ['mod1']],
  ])('normalizes catalog rows %j', async (raw, ids) => {
    expect((await mountVm()).normalizeLocalCatalogRows(raw).map((row: any) => row.id)).toEqual(ids)
  })

  // --- refreshLocalStatus error handling ---

  it('refreshLocalStatus shows error when catalog fetch fails', async () => {
    const vm = await mountVm()
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) return Promise.resolve({ ok: false, status: 500 })
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { last_sync_at: '' } }),
      })
    })
    await vm.refreshLocalStatus()
    expect(vm.localStatusError).toContain('本地安装状态读取失败')
  })

  it('refreshLocalStatus shows error when sync status fetch fails', async () => {
    const vm = await mountVm()
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog'))
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { installed: [], available: [] } }),
        })
      if (url.includes('sync')) return Promise.resolve({ ok: false, status: 404 })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    await vm.refreshLocalStatus()
    expect(vm.localStatusError).toContain('同步状态读取失败')
  })

  // --- selectUser error handling ---

  it('selectUser shows alert when listUserMods fails', async () => {
    const vm = await mountVm()
    mockListUserMods.mockRejectedValue(new Error('Load mods failed'))
    await vm.selectUser({ id: 1, username: 'test', mod_ids: ['fallback'] })
    expect(vm.userModIds).toEqual(['fallback'])
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('加载用户 Mod 失败'))
  })

  // --- modLabel / isModInstalled / modInstallText ---

  it('modLabel returns mod name for known mod', async () => {
    const vm = await mountVm()
    expect(vm.modLabel('mod1')).toBe('Mod 1')
  })

  it('modLabel returns modId for unknown mod', async () => {
    const vm = await mountVm()
    expect(vm.modLabel('unknown')).toBe('unknown')
  })

  it('modInstallText returns 未安装 for not installed mod', async () => {
    const vm = await mountVm()
    expect(vm.modInstallText('mod1')).toBe('未安装')
  })

  it('modInstallText returns 已安装 v{version} for installed mod with version', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              data: {
                installed: [{ id: 'mod1', version: '2.0', is_installed: true }],
                available: [],
              },
            }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { last_sync_at: '' } }),
      })
    })
    const vm = await mountVm()
    expect(vm.modInstallText('mod1')).toBe('已安装 v2.0')
  })

  // --- syncLastText ---

  it('syncLastText returns empty string when no sync date', async () => {
    const vm = await mountVm()
    expect(vm.syncLastText).toBe('')
  })

  it('syncLastText returns formatted date for valid date', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('sync')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { last_sync_at: '2026-06-25T10:00:00Z' } }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { installed: [], available: [] } }),
      })
    })
    const vm = await mountVm()
    expect(vm.syncLastText).toBeTruthy()
  })

  // --- loadWallets error handling ---

  it('loadWallets does not throw on failure', async () => {
    mockListWallets.mockRejectedValue(new Error('Wallet fetch failed'))
    const vm = await mountVm()
    // Should not throw, walletMap should be empty
    expect(vm.walletMap.size).toBe(0)
  })

  it('forcePushSelectedEntitlements sends selected account snapshot', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    vm.profileEditing.tier = 'enterprise'
    vm.profileEditing.industry_id = '考勤'
    vm.profileEditing.entitled_industries = []
    vm.userModIds = ['mod1']
    await wrapper.get('.admin-chain-actions button').trigger('click')
    await flushPromises()
    expect(mockForcePushUserEntitlements).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        user: expect.objectContaining({ username: 'admin', is_enterprise: true }),
        profile: expect.objectContaining({
          tier: 'enterprise',
          industry_id: '考勤',
          entitled_industries: expect.arrayContaining(['考勤']),
        }),
        mod_ids: ['mod1'],
        wallet: expect.objectContaining({ balance: 100.5 }),
      }),
    )
    expect(mockAppAlert).toHaveBeenCalledWith('已强制推送企业端：发送 1 条，失败 0 条')
  })

  it('forcePushSelectedEntitlements shows error on failure', async () => {
    const vm = await mountVm(true)
    mockForcePushUserEntitlements.mockRejectedValue(new Error('push failed'))
    await vm.forcePushSelectedEntitlements()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('强制推送失败'))
  })
  it.each([
    ['', 'secret', '请填写用户名'], ['customer', 'short', '密码至少 6 位'],
  ])('validates new account %s before creating it', async (username, password, message) => {
    const vm = await mountVm()
    Object.assign(vm.newAccount, { username, password })
    await vm.createAccount()
    expect(mockCreateMarketUser).not.toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenLastCalledWith(message)
    expect(vm.creatingAccount).toBe(false)
  })

  it.each([
    [' Customer ', '', 'customer@xcagi.local', false, ''],
    ['Customer@Example.com', '', 'customer@example.com', true, '考勤'],
    ['customer', ' explicit@example.com ', 'explicit@example.com', true, '考勤'],
  ])('creates and selects %s with its requested profile', async (username, email, expectedEmail, enterprise, industry) => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    const user = { id: 72, username: username.trim(), is_enterprise: enterprise, mod_ids: [] }
    mockListUsers.mockResolvedValue({ users: [user] })
    mockSetUserEnterprise.mockResolvedValue({ success: true })
    mockSetUserProfile.mockResolvedValue({ success: true })
    await wrapper.get('.admin-entitlements-head button').trigger('click')
    const inputs = wrapper.findAll('.admin-create-account .admin-user-input')
    await inputs[0].setValue(username)
    await inputs[1].setValue('safe-secret')
    await inputs[2].setValue(email)
    const selects = wrapper.findAll('.admin-create-account select')
    await selects[0].setValue('enterprise')
    await selects[1].setValue(industry)
    await wrapper.get('.admin-create-account input[type="checkbox"]').setValue(true)
    await wrapper.get('.admin-password-field button:last-child').trigger('click')
    expect(inputs[1].attributes('type')).toBe('text')
    await wrapper.get('.admin-create-account .btn-primary').trigger('click')
    await flushPromises()
    expect(mockCreateMarketUser).toHaveBeenCalledWith({ username: username.trim(), email: expectedEmail, password: 'safe-secret' })
    expect(mockSetUserProfile).toHaveBeenCalledWith(72, expect.objectContaining({ industry_id: industry || '通用', entitled_industries: [industry || '通用'] }))
    expect(mockSetUserEnterprise).toHaveBeenCalledTimes(enterprise ? 0 : 1)
    expect(vm.selectedUserId).toBe(72)
    expect(vm.newAccount.password).toBe('')
    expect(vm.createAccountOpen || vm.showNewAccountPassword || vm.creatingAccount).toBe(false)
    expect(mockAppAlert).toHaveBeenLastCalledWith('账号已创建')
  })

  it('finishes creating an account even when the refreshed list omits it', async () => {
    const vm = await mountVm()
    Object.assign(vm.newAccount, { username: 'unlisted', password: 'secret' })
    await vm.createAccount()
    expect(mockSetUserProfile).not.toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenLastCalledWith('账号已创建')
  })

  it.each([new Error('offline'), 'offline'])('retains account input after a failed creation: %s', async (error) => {
    const vm = await mountVm()
    Object.assign(vm.newAccount, { username: 'customer', password: 'secret' })
    mockCreateMarketUser.mockRejectedValueOnce(error)
    await vm.createAccount()
    expect(vm.newAccount.username).toBe('customer')
    expect(vm.creatingAccount).toBe(false)
    expect(mockAppAlert).toHaveBeenLastCalledWith('创建失败：offline')
  })

  it.each([0, -10, NaN, Infinity])('rejects invalid wallet credit %s', async (amount) => {
    const vm = await mountVm(true)
    vm.setCreditAmount(amount)
    await vm.creditSelectedWallet()
    expect(mockCreditWallet).not.toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenLastCalledWith('加款金额必须大于 0')
  })

  it.each(['', ' customer credit '])('credits and refreshes the wallet with description %j', async (description) => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    await wrapper.get('.admin-wallet-panel__quick button').trigger('click')
    expect(vm.creditForm.amount).toBe(50)
    await wrapper.get('.admin-wallet-panel__amount input').setValue('50')
    await wrapper.get('.admin-wallet-panel__desc input').setValue(description)
    await wrapper.get('.admin-wallet-panel .btn-primary').trigger('click')
    await flushPromises()
    expect(mockCreditWallet).toHaveBeenCalledWith(1, { amount: 50, description: description.trim() || '后台加款' })
    expect(mockListWallets).toHaveBeenCalledTimes(2)
    expect(mockAppAlert).toHaveBeenLastCalledWith('加钱成功')
    expect(vm.creditingWallet).toBe(false)
  })

  it.each([new Error('offline'), 'offline'])('clears the wallet busy flag after failure: %s', async (error) => {
    const vm = await mountVm(true)
    vm.setCreditAmount(50)
    mockCreditWallet.mockRejectedValueOnce(error)
    await vm.creditSelectedWallet()
    expect(mockAppAlert).toHaveBeenLastCalledWith('加钱失败：offline')
    expect(vm.creditingWallet).toBe(false)
  })

  it('does not mutate a wallet, entitlement, or binding without a selected account', async () => {
    const vm = await mountVm()
    await vm.creditSelectedWallet()
    await vm.forcePushSelectedEntitlements()
    await vm.unbindMod('mod1')
    expect(mockCreditWallet).not.toHaveBeenCalled()
    expect(mockForcePushUserEntitlements).not.toHaveBeenCalled()
    expect(mockUnbindUserMod).not.toHaveBeenCalled()
  })

  it.each([new Error('offline'), 'offline'])('preserves bindings after an unbind error: %s', async (error) => {
    const vm = await mountVm(true)
    vm.userModIds = ['mod1']
    mockUnbindUserMod.mockRejectedValueOnce(error)
    await vm.unbindMod('mod1')
    expect(vm.userModIds).toEqual(['mod1'])
    expect(mockAppAlert).toHaveBeenLastCalledWith('解绑失败：offline')
  })

})
