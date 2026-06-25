import { describe, it, expect, vi, beforeEach } from 'vitest'
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

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
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
  mockListUsers.mockResolvedValue({
    users: [
      { id: 1, username: 'admin', is_admin: true, mod_ids: [] },
      { id: 2, username: 'enterprise', is_enterprise: true, mod_ids: ['mod1'] },
      { id: 3, username: 'normal', mod_ids: [] },
    ],
  })
  mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Mod 1' }, { id: 'mod2', name: 'Mod 2' }] })
  mockListUserMods.mockResolvedValue({ mod_ids: [] })
  mockGetUserProfiles.mockResolvedValue({ data: {} })
  mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: 100.5 }] })
  mockApiFetch.mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ data: { installed: [], available: [], last_sync_at: '' } }),
  })
}

async function mountComponent() {
  const wrapper = mount(AdminEntitlementsView, {
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: true },
    },
  })
  await flushPromises()
  return wrapper
}

async function selectUser(wrapper: ReturnType<typeof mount> extends Promise<infer W> ? W : never) {
  const cards = wrapper.findAll('.admin-user-card')
  if (cards.length > 0) {
    await cards[0].trigger('click')
    await flushPromises()
  }
}

describe('AdminEntitlementsView functions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    setupDefaultMocks()
  })

  // --- walletBalance ---

  it('walletBalance returns formatted balance', async () => {
    mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: 100.5 }] })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.walletBalance({ id: 1 })).toBe('¥100.50')
  })

  it('walletBalance returns — for missing wallet', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.walletBalance({ id: 999 })).toBe('—')
  })

  it('walletBalance returns — for null balance', async () => {
    mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: null }] })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.walletBalance({ id: 1 })).toBe('—')
  })

  it('walletBalance handles string balance', async () => {
    mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: '250.75' }] })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.walletBalance({ id: 1 })).toBe('¥250.75')
  })

  it('walletBalance returns — for NaN balance', async () => {
    mockListWallets.mockResolvedValue({ items: [{ user_id: 1, balance: 'abc' }] })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.walletBalance({ id: 1 })).toBe('—')
  })

  // --- saveProfile ---

  it('saveProfile calls setUserProfile and shows alert', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    // Change profile editing
    vm.profileEditing.tier = 'enterprise'
    vm.profileEditing.industry_id = '制造业'
    mockSetUserProfile.mockResolvedValue({ success: true })
    await vm.saveProfile()
    expect(mockSetUserProfile).toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenCalledWith('已保存')
  })

  it('saveProfile auto-includes current industry in entitled_industries', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    vm.profileEditing.industry_id = '制造业'
    vm.profileEditing.entitled_industries = []
    mockSetUserProfile.mockResolvedValue({ success: true })
    await vm.saveProfile()
    const callArgs = mockSetUserProfile.mock.calls[0][1] as any
    expect(callArgs.entitled_industries).toContain('制造业')
  })

  it('saveProfile shows error on failure', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    mockSetUserProfile.mockRejectedValue(new Error('Server error'))
    await vm.saveProfile()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('保存失败'))
  })

  it('saveProfile does nothing when no user selected', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    vm.selectedUserId = null
    await vm.saveProfile()
    expect(mockSetUserProfile).not.toHaveBeenCalled()
  })

  // --- bindMod ---

  it('bindMod calls bindUserMod and updates userModIds', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    vm.modToBind = 'mod2'
    mockBindUserMod.mockResolvedValue({ success: true })
    await vm.bindMod()
    expect(mockBindUserMod).toHaveBeenCalledWith(expect.any(Number), 'mod2')
    expect(vm.userModIds).toContain('mod2')
    expect(mockAppAlert).toHaveBeenCalledWith('已绑定')
  })

  it('bindMod shows error on failure', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    vm.modToBind = 'mod2'
    mockBindUserMod.mockRejectedValue(new Error('Bind failed'))
    await vm.bindMod()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('绑定失败'))
  })

  it('bindMod does nothing without selectedUserId', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    vm.selectedUserId = null
    vm.modToBind = 'mod2'
    await vm.bindMod()
    expect(mockBindUserMod).not.toHaveBeenCalled()
  })

  it('bindMod does nothing without modToBind', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    vm.modToBind = ''
    await vm.bindMod()
    expect(mockBindUserMod).not.toHaveBeenCalled()
  })

  // --- toggleEnterprise ---

  it('toggleEnterprise calls setUserEnterprise with checked value', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    mockSetUserEnterprise.mockResolvedValue({ success: true })
    const fakeEvent = { target: { checked: true } } as unknown as Event
    await vm.toggleEnterprise(fakeEvent)
    expect(mockSetUserEnterprise).toHaveBeenCalledWith(expect.any(Number), true)
  })

  it('toggleEnterprise shows error on failure', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    mockSetUserEnterprise.mockRejectedValue(new Error('Update failed'))
    const fakeEvent = { target: { checked: false } } as unknown as Event
    await vm.toggleEnterprise(fakeEvent)
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('更新失败'))
  })

  it('toggleEnterprise does nothing when no user selected', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    vm.selectedUserId = null
    const fakeEvent = { target: { checked: true } } as unknown as Event
    await vm.toggleEnterprise(fakeEvent)
    expect(mockSetUserEnterprise).not.toHaveBeenCalled()
  })

  // --- startImpersonate ---

  it('startImpersonate calls API and redirects', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    mockStartImpersonate.mockResolvedValue({ bridge_token: 'tok' })
    await vm.startImpersonate()
    expect(mockStartImpersonate).toHaveBeenCalled()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('已进入代管'))
  })

  it('startImpersonate shows error on failure', async () => {
    const wrapper = await mountComponent()
    await selectUser(wrapper)
    const vm = wrapper.vm as any
    mockStartImpersonate.mockRejectedValue(new Error('Impersonate failed'))
    await vm.startImpersonate()
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('代管失败'))
  })

  it('startImpersonate does nothing when no user selected', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    vm.selectedUserId = null
    await vm.startImpersonate()
    expect(mockStartImpersonate).not.toHaveBeenCalled()
  })

  // --- normalizeLocalCatalogRows ---

  it('normalizeLocalCatalogRows filters to only installed mods', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    const raw = {
      data: {
        installed: [{ id: 'mod1', name: 'Mod 1', version: '1.0', is_installed: true }],
        available: [{ id: 'mod2', name: 'Mod 2', is_installed: false }],
      },
    }
    const result = vm.normalizeLocalCatalogRows(raw)
    expect(result.length).toBe(1)
    expect(result[0].id).toBe('mod1')
  })

  it('normalizeLocalCatalogRows handles raw without data wrapper', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    const raw = {
      installed: [{ id: 'mod1', is_installed: true }],
      available: [],
    }
    const result = vm.normalizeLocalCatalogRows(raw)
    expect(result.length).toBe(1)
  })

  it('normalizeLocalCatalogRows handles empty data', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    const result = vm.normalizeLocalCatalogRows({})
    expect(result).toEqual([])
  })

  it('normalizeLocalCatalogRows handles non-object rows', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    const raw = {
      data: {
        installed: [null, 'invalid', { id: 'mod1', is_installed: true }],
        available: [],
      },
    }
    const result = vm.normalizeLocalCatalogRows(raw)
    expect(result.length).toBe(1)
  })

  // --- refreshLocalStatus error handling ---

  it('refreshLocalStatus shows error when catalog fetch fails', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) return Promise.resolve({ ok: false, status: 500 })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { last_sync_at: '' } }) })
    })
    await vm.refreshLocalStatus()
    expect(vm.localStatusError).toContain('本地安装状态读取失败')
  })

  it('refreshLocalStatus shows error when sync status fetch fails', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { installed: [], available: [] } }) })
      if (url.includes('sync')) return Promise.resolve({ ok: false, status: 404 })
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) })
    })
    await vm.refreshLocalStatus()
    expect(vm.localStatusError).toContain('同步状态读取失败')
  })

  // --- selectUser error handling ---

  it('selectUser shows alert when listUserMods fails', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    mockListUserMods.mockRejectedValue(new Error('Load mods failed'))
    await vm.selectUser({ id: 1, username: 'test', mod_ids: ['fallback'] })
    expect(vm.userModIds).toEqual(['fallback'])
    expect(mockAppAlert).toHaveBeenCalledWith(expect.stringContaining('加载用户 Mod 失败'))
  })

  // --- modLabel / isModInstalled / modInstallText ---

  it('modLabel returns mod name for known mod', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.modLabel('mod1')).toBe('Mod 1')
  })

  it('modLabel returns modId for unknown mod', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.modLabel('unknown')).toBe('unknown')
  })

  it('modInstallText returns 未安装 for not installed mod', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.modInstallText('mod1')).toBe('未安装')
  })

  it('modInstallText returns 已安装 v{version} for installed mod with version', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { installed: [{ id: 'mod1', version: '2.0', is_installed: true }], available: [] } }),
        })
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { last_sync_at: '' } }) })
    })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.modInstallText('mod1')).toBe('已安装 v2.0')
  })

  // --- syncLastText ---

  it('syncLastText returns empty string when no sync date', async () => {
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
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
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ data: { installed: [], available: [] } }) })
    })
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    expect(vm.syncLastText).toBeTruthy()
  })

  // --- loadWallets error handling ---

  it('loadWallets does not throw on failure', async () => {
    mockListWallets.mockRejectedValue(new Error('Wallet fetch failed'))
    const wrapper = await mountComponent()
    const vm = wrapper.vm as any
    // Should not throw, walletMap should be empty
    expect(vm.walletMap.size).toBe(0)
  })
})
