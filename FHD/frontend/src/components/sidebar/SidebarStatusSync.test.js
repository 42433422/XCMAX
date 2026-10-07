import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useSidebarEntitlementSync } from './useSidebarEntitlementSync'
import { useSidebarAdminDeployStatus } from './useSidebarAdminDeployStatus'

const boundary = vi.hoisted(() => ({ admin: false, csrf: vi.fn(), status: vi.fn(), pull: vi.fn(), deploy: vi.fn() }))
vi.mock('@/utils/adminConsoleUrl', async (original) => ({ ...await original(), isAdminConsoleSpa: () => boundary.admin }))
vi.mock('@/api/core', async (original) => ({ ...await original(), primeCsrfCookie: boundary.csrf }))
vi.mock('@/api/xcmaxAdmin', () => ({ xcmaxAdminApi: {
  getCurrentEntitlementsSyncStatus: boundary.status, pullSync: boundary.pull, checkDeployUpdates: boundary.deploy,
} }))
let scope, account, sync, deploy
beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-07T12:00:00Z'))
  localStorage.clear()
  setActivePinia(createPinia())
  account = useAccountProfileStore()
  Object.assign(account, { loaded: true, companyBrand: 'SUNBIRD', marketUserId: 29, accountKind: 'enterprise' })
  boundary.admin = false
  boundary.csrf.mockReset().mockResolvedValue(undefined)
  boundary.pull.mockReset().mockResolvedValue(undefined)
  boundary.status.mockReset().mockResolvedValue({ data: { has_snapshot: true, snapshot: { username: 'SUNBIRD', profile: { tier: 'enterprise', industry_id: 'packaging' }, mod_ids: ['erp'] } } })
  boundary.deploy.mockReset()
  scope = effectScope()
})
afterEach(() => {
  sync?.stopEntitlementSyncPolling()
  sync?.clearEntitlementSyncNoticeTimer()
  deploy?.stopAdminDeployStatusPolling()
  scope.stop()
  sync = deploy = undefined
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
})
function entitlements() { sync = scope.run(() => useSidebarEntitlementSync()); return sync }
function deployment() { deploy = scope.run(() => useSidebarAdminDeployStatus()); return deploy }

describe('Customer entitlement status', () => {
  it.each(['unloaded', 'unbound', 'admin'])('does not query customer snapshots in %s context', async (context) => {
    if (context === 'unloaded') account.loaded = false
    if (context === 'unbound') { account.companyBrand = ''; account.marketUserId = null }
    if (context === 'admin') boundary.admin = true
    const ui = entitlements()
    await ui.refreshEntitlementSyncStatus()
    ui.syncEntitlementSyncPolling()
    expect(ui.shouldShowEntitlementSyncStatus.value).toBe(false)
    expect(ui.entitlementSyncStatusText.value).toBe('')
    expect(boundary.status).not.toHaveBeenCalled()
  })

  it('shows the bound customer snapshot and polls locally without remote pull writes', async () => {
    const ui = entitlements()
    ui.syncEntitlementSyncPolling()
    ui.syncEntitlementSyncPolling()
    await nextTick()
    expect(ui.entitlementSyncStatusText.value).toBe('权益已同步')
    expect(ui.entitlementSyncStatusTone.value).toBe('ok')
    expect(ui.entitlementSyncStatusTitle.value).toBe('账号 SUNBIRD · 等级 enterprise · 行业 packaging · Mod erp')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(boundary.status).toHaveBeenCalledTimes(2)
    expect(boundary.pull).not.toHaveBeenCalled()
    account.loaded = false
    await nextTick()
    await vi.advanceTimersByTimeAsync(30_000)
    expect(boundary.status).toHaveBeenCalledTimes(2)
    expect(ui.entitlementSyncStatusText.value).toBe('')
  })

  it('keeps a pending read distinct from a synchronized snapshot and suppresses concurrent reads', async () => {
    let resolve
    boundary.status.mockReturnValue(new Promise((done) => { resolve = done }))
    const ui = entitlements()
    const pending = ui.refreshEntitlementSyncStatus()
    expect(ui.entitlementSyncStatusText.value).toBe('权益同步中')
    expect(ui.entitlementSyncStatusTone.value).toBe('muted')
    await ui.refreshEntitlementSyncStatus()
    expect(boundary.status).toHaveBeenCalledTimes(1)
    resolve({ data: null })
    await pending
    expect(ui.entitlementSyncStatusText.value).toBe('')
  })

  it.each([[new Error('同步不可用'), '同步不可用'], [null, '权益同步失败']])('displays a failed manual pull without declaring success', async (failure, detail) => {
    boundary.pull.mockRejectedValue(failure)
    const refresh = vi.spyOn(account, 'refreshFromServer')
    const ui = entitlements()
    await ui.refreshEntitlementSyncStatus({ pull: true })
    expect(ui.entitlementSyncStatusText.value).toBe('权益未同步')
    expect(ui.entitlementSyncStatusTone.value).toBe('error')
    expect(ui.entitlementSyncStatusTitle.value).toBe(detail)
    expect(refresh).not.toHaveBeenCalled()
  })

  it('notifies a changed authenticated profile once and expires the temporary updated badge', async () => {
    boundary.status.mockRejectedValue(new Error('local snapshot unavailable'))
    vi.spyOn(account, 'refreshFromServer').mockImplementation(async () => { account.budgetRange = '10万以下' })
    const events = vi.fn()
    window.addEventListener('xcagi:account-entitlements-updated', events)
    const ui = entitlements()
    await ui.refreshEntitlementSyncStatus({ pull: true })
    expect(boundary.csrf).toHaveBeenCalledTimes(1)
    expect(ui.entitlementSyncStatusText.value).toBe('权益已更新')
    expect(ui.entitlementSyncStatusTone.value).toBe('info')
    expect(events).toHaveBeenCalledTimes(1)
    expect(events.mock.calls[0][0].detail.snapshot.market_user_id).toBe('29')
    await vi.advanceTimersByTimeAsync(45_000)
    expect(ui.entitlementSyncStatusText.value).toBe('权益已同步')
    window.removeEventListener('xcagi:account-entitlements-updated', events)
  })

  it('does not replay an already seen entitlement update', async () => {
    const stamp = Date.now() - 1000
    localStorage.setItem('xcagi_entitlements_seen_29', String(stamp))
    boundary.status.mockResolvedValue({ data: { has_snapshot: true, updated_at_ms: stamp } })
    const ui = entitlements()
    await ui.refreshEntitlementSyncStatus()
    expect(ui.entitlementSyncStatusText.value).toBe('权益已同步')
    expect(ui.entitlementSyncStatusTitle.value).toBe('')
  })
})

