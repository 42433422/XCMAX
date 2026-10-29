import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { appConfirm } from '@/utils/appDialog'
import { useSettingsAccount } from './useSettingsAccount'
const api = vi.hoisted(() => ({ getCurrentUser: vi.fn(), validateSession: vi.fn(), logout: vi.fn() }))
const replace = vi.hoisted(() => vi.fn())
vi.mock('@/api/auth', () => ({ authApi: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/' }), useRouter: () => ({ replace }) }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (p: string) => p }))
vi.mock('@/api/marketAccount', () => ({ LS_MARKET_USER_JSON: 'market' }))
vi.mock('@/api/adminAudit', () => ({ default: {} }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => ({ applyFromMeData: vi.fn().mockResolvedValue(undefined), clear: vi.fn() }) }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn().mockResolvedValue(true), appAlert: vi.fn() }))
const user = { username: 'test', id: 1 }
const me = { success: true, data: { user } }
function pending() { let resolve!: (v: any) => void; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(appConfirm).mockResolvedValue(true); localStorage.clear(); api.getCurrentUser.mockResolvedValue(me); api.logout.mockResolvedValue({ success: true }) })
afterEach(() => vi.useRealTimers())
it('coalesces mount and activation and shows checking instead of signed out', async () => {
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const s = useSettingsAccount(); const a = s.loadLocalUser(); const b = s.loadLocalUser()
 expect(a).toBe(b); expect(api.getCurrentUser).toHaveBeenCalledTimes(1)
 expect(s.profileBrandTitle.value).toBe('settings.accountChecking')
 p.resolve(me); await a; expect(s.isLoggedIn.value).toBe(true)
})
it('preserves known identity on transient failures', async () => {
 const s = useSettingsAccount(); await s.loadLocalUser()
 api.getCurrentUser.mockRejectedValue(new Error('offline')); api.validateSession.mockRejectedValue(new Error('offline'))
 await s.loadLocalUser(); expect(s.localUser.value).toEqual(user); expect(s.accountError.value).toBe(true)
 expect(api.validateSession).not.toHaveBeenCalled()
})
it('honors explicit invalid even when success is true', async () => {
 const s = useSettingsAccount(); await s.loadLocalUser()
 api.getCurrentUser.mockResolvedValue({}); api.validateSession.mockResolvedValue({ success: true, data: { valid: false } })
 await s.loadLocalUser(); expect(s.isLoggedIn.value).toBe(false); expect(s.accountError.value).toBe(false)
})
it('recognizes a valid session without profile metadata', async () => {
 api.getCurrentUser.mockResolvedValue({}); api.validateSession.mockResolvedValue({ data: { valid: true } })
 const s = useSettingsAccount(); await s.loadLocalUser(); expect(s.isLoggedIn.value).toBe(true)
})
it('does not let a pre-logout response restore the account', async () => {
 const s = useSettingsAccount(); await s.loadLocalUser(); const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const load = s.loadLocalUser(); await s.onLogout(); p.resolve(me); await load
 expect(s.isLoggedIn.value).toBe(false)
})

it.each([401, 403])('clears expired credentials on HTTP %s', async status => {
 const s = useSettingsAccount(); await s.loadLocalUser()
 api.getCurrentUser.mockRejectedValue({ status }); api.validateSession.mockRejectedValue({ status })
 await s.loadLocalUser(); expect(s.isLoggedIn.value).toBe(false); expect(s.accountError.value).toBe(false)
})

it('rejects a response after an account switch', async () => {
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const s = useSettingsAccount(); const loading = s.loadLocalUser(); productReadAccountEpoch.value++
 p.resolve(me); await loading; expect(s.isLoggedIn.value).toBe(false)
})
it('retires a disposed settings request', async () => {
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const scope = effectScope(); const s = scope.run(() => useSettingsAccount())!; const loading = s.loadLocalUser()
 scope.stop(); expect(api.getCurrentUser.mock.calls[0][0].signal.aborted).toBe(true)
 p.resolve(me); await loading; expect(s.isLoggedIn.value).toBe(false)
})

