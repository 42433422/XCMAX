import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import AdminEntitlementsView from './AdminEntitlementsView.vue'

// --- Mocks ---

const mockListUsers = vi.fn().mockResolvedValue({ users: [] })
const mockListAssignableMods = vi.fn().mockResolvedValue({ mods: [] })
const mockListUserMods = vi.fn().mockResolvedValue({ mod_ids: [] })
const mockBindUserMod = vi.fn().mockResolvedValue({ success: true })
const mockUnbindUserMod = vi.fn().mockResolvedValue({ success: true })
const mockSetUserEnterprise = vi.fn().mockResolvedValue({ success: true })
const mockStartImpersonate = vi.fn().mockResolvedValue({ bridge_token: 'test-token', enterprise_launch_path: '/chat' })

vi.mock('@/api/xcmaxAdmin', () => ({
  xcmaxAdminApi: {
    listUsers: () => mockListUsers(),
    listAssignableMods: () => mockListAssignableMods(),
    listUserMods: (id: number) => mockListUserMods(id),
    bindUserMod: (uid: number, mid: string) => mockBindUserMod(uid, mid),
    unbindUserMod: (uid: number, mid: string) => mockUnbindUserMod(uid, mid),
    setUserEnterprise: (uid: number, val: boolean) => mockSetUserEnterprise(uid, val),
    startImpersonate: (uid: number, name: string) => mockStartImpersonate(uid, name),
  },
}))

vi.mock('@/utils/adminConsoleUrl', () => ({
  buildEnterpriseImpersonateLaunchUrl: (token: string, path: string) =>
    `http://enterprise.test/impersonate?token=${token}&path=${path}`,
}))

const mockAppAlert = vi.fn().mockResolvedValue(undefined)
vi.mock('@/utils/appDialog', () => ({
  appAlert: (...args: unknown[]) => mockAppAlert(...args),
}))

const mockApiFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: () => Promise.resolve({ data: { installed: [], available: [] } }),
})
vi.mock('@/utils/apiBase', () => ({
  apiFetch: (url: string) => mockApiFetch(url),
}))

// --- Helpers ---

function mountComponent() {
  return mount(AdminEntitlementsView, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: true,
      },
    },
  })
}

