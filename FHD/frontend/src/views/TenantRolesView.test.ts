import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TenantRolesView from './TenantRolesView.vue'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { rbacApi, type RbacRole } from '@/api/rbac'

vi.mock('@/api/rbac', () => ({ rbacApi: {
  listRoles: vi.fn(), listPermissions: vi.fn(), listUsers: vi.fn(), createRole: vi.fn(),
  updateRole: vi.fn(), assignRole: vi.fn(), inviteMember: vi.fn(),
} }))
const permission = { id: 1, code: 'sales.read', name: '查看销售', description: '', module: 'sales' }
const system: RbacRole = { id: 1, key: 'admin', name: '管理员', description: '系统权限', is_system: true, permissions: [permission] }
const custom: RbacRole = { id: 2, key: 'sales', name: '销售员', description: '销售业务', is_system: false, permissions: [] }
let wrapper: VueWrapper | undefined
beforeEach(() => {
  vi.resetAllMocks()
  setActivePinia(createPinia())
  vi.spyOn(useAccountProfileStore(), 'refreshFromServer').mockResolvedValue(undefined)
  vi.mocked(rbacApi.listRoles).mockResolvedValue([system, custom])
  vi.mocked(rbacApi.listPermissions).mockResolvedValue([permission])
  vi.mocked(rbacApi.listUsers).mockResolvedValue([
    { id: 2, username: 'SUNBIRD', display_name: '验收用户', role: 'sales', is_active: true },
    { id: 3, username: 'inactive', display_name: '', role: 'external', is_active: false },
  ])
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.restoreAllMocks(); vi.unstubAllGlobals() })
async function open() { wrapper = mount(TenantRolesView); await flushPromises(); return wrapper }
async function click(text: string) {
  const button = wrapper!.findAll('button').find((item) => item.text() === text)
  expect(button, `visible action ${text}`).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

describe('Tenant role management through its visible controls', () => {
  it('locks system-role edits, excludes administrator assignment, and hides invitations from members', async () => {
    const view = await open()
    expect(view.get('input[type=checkbox]').attributes('disabled')).toBeDefined()
    expect(view.get('button[type=submit]').attributes('disabled')).toBeDefined()
    expect(view.findAll('select')[1].text()).not.toContain('管理员')
    expect(view.text()).not.toContain('邀请企业成员')
    expect(view.findAll('select')[0].text()).toContain('inactive（已停用）')
  })

  it('creates a role with chosen permissions and then selects the returned persisted role', async () => {
    const view = await open()
    await click('新建角色')
    const inputs = view.findAll('.rbac-editor input:not([type=checkbox])')
    await inputs[0].setValue('  审核员  ')
    await inputs[1].setValue('核对销售记录')
    await view.get('input[type=checkbox]').setValue(true)
    const created = { ...custom, id: 4, key: 'review', name: '审核员', permissions: [permission] }
    vi.mocked(rbacApi.createRole).mockResolvedValue(created)
    vi.mocked(rbacApi.listRoles).mockResolvedValue([system, custom, created])
    await view.get('form').trigger('submit')
    await flushPromises()
    expect(rbacApi.createRole).toHaveBeenCalledExactlyOnceWith({ name: '审核员', description: '核对销售记录', permissions: ['sales.read'] })
    expect(view.get('[role=status]').text()).toBe('角色已创建。')
    expect(view.get('.rbac-role--active').text()).toContain('审核员')
    expect(view.findAll('.rbac-editor input:not([type=checkbox])')).toHaveLength(1)
  })

  it.each([0, 3])('updates a custom role and reports %s revoked sessions', async (revoked) => {
    const view = await open()
    await view.findAll('.rbac-role')[1].trigger('click')
    await view.get('input[type=checkbox]').setValue(true)
    await view.get('.rbac-editor input:not([type=checkbox])').setValue('更新说明')
    vi.mocked(rbacApi.updateRole).mockResolvedValue({ ...custom, sessions_revoked: revoked })
    await view.get('form').trigger('submit')
    await flushPromises()
    expect(rbacApi.updateRole).toHaveBeenCalledExactlyOnceWith(2, { description: '更新说明', permissions: ['sales.read'] })
    expect(view.get('[role=status]').text()).toContain(`${revoked} 个现有会话已撤销`)
  })

  it('keeps a failed save editable and suppresses duplicate submissions while the request is pending', async () => {
    const view = await open()
    await view.findAll('.rbac-role')[1].trigger('click')
    let reject!: (reason: Error) => void
    vi.mocked(rbacApi.updateRole).mockReturnValue(new Promise((_resolve, fail) => { reject = fail }))
    await view.get('form').trigger('submit')
    await view.get('form').trigger('submit')
    expect(rbacApi.updateRole).toHaveBeenCalledTimes(1)
    expect(view.get('button[type=submit]').text()).toBe('保存中…')
    reject(new Error('权限不足'))
    await flushPromises()
    expect(view.get('[role=alert]').text()).toBe('权限不足')
    expect(view.get('button[type=submit]').attributes('disabled')).toBeUndefined()
    expect(view.find('[role=status]').exists()).toBe(false)
  })

  it('assigns a selected user and shows the server session revocation receipt', async () => {
    const view = await open()
    expect(view.findAll('button').find((button) => button.text() === '分配角色')!.attributes('disabled')).toBeDefined()
    const selects = view.findAll('select')
    await selects[0].setValue('2')
    expect(view.text()).toContain('当前角色：销售员')
    await selects[1].setValue('sales')
    vi.mocked(rbacApi.assignRole).mockResolvedValue({ user_id: 2, role: 'sales', display_role: '销售员', sessions_revoked: 2 })
    await click('分配角色')
    expect(rbacApi.assignRole).toHaveBeenCalledExactlyOnceWith(2, 'sales')
    expect(view.get('[role=status]').text()).toContain('2 个现有会话已撤销')
    await selects[0].setValue('3')
    expect(view.text()).toContain('当前角色：external')
  })

  it.each(['load', 'save', 'assign', 'invite'])('shows a failed %s operation without a success receipt', async (operation) => {
    if (operation === 'invite') useAccountProfileStore().tenantIsOwner = true
    if (operation === 'load') vi.mocked(rbacApi.listRoles).mockRejectedValue(null)
    const view = await open()
    if (operation === 'save') {
      await view.findAll('.rbac-role')[1].trigger('click')
      vi.mocked(rbacApi.updateRole).mockRejectedValue(null)
      await view.get('form').trigger('submit')
    } else if (operation === 'assign') {
      await view.findAll('select')[0].setValue('2')
      await view.findAll('select')[1].setValue('sales')
      vi.mocked(rbacApi.assignRole).mockRejectedValue(null)
      await click('分配角色')
    } else if (operation === 'invite') {
      await view.get('input[autocomplete=off]').setValue('NEW-MEMBER')
      vi.mocked(rbacApi.inviteMember).mockRejectedValue(null)
      await click('生成邀请码')
    }
    await flushPromises()
    const expected = { load: '无法加载角色权限，请稍后重试。', save: '保存失败。', assign: '角色分配失败。', invite: '无法生成邀请码。' }
    expect(view.get('[role=alert]').text()).toBe(expected[operation as keyof typeof expected])
    expect(view.find('[role=status]').exists()).toBe(false)
  })

  it('lets the enterprise owner generate and copy the one-time invitation', async () => {
    useAccountProfileStore().tenantIsOwner = true
    const copy = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText: copy } })
    const view = await open()
    await view.get('input[autocomplete=off]').setValue('  NEW-MEMBER  ')
    vi.mocked(rbacApi.inviteMember).mockResolvedValue({ code: 'test-one-time-code', target_username: 'NEW-MEMBER', expires_at: '2026-10-08T12:00:00Z' })
    await click('生成邀请码')
    expect(rbacApi.inviteMember).toHaveBeenCalledExactlyOnceWith('NEW-MEMBER')
    expect(view.text()).toContain('24 小时内有效')
    expect(view.get('code').text()).toBe('test-one-time-code')
    await click('复制邀请码')
    expect(copy).toHaveBeenCalledExactlyOnceWith('test-one-time-code')
    expect(view.findAll('[role=status]')[0].text()).toBe('邀请码已复制。')
  })

  it('recovers from a failed refresh and selects the first available role when the selection was removed', async () => {
    const view = await open()
    await view.findAll('.rbac-role')[1].trigger('click')
    vi.mocked(rbacApi.listRoles).mockRejectedValueOnce(new Error('服务不可用'))
    await click('刷新')
    expect(view.get('[role=alert]').text()).toBe('服务不可用')
    vi.mocked(rbacApi.listRoles).mockResolvedValue([system])
    await click('刷新')
    expect(view.find('[role=alert]').exists()).toBe(false)
    expect(view.get('.rbac-role--active').text()).toContain('管理员')
  })
})