it('shares one eight-second budget between the profile and legacy validation fallback', async () => {
 vi.useFakeTimers()
 const s = useSettingsAccount(); await s.loadLocalUser()
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 api.validateSession.mockReturnValue(new Promise(() => {}))
 const loading = s.loadLocalUser()
 await vi.advanceTimersByTimeAsync(7_000)
 p.resolve({}); await vi.advanceTimersByTimeAsync(0)
 expect(api.validateSession).toHaveBeenCalledTimes(1)
 await vi.advanceTimersByTimeAsync(999); expect(s.accountLoading.value).toBe(true)
 await vi.advanceTimersByTimeAsync(1); await loading
 expect(s.accountLoading.value).toBe(false); expect(s.accountError.value).toBe(true)
 expect(s.localUser.value).toEqual(user)
 expect(api.validateSession.mock.calls[0][0].signal.aborted).toBe(true)
})

it('does not adopt a stored username or avatar when validation has no verified identity', async () => {
 localStorage.setItem('market', JSON.stringify({ username: 'previous-account', avatar: 'https://example.test/a.png' }))
 api.getCurrentUser.mockResolvedValue({}); api.validateSession.mockResolvedValue({ data: { valid: true } })
 const s = useSettingsAccount(); await s.loadLocalUser()
 expect(s.isLoggedIn.value).toBe(true); expect(s.localUser.value).toBeNull(); expect(s.profileAvatarUrl.value).toBe('')
})

it.each(['success', 'unauthorized'])('ignores old %s after the shared session is invalidated', async outcome => {
 const scope = effectScope(); const s = scope.run(() => useSettingsAccount())!; await s.loadLocalUser()
 let settle!: (value: unknown) => void
 api.getCurrentUser.mockReturnValue(new Promise((resolve, reject) => { settle = outcome === 'success' ? resolve : reject }))
 const loading = s.loadLocalUser(); invalidateEnterpriseSessionCache()
 settle(outcome === 'success' ? { data: { user: { username: 'old-account' } } } : { status: 401 })
 await loading; expect(s.localUser.value).toBeNull(); expect(s.isLoggedIn.value).toBe(false); expect(s.accountError.value).toBe(false)
 scope.stop()
})

it('clears the local identity even when the logout request fails', async () => {
 const s = useSettingsAccount(); await s.loadLocalUser()
 api.logout.mockRejectedValue(new Error('offline'))
 await s.onLogout()
 expect(s.isLoggedIn.value).toBe(false); expect(s.profileDisplayNameDraft.value).toBe('')
 expect(s.accountError.value).toBe(true); expect(s.logoutLoading.value).toBe(false)
})

it('does not confirm logout for an account that changed while the dialog was open', async () => {
 let confirm!: (value: boolean) => void
 vi.mocked(appConfirm).mockReturnValue(new Promise(resolve => { confirm = resolve }))
 const s = useSettingsAccount(); const logout = s.onLogout()
 invalidateEnterpriseSessionCache(); confirm(true); await logout
 expect(api.logout).not.toHaveBeenCalled()
})

it('finishes the global logout redirect after profile clearing retires the settings scope', async () => {
 const p = pending(); api.logout.mockReturnValue(p.promise)
 const scope = effectScope(); const s = scope.run(() => useSettingsAccount())!
 const logout = s.onLogout(); await Promise.resolve()
 expect(api.logout).toHaveBeenCalledTimes(1)
 scope.stop(); p.resolve({ success: true }); await logout
 expect(replace).toHaveBeenCalledWith({ name: 'login', query: { redirect: '/' } })
})

it('does not redirect a new login when an earlier logout finishes', async () => {
 const p = pending(); api.logout.mockReturnValue(p.promise)
 const s = useSettingsAccount(); const logout = s.onLogout(); await Promise.resolve()
 invalidateEnterpriseSessionCache(); p.resolve({ success: true }); await logout
 expect(replace).not.toHaveBeenCalled()
})

it('provides both translated state labels', async () => {
 for (const lang of ['zh-CN', 'en-US']) {
  const messages = await import(`../../i18n/locales/${lang}/settings.json`)
  expect(messages.default.settings.accountChecking).toBeTruthy()
  expect(messages.default.settings.accountUnavailable).toBeTruthy()
 }
})
