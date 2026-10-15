import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useLoginViewState } from '@/views/login-view/useLoginViewState'
import { useLoginViewSession } from '@/views/login-view/useLoginViewSession'
import { useLoginViewActions } from '@/views/login-view/useLoginViewActions'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useIndustryStore } from '@/stores/industry'

// Keep login actions/session, auth HTTP API/core, profile, tenant prefs hydration,
// industry store and industry HTTP APIs real. Mock only unrelated UI/discovery edges.
vi.mock('vue-i18n', async (original) => ({ ...await original<typeof import('vue-i18n')>(), useI18n: () => ({ t: (s: string) => s }) }))
vi.mock('@/api', async () => ({ ApiError: (await import('@/api/core')).ApiError }))
vi.mock('@/api/marketAccount', () => ({
 LS_MARKET_REFRESH_TOKEN: 'test-market-refresh', LS_MARKET_ACCESS_TOKEN: 'test-market-token', LS_MARKET_USER_JSON: 'test-market-user',
 applyMarketTokensAfterFhdLogin: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('@/utils/platformShellApi', () => ({ clearDeliverableStatusCache: vi.fn() }))
vi.mock('@/utils/hostPackOnboardingGate', () => ({ clearHostPackSkippedSession: vi.fn() }))
vi.mock('@/utils/productSku', () => ({ fetchProductSku: vi.fn().mockResolvedValue('enterprise'), isEnterpriseEdition: () => true }))
vi.mock('@/utils/desktopShell', () => ({ isDesktopShell: () => true }))
vi.mock('@/utils/adminConsoleUrl', () => ({ isAdminConsoleSpa: () => false, DESKTOP_ADMIN_FORBIDDEN_MESSAGE: 'forbidden', resolveAdminConsoleLoginUrl: () => '' }))
vi.mock('@/utils/erpDomainPaths', () => ({ resolveErpApiPathWhenReady: async (p: string) => p }))
vi.mock('@/stores/workflowAiEmployees', () => ({ useWorkflowAiEmployeesStore: () => ({ reloadForTenantScope: vi.fn() }), workflowAiEmployeesStorageKey: () => 'test-employees' }))
vi.mock('@/stores/workflowEmployeeSpace', () => ({ useWorkflowEmployeeSpaceStore: () => ({ reloadForTenantScope: vi.fn() }) }))
vi.mock('@/stores/mods', () => ({ readEntitledModIdsFromAuthPayload: () => [], useModsStore: () => ({ mods: [], activeModId: '', reloadActiveModForTenantScope: vi.fn(), initialize: vi.fn().mockResolvedValue(undefined) }) }))

const payload = { success: true, data: { account_kind: 'enterprise', market_is_enterprise: true, tenant_id: 10, user: { id: 20, username: 'synthetic-enterprise', role: 'tenant:member' } } }
const industry = { success: true, data: { id: '考勤', name: '考勤', config: { units: { primary: '天' } } } }
const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } })
let calls: Array<{ url: string; signal: AbortSignal | null | undefined }> = []
let releaseIndustry: (() => void) | undefined
let failIndustry: (() => void) | undefined
function beginLogin(delayIndustry: boolean, tenant = 10, failure: 'industry' | 'list' | 'invalid' | 'prefs' | null = null) {
 vi.stubGlobal('fetch', vi.fn((input: string, options: RequestInit = {}) => {
  const url = new URL(input, 'http://localhost').pathname
  calls.push({ url, signal: options.signal })
  if (url === '/health') return Promise.resolve(json({ healthy: true }))
  if (url === '/api/auth/login') return Promise.resolve(json({ ...payload, data: { ...payload.data, tenant_id: tenant } }))
  if (url === '/api/workspace/prefs' && failure === 'prefs') return new Promise<Response>(resolve => { releaseIndustry = () => resolve(json({ success: true, owner_id: `tenant:${tenant}`, data: {} })) })
  if (url === '/api/workspace/prefs') return Promise.resolve(json({ success: true, owner_id: `tenant:${tenant}`, data: { selected_industry_id: '考勤', product_flow_completed: true } }))
  if (url === '/api/system/industries') return failure === 'list' ? Promise.reject(new Error('list unavailable')) : Promise.resolve(json({ success: true, data: { industries: [] } }))
  if (url === '/api/system/industry') {
   const selected = tenant === 10 ? industry : { success: true, data: { id: '涂料', name: '涂料', units: { primary: '桶' } } }
   if (failure === 'industry') return Promise.resolve(new Response('{}', { status: 403, headers: { 'Content-Type': 'application/json' } }))
   if (failure === 'invalid') return Promise.resolve(json({ success: false }))
   if (!delayIndustry) return Promise.resolve(json(selected))
   return new Promise<Response>((resolve, reject) => {
    releaseIndustry = () => resolve(json(selected))
    failIndustry = () => reject(new Error('late failure'))
    options.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
   })
  }
  throw new Error(`Unexpected request forbidden in isolated test: ${url}`)
 }))
 const state = useLoginViewState({ query: {} } as any)
 state.productSku.value = 'enterprise'
 state.username.value = 'synthetic-enterprise'
 state.password.value = 'synthetic-test-password'
 const router = { replace: vi.fn().mockResolvedValue(undefined) }
 const profile = useAccountProfileStore()
 vi.spyOn(profile, 'refreshFromServer').mockResolvedValue(undefined)
 const session = useLoginViewSession(state, { router: router as any })
 const actions = useLoginViewActions(state, { completeLoginSuccess: session.completeLoginSuccess, qr: { startQrLogin: vi.fn(), stopQrPoll: vi.fn() } as any })
 let settled = false
 const submitting = actions.submitLogin().finally(() => { settled = true })
 return { state, router, profile, submitting, isSettled: () => settled }
}
beforeEach(() => {
 setActivePinia(createPinia())
 localStorage.clear(); sessionStorage.clear(); document.cookie = 'csrf_token=synthetic-test-csrf'
 calls = []; releaseIndustry = undefined
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('normal login workspace readiness', () => {
 it('control: immediate industry response finishes real login await chain', async () => {
  const login = beginLogin(false)
  await login.submitting
  expect(login.router.replace).toHaveBeenCalledOnce()
  expect(login.state.loading.value).toBe(false)
  expect(login.profile.tenantId).toBe(10)
  expect(login.profile.permissions).toEqual([])
  expect(calls.map(c => c.url)).toContain('/api/auth/login')
  expect(useIndustryStore().currentIndustryId).toBe('考勤')
 })
 it.each([1, 2, 3])('bounds the industry stall and permits a safe retry, repetition %s', async () => {
  vi.useFakeTimers()
  const login = beginLogin(true)
  await vi.waitFor(() => expect(releaseIndustry).toBeTypeOf('function'))
  const pending = calls.find(c => c.url === '/api/system/industry')!
  expect(pending.signal).toBeDefined()
  await vi.advanceTimersByTimeAsync(8000)
  await login.submitting
  expect(pending.signal?.aborted).toBe(true)
  expect(login.state.loading.value).toBe(false)
  expect(login.state.errorMessage.value).toContain('重新登录')
  expect(login.router.replace).not.toHaveBeenCalled()
  expect(login.profile.loaded).toBe(false)
  expect(login.profile.workspaceReady).toBe(false)
  expect(login.profile.permissions).toEqual([])
  expect(calls.map(c => c.url)).not.toContain('/api/auth/logout')
  const retry = beginLogin(false)
  await retry.submitting
  expect(retry.router.replace).toHaveBeenCalledOnce()
  expect(retry.profile.workspaceReady).toBe(true)
  expect(useIndustryStore().currentIndustryId).toBe('考勤')
 })
 it.each(['industry', 'invalid'] as const)('keeps business closed on %s response without inventing industry/permissions', async (failure) => {
  const login = beginLogin(false, 10, failure)
  await login.submitting
  expect(login.state.errorMessage.value).toContain('重新登录')
  expect(login.router.replace).not.toHaveBeenCalled()
  expect(login.profile.workspaceReady).toBe(false)
  expect(login.profile.permissions).toEqual([])
  expect(useIndustryStore().currentIndustry).toBeNull()
 })
 it('does not confuse unavailable display list with permission or current-industry failure', async () => {
  const login = beginLogin(false, 10, 'list')
  await login.submitting
  expect(login.router.replace).toHaveBeenCalledOnce()
  expect(login.profile.permissions).toEqual([])
  expect(useIndustryStore().industries).toEqual([])
  expect(useIndustryStore().currentIndustryId).toBe('考勤')
 })
 it.each([[10, false], [10, true], [11, false], [11, true]])('ignores stale completion for next tenant %s, failure=%s', async (tenant, fail) => {
  const previous = beginLogin(true)
  await vi.waitFor(() => expect(releaseIndustry).toBeTypeOf('function'))
  const finishPrevious = fail ? failIndustry! : releaseIndustry!
  const latest = beginLogin(false, tenant as number)
  await latest.submitting
  localStorage.setItem('test-market-token', 'new-session')
  finishPrevious()
  await previous.submitting
  expect(previous.router.replace).not.toHaveBeenCalled()
  expect(latest.router.replace).toHaveBeenCalledOnce()
  expect(latest.profile.tenantId).toBe(tenant)
  expect(latest.profile.workspaceReady).toBe(true)
  expect(localStorage.getItem('test-market-token')).toBe('new-session')
  expect(useIndustryStore().currentIndustryId).toBe(tenant === 10 ? '考勤' : '涂料')
 })

 it("retains this account's verified units during a background profile refresh", async () => {
  const login = beginLogin(false)
  await login.submitting
  let release!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/industry')
    ? new Promise<Response>(resolve => { release = resolve })
    : Promise.resolve(json({ success: true, data: { industries: [] } }))))
  const refreshing = login.profile.applyFromMeData(payload.data)
  await vi.waitFor(() => expect(release).toBeTypeOf('function'))
  expect(login.profile.workspaceReady).toBe(true)
  expect(useIndustryStore().currentIndustryId).toBe('考勤')
  release(json(industry))
  await refreshing
 })

 it("ignores the previous account's preference hydration finishing after the next login", async () => {
  const previous = beginLogin(false, 10, 'prefs')
  await vi.waitFor(() => expect(releaseIndustry).toBeTypeOf('function'))
  const finishPrevious = releaseIndustry!
  const latest = beginLogin(false, 11)
  await latest.submitting
  const industryRequests = calls.filter(c => c.url === '/api/system/industry').length
  finishPrevious()
  await previous.submitting
  expect(previous.router.replace).not.toHaveBeenCalled()
  expect(latest.profile.tenantId).toBe(11)
  expect(latest.profile.workspaceReady).toBe(true)
  expect(calls.filter(c => c.url === '/api/system/industry')).toHaveLength(industryRequests)
 })

})
