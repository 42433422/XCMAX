import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { appConfirm } from '@/utils/appDialog'
import { useSettingsAccount } from './useSettingsAccount'
const api = vi.hoisted(() => ({ getCurrentUser: vi.fn(), validateSession: vi.fn(), logout: vi.fn() }))
const replace = vi.hoisted(() => vi.fn())
const profile = vi.hoisted(() => ({ applyFromMeData: vi.fn(), clear: vi.fn(), workspaceReady: true }))
vi.mock('@/api/auth', () => ({ authApi: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/' }), useRouter: () => ({ replace }) }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (p: string) => p }))
vi.mock('@/api/marketAccount', () => ({ LS_MARKET_USER_JSON: 'market' }))
vi.mock('@/api/adminAudit', () => ({ default: {} }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => profile }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn().mockResolvedValue(true), appAlert: vi.fn() }))
const user = { username: 'test', id: 1 }
const me = { success: true, data: { user } }
function pending() { let resolve!: (v: any) => void; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(() => { vi.resetAllMocks(); profile.applyFromMeData.mockResolvedValue(undefined); profile.workspaceReady = true; vi.mocked(appConfirm).mockResolvedValue(true); localStorage.clear(); api.getCurrentUser.mockResolvedValue(me); api.logout.mockResolvedValue({ success: true }) })
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

it('awaits required profile data and accepts only a verified success payload', async () => {
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const s = useSettingsAccount(); let complete = false
 const loading = s.loadLocalUser({ required: true, current: () => true }).then(() => { complete = true })
 await Promise.resolve(); expect(complete).toBe(false); expect(s.localUser.value).toBeNull()
 p.resolve(me); await loading
 expect(complete).toBe(true); expect(s.localUser.value).toEqual(user)
})

it.each([
 { success: false, data: { user } },
 { data: { user } },
])('rejects a required profile with an unsuccessful envelope: %j', async payload => {
 api.getCurrentUser.mockResolvedValue(payload)
 const s = useSettingsAccount()
 await expect(s.loadLocalUser({ required: true })).rejects.toThrow()
 expect(s.localUser.value).toBeNull(); expect(s.accountError.value).toBe(true)
})

it('rejects required legacy validation without a verified account identity', async () => {
 api.getCurrentUser.mockResolvedValue({ success: true, data: {} })
 api.validateSession.mockResolvedValue({ success: true, data: { valid: true } })
 const s = useSettingsAccount()
 await expect(s.loadLocalUser({ required: true })).rejects.toThrow()
 expect(s.localUser.value).toBeNull(); expect(s.accountError.value).toBe(true)
})

it('keeps the required legacy 404 fallback for a verified server username', async () => {
 api.getCurrentUser.mockRejectedValue({ status: 404 })
 api.validateSession.mockResolvedValue({ success: true, data: { valid: true, username: 'verified' } })
 const s = useSettingsAccount(); await s.loadLocalUser({ required: true })
 expect(s.localUser.value?.username).toBe('verified'); expect(s.accountError.value).toBe(false)
})

it('does not write a required account result after its startup attempt retires', async () => {
 let current = true
 const p = pending(); api.getCurrentUser.mockReturnValue(p.promise)
 const s = useSettingsAccount(); const loading = s.loadLocalUser({ required: true, current: () => current })
 current = false; p.resolve(me); await loading
 expect(s.localUser.value).toBeNull(); expect(s.sessionValid.value).toBe(false)
})

it('restarts a required retry instead of sharing the retired account request', async () => {
 const p = pending(); api.getCurrentUser.mockReturnValueOnce(p.promise).mockResolvedValueOnce(me)
 const s = useSettingsAccount(); const old = s.loadLocalUser({ required: true })
 const fresh = s.loadLocalUser({ required: true })
 await fresh; p.resolve({ success: true, data: { user: { username: 'retired' } } }); await old
 expect(api.getCurrentUser).toHaveBeenCalledTimes(2)
 expect(s.localUser.value).toEqual(user)
})

it('propagates required transport failure and permits a fresh retry', async () => {
 api.getCurrentUser.mockRejectedValueOnce(new Error('synthetic offline'))
 const s = useSettingsAccount()
 await expect(s.loadLocalUser({ required: true })).rejects.toThrow('synthetic offline')
 expect(s.accountError.value).toBe(true)
 api.getCurrentUser.mockResolvedValue(me); await s.loadLocalUser({ required: true })
 expect(s.localUser.value).toEqual(user); expect(s.accountError.value).toBe(false)
})

it('awaits the required profile application even while cached workspaceReady is already true', async () => {
 const hydration = pending(); profile.applyFromMeData.mockReturnValue(hydration.promise)
 const s = useSettingsAccount(); let ready = false
 const loading = s.loadLocalUser({ required: true }).then(() => { ready = true })
 await Promise.resolve(); await Promise.resolve()
 expect(profile.workspaceReady).toBe(true); expect(profile.applyFromMeData).toHaveBeenCalled()
 expect(ready).toBe(false); expect(s.accountLoading.value).toBe(true)
 hydration.resolve(undefined); await loading
 expect(ready).toBe(true); expect(s.accountLoading.value).toBe(false)
})

it('surfaces this required profile hydration failure rather than using previous workspace success', async () => {
 profile.applyFromMeData.mockRejectedValue(new Error('synthetic workspace hydration failure'))
 const s = useSettingsAccount()
 await expect(s.loadLocalUser({ required: true })).rejects.toThrow('synthetic workspace hydration failure')
 expect(s.accountError.value).toBe(true)
})

it('retains non-required background profile hydration degradation', async () => {
 profile.applyFromMeData.mockRejectedValue(new Error('optional profile hydration failure'))
 const s = useSettingsAccount()
 await expect(s.loadLocalUser()).resolves.toBeUndefined()
 expect(s.localUser.value).toEqual(user); expect(s.accountError.value).toBe(false)
})

it('includes required hydration in the same bounded account request budget', async () => {
 vi.useFakeTimers()
 profile.applyFromMeData.mockReturnValue(new Promise(() => {}))
 const s = useSettingsAccount()
 const loading = s.loadLocalUser({ required: true })
 const failure = expect(loading).rejects.toThrow('账号状态核实超时')
 await vi.advanceTimersByTimeAsync(8_000)
 await failure
 expect(s.accountError.value).toBe(true); expect(s.accountLoading.value).toBe(false)
})
