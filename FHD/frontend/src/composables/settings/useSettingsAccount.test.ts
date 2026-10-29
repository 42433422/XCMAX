import { beforeEach, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { appConfirm } from '@/utils/appDialog'
import { useSettingsAccount } from './useSettingsAccount'
const api = vi.hoisted(() => ({ getCurrentUser: vi.fn(), validateSession: vi.fn(), logout: vi.fn() }))
vi.mock('@/api/auth', () => ({ authApi: api }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ fullPath: '/' }), useRouter: () => ({ replace: vi.fn() }) }))
vi.mock('@/api/core', () => ({ buildFullApiUrl: (p: string) => p }))
vi.mock('@/api/marketAccount', () => ({ LS_MARKET_USER_JSON: 'market' }))
vi.mock('@/api/adminAudit', () => ({ default: {} }))
vi.mock('@/stores/accountProfile', () => ({ useAccountProfileStore: () => ({ applyFromMeData: vi.fn().mockResolvedValue(undefined), clear: vi.fn() }) }))
vi.mock('@/utils/appDialog', () => ({ appConfirm: vi.fn().mockResolvedValue(true), appAlert: vi.fn() }))
const user = { username: 'test', id: 1 }
const me = { success: true, data: { user } }
function pending() { let resolve!: (v: any) => void; const promise = new Promise(r => { resolve = r }); return { promise, resolve } }
beforeEach(() => { vi.resetAllMocks(); vi.mocked(appConfirm).mockResolvedValue(true); localStorage.clear(); api.getCurrentUser.mockResolvedValue(me); api.logout.mockResolvedValue({ success: true }) })
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
 scope.stop(); p.resolve(me); await loading; expect(s.isLoggedIn.value).toBe(false)
})