describe('Administrator deployment status', () => {
  it('does not expose deployment status or call the administrator API to customer accounts', async () => {
    boundary.admin = true
    const ui = deployment()
    ui.syncAdminDeployStatusPolling()
    await ui.refreshAdminDeployStatus()
    expect(ui.adminDeployStatusText.value).toBe('')
    expect(boundary.deploy).not.toHaveBeenCalled()
  })

  it.each([
    [{ needs_pack: true }, 'warn', 'v1.0.0.5 待推送'],
    [{ needs_push: true }, 'warn', 'v1.0.0.5 待推送'],
    [{ enterprise_pending: true }, 'info', '新版本 v1.0.0.5 已推送'],
    [{ up_to_date: true }, 'ok', 'v1.0.0.5 最新'],
    [{}, 'muted', 'v1.0.0.5'],
  ])('presents the actual deployment gate flags', async (flags, tone, text) => {
    boundary.admin = true
    account.accountKind = 'admin'
    account.marketIsAdmin = true
    boundary.deploy.mockResolvedValue({ data: { flags, update_hub: { version: '1.0.0.5', git_sha: 'a'.repeat(40) }, admin_local: { version: '1.0.0.4' } } })
    const ui = deployment()
    await ui.refreshAdminDeployStatus()
    expect(ui.adminDeployStatusTone.value).toBe(tone)
    expect(ui.adminDeployStatusText.value).toBe(text)
    expect(ui.adminDeployStatusTitle.value).toContain('管理端 v1.0.0.4 · update 站 v1.0.0.5 · Git aaaaaaaaaaaa')
  })

  it('shows unavailable deployment data as unknown and stops its poll after sign-out', async () => {
    boundary.admin = true
    Object.assign(account, { accountKind: 'admin', marketIsAdmin: true })
    boundary.deploy.mockResolvedValue({ message: '部署数据不可用', data: null })
    const ui = deployment()
    ui.syncAdminDeployStatusPolling()
    ui.syncAdminDeployStatusPolling()
    await nextTick()
    expect(ui.adminDeployStatusText.value).toBe('版本未知')
    expect(ui.adminDeployStatusTone.value).toBe('error')
    expect(ui.adminDeployStatusTitle.value).toBe('部署数据不可用')
    account.marketIsAdmin = false
    await nextTick()
    await vi.advanceTimersByTimeAsync(180_000)
    expect(boundary.deploy).toHaveBeenCalledTimes(1)
    expect(ui.adminDeployStatusText.value).toBe('')
  })
})