describe('AdminEntitlementsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockListUsers.mockResolvedValue({ users: [] })
    mockListAssignableMods.mockResolvedValue({ mods: [] })
    mockApiFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ data: { installed: [], available: [] } }),
    })
  })

  it('renders page title', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('h2').text()).toContain('用户 Mod 管理')
  })

  it('shows empty user list when no users', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-user-list__empty').text()).toContain('暂无用户')
  })

  it('renders user list when users are loaded', async () => {
    mockListUsers.mockResolvedValue({
      users: [
        { id: 1, username: 'admin', email: 'admin@test.com', is_admin: true, mod_ids: [] },
        { id: 2, username: 'enterprise', email: 'ent@test.com', is_enterprise: true, mod_ids: ['mod1'] },
        { id: 3, username: 'normal', email: 'norm@test.com', mod_ids: [] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    const rows = wrapper.findAll('.admin-user-row')
    expect(rows.length).toBe(3)
  })

  it('shows admin/enterprise/normal labels for users', async () => {
    mockListUsers.mockResolvedValue({
      users: [
        { id: 1, username: 'admin', is_admin: true, mod_ids: [] },
        { id: 2, username: 'ent', is_enterprise: true, mod_ids: [] },
        { id: 3, username: 'norm', mod_ids: [] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    const rows = wrapper.findAll('.admin-user-row')
    expect(rows[0].text()).toContain('管理员')
    expect(rows[1].text()).toContain('企业')
    expect(rows[2].text()).toContain('普通')
  })

  it('shows mod count for each user', async () => {
    mockListUsers.mockResolvedValue({
      users: [
        { id: 1, username: 'user1', mod_ids: ['mod1', 'mod2'] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-user-row').text()).toContain('2 Mod')
  })

  it('selects a user when clicking user row', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', email: 'test@test.com', mod_ids: [] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: [] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-user-detail').exists()).toBe(true)
    expect(wrapper.find('h3').text()).toContain('testuser')
  })

  it('shows "请选择左侧用户" when no user is selected', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-user-detail--empty').text()).toContain('请选择左侧用户')
  })

  it('shows load error when API fails', async () => {
    mockListUsers.mockRejectedValue(new Error('Network error'))
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-entitlements-alert').exists()).toBe(true)
  })

  it('filters users by search input', async () => {
    mockListUsers.mockResolvedValue({
      users: [
        { id: 1, username: 'alice', email: 'alice@test.com', mod_ids: [] },
        { id: 2, username: 'bob', email: 'bob@test.com', mod_ids: [] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    const searchInput = wrapper.find('.admin-user-search')
    await searchInput.setValue('alice')
    await flushPromises()
    const rows = wrapper.findAll('.admin-user-row')
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain('alice')
  })

  it('filters users by email', async () => {
    mockListUsers.mockResolvedValue({
      users: [
        { id: 1, username: 'alice', email: 'alice@test.com', mod_ids: [] },
        { id: 2, username: 'bob', email: 'bob@test.com', mod_ids: [] },
      ],
    })
    const wrapper = mountComponent()
    await flushPromises()
    const searchInput = wrapper.find('.admin-user-search')
    await searchInput.setValue('bob@test')
    await flushPromises()
    const rows = wrapper.findAll('.admin-user-row')
    expect(rows.length).toBe(1)
  })

  it('shows enterprise checkbox when user is selected', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', is_enterprise: false, mod_ids: [] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: [] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    const checkbox = wrapper.find('.admin-flag input[type="checkbox"]')
    expect(checkbox.exists()).toBe(true)
  })

  it('shows "进入代管" button when user is selected', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: [] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: [] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-user-detail__actions button').text()).toContain('进入代管')
  })

  it('shows "尚未绑定客户 Mod" when user has no mods', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: [] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: [] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-mod-panel p.muted').text()).toContain('尚未绑定客户 Mod')
  })

  it('shows mod chips when user has mods', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: ['mod1'] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: ['mod1'] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Test Mod' }] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-mod-chip').exists()).toBe(true)
    expect(wrapper.find('.admin-mod-chip').text()).toContain('Test Mod')
  })

  it('shows mod install status as "未安装" when not installed locally', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: ['mod1'] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: ['mod1'] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Test Mod' }] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-mod-install').text()).toContain('未安装')
  })

  it('shows "已安装" when mod is installed locally', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: ['mod1'] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: ['mod1'] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Test Mod' }] })
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ data: { installed: [{ id: 'mod1', version: '1.0', is_installed: true }], available: [] } }),
        })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { last_sync_at: '' } }),
      })
    })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-mod-install.is-installed').text()).toContain('已安装')
  })

  it('shows entitlement chain employees for installed workflow employee mods', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', is_enterprise: true, mod_ids: ['mod1'] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: ['mod1'] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Test Mod' }] })
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            data: {
              installed: [
                {
                  id: 'mod1',
                  name: 'Test Mod',
                  version: '1.0',
                  is_installed: true,
                  workflow_employees: [{ id: 'employee-a', label: '员工 A' }],
                },
              ],
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
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-entitlement-chain').text()).toContain('账号 → Mod → AI 员工 → 设备执行')
    expect(wrapper.find('.admin-entitlement-chain').text()).toContain('员工 A')
    expect(wrapper.find('.admin-entitlement-chain').text()).toContain('1 个员工')
  })

  it('shows bind mod section with select dropdown', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: [] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: [] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod2', name: 'Another Mod' }] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    expect(wrapper.find('.admin-mod-select').exists()).toBe(true)
    expect(wrapper.find('.admin-mod-assign button').text()).toContain('绑定')
  })

  it('shows local sync status section', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-sync-strip').exists()).toBe(true)
    expect(wrapper.find('.admin-sync-strip').text()).toContain('本地宿主状态')
  })

  it('shows refresh status button', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-sync-strip button').text()).toContain('刷新状态')
  })

  it('shows local status error when catalog fetch fails', async () => {
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return Promise.resolve({ ok: false, status: 500 })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { last_sync_at: '' } }),
      })
    })
    const wrapper = mountComponent()
    await flushPromises()
    expect(wrapper.find('.admin-entitlements-alert--soft').exists()).toBe(true)
  })

  it('unbinds a mod when clicking remove button', async () => {
    mockListUsers.mockResolvedValue({
      users: [{ id: 1, username: 'testuser', mod_ids: ['mod1'] }],
    })
    mockListUserMods.mockResolvedValue({ mod_ids: ['mod1'] })
    mockListAssignableMods.mockResolvedValue({ mods: [{ id: 'mod1', name: 'Test Mod' }] })
    const wrapper = mountComponent()
    await flushPromises()
    await wrapper.find('.admin-user-row__btn').trigger('click')
    await flushPromises()
    const removeBtn = wrapper.find('.admin-mod-chip__remove')
    expect(removeBtn.exists()).toBe(true)
    await removeBtn.trigger('click')
    await flushPromises()
    expect(mockUnbindUserMod).toHaveBeenCalledWith(1, 'mod1')
  })

  it('refresh local status button triggers API call', async () => {
    const wrapper = mountComponent()
    await flushPromises()
    mockApiFetch.mockClear()
    await wrapper.find('.admin-sync-strip button').trigger('click')
    await flushPromises()
    expect(mockApiFetch).toHaveBeenCalled()
  })

  it('shows "刷新中…" while refreshing local status', async () => {
    let resolveCatalog: (value: unknown) => void
    mockApiFetch.mockImplementation((url: string) => {
      if (url.includes('catalog')) {
        return new Promise(resolve => { resolveCatalog = resolve })
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ data: { last_sync_at: '' } }),
      })
    })
    const wrapper = mountComponent()
    await flushPromises()
    // Click refresh
    const refreshPromise = wrapper.find('.admin-sync-strip button').trigger('click')
    await flushPromises()
    // Should show loading state
    expect(wrapper.find('.admin-sync-strip button').text()).toContain('刷新中')
    // Resolve the pending request
    resolveCatalog!({ ok: true, json: () => Promise.resolve({ data: { installed: [], available: [] } }) })
    await flushPromises()
  })
})
