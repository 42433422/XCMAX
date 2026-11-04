import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi, type AccountKind, type AccountTier } from '@/api/auth'
import { captureAuthSession, getAuthSessionEpoch, invalidateEnterpriseSessionCache, validateEnterpriseSessionCached } from '@/utils/authSessionCache'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { refreshTenantScopedClientStores } from '@/utils/refreshTenantScopedClientStores'
import { setRuntimeTenantStorageScopeInput } from '@/utils/tenantStorageScopeRuntime'
import type { TenantStorageScopeInput } from '@/utils/tenantStorageScope'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'

const SCOPE_MOVED = '登录工作空间已改变，请重试'

function scopeMoved(error: unknown): boolean {
  return error instanceof Error && error.message === SCOPE_MOVED
}

function buildScopeInput(
  tenantId: number | null,
  marketUserId: number | null,
  localUserId: number | null,
  accountKind: AccountKind,
  marketUsername: string,
): TenantStorageScopeInput {
  return {
    tenantId,
    marketUserId,
    localUserId,
    marketUsername: marketUsername || undefined,
    accountKind,
  }
}

async function syncTenantScopedStoresFromProfile(
  tenantId: number | null,
  marketUserId: number | null,
  localUserId: number | null,
  accountKind: AccountKind,
  marketUsername: string,
): Promise<void> {
  const input = buildScopeInput(tenantId, marketUserId, localUserId, accountKind, marketUsername)
  setRuntimeTenantStorageScopeInput(input)
  const refreshing = refreshTenantScopedClientStores(input)
  const epoch = productReadAccountEpoch.value
  await refreshing
  // Preferences already retried once inside the refresh. If the generation
  // still moved, a newer profile read owns industry loading — do not fail this login.
  if (epoch !== productReadAccountEpoch.value) return
  if (tenantId !== null || localUserId !== null || marketUserId !== null) {
    const { useIndustryStore } = await import('@/stores/industry')
    try {
      await useIndustryStore().loadFromServer(accountKind !== 'admin')
    } catch (error) {
      if (scopeMoved(error)) return
      throw error
    }
  }
}

export const useAccountProfileStore = defineStore('accountProfile', () => {
  const accountKind = ref<AccountKind>('enterprise')
  const companyBrand = ref('')
  const marketIsAdmin = ref(false)
  const marketIsEnterprise = ref(false)
  const tenantId = ref<number | null>(null)
  const tenantName = ref('')
  const marketUserId = ref<number | null>(null)
  const localUserId = ref<number | null>(null)
  const impersonatingMarketUserId = ref<number | null>(null)
  const impersonatingUsername = ref('')
  // 账号体系真相源（前端只读展示）：身份 / 等级 / 预算 / 已授权行业 / 会员
  const tier = ref<AccountKind | null>(null)
  const accountTier = ref<AccountTier | null>(null)
  const budgetRange = ref('')
  const entitledIndustries = ref<string[]>([])
  const marketMembershipTier = ref<string | null>(null)
  const permissions = ref<string[]>([])
  const tenantIsOwner = ref(false)
  const userRole = ref('')
  const loaded = ref(false)
  const sessionCheckUnavailable = ref(false)
  const workspaceEpoch = ref(-1)
  const workspaceHydrationReady = ref(false)
  // Hydration readiness outlives a later scope-generation bump. The epoch match
  // only keeps an already verified workspace visible while the next read is in flight.
  const workspaceReady = computed(() => loaded.value && (
    workspaceHydrationReady.value || workspaceEpoch.value === productReadAccountEpoch.value
  ))
  let hydrationEpoch = 0
  let clearedEpoch = 0
  let latestHydration: { epoch: number; promise: Promise<void> } | null = null

  const isAdminAccount = computed(() => accountKind.value === 'admin' && marketIsAdmin.value)

  const isImpersonating = computed(() => impersonatingMarketUserId.value != null)

  const displayBrand = computed(() => {
    const brand = companyBrand.value.trim()
    if (brand) return brand
    return ''
  })

  function applySessionFields(data: Record<string, unknown>): Promise<void> {
    sessionCheckUnavailable.value = false
    const epoch = ++hydrationEpoch
    workspaceHydrationReady.value = false
    const kind = String(data.account_kind || 'enterprise').trim()
    if (kind === 'personal' || kind === 'enterprise' || kind === 'admin') {
      accountKind.value = kind
    }
    companyBrand.value = String(data.company_brand || '').trim()
    marketIsAdmin.value = Boolean(data.market_is_admin)
    marketIsEnterprise.value = Boolean(data.market_is_enterprise)
    // 会话校验与登录等局部载荷不含租户/权限键；缺失键必须保留已知状态，否则会把设置页里
    // 依赖权限的入口（如「角色与权限」）清掉（显式 null 仍然表示“无”）。
    if ('tenant_id' in data) {
      const tid = data.tenant_id
      tenantId.value = tid === null || tid === undefined || tid === '' ? null : Number(tid)
    }
    tenantName.value = String(data.tenant_name || data.company_brand || '').trim()
    const mid = data.market_user_id
    marketUserId.value = mid === null || mid === undefined || mid === '' ? null : Number(mid)
    const lid = data.local_user_id
    if (lid === null || lid === undefined || lid === '') {
      const nested = data.user
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        const uid = (nested as Record<string, unknown>).id
        localUserId.value = uid === null || uid === undefined || uid === '' ? null : Number(uid)
      }
    } else {
      localUserId.value = Number(lid)
    }
    const imp = data.impersonating_market_user_id
    impersonatingMarketUserId.value = imp === null || imp === undefined || imp === '' ? null : Number(imp)
    impersonatingUsername.value = String(data.impersonating_username || '').trim()
    const t = String(data.tier || '').trim()
    tier.value = t === 'personal' || t === 'enterprise' || t === 'admin' ? t : null
    const at = String(data.account_tier || '').trim()
    accountTier.value = at === 'normal' || at === 'pro' || at === 'max' || at === 'ultra' ? at : null
    budgetRange.value = String(data.budget_range || '').trim()
    entitledIndustries.value = Array.isArray(data.entitled_industries) ? (data.entitled_industries as unknown[]).map((x) => String(x)) : []
    const mmt = data.market_membership_tier
    marketMembershipTier.value = mmt === null || mmt === undefined || mmt === '' ? null : String(mmt).trim()
    if (Array.isArray(data.permissions)) permissions.value = (data.permissions as unknown[]).map(String)
    if ('tenant_is_owner' in data) tenantIsOwner.value = data.tenant_is_owner === true
    const nestedUser = data.user
    userRole.value = nestedUser && typeof nestedUser === 'object' && !Array.isArray(nestedUser)
      ? String((nestedUser as Record<string, unknown>).role || '') : ''
    loaded.value = true
    const hydration = syncTenantScopedStoresFromProfile(
      tenantId.value,
      marketUserId.value,
      localUserId.value,
      accountKind.value,
      impersonatingUsername.value,
    )
    // The synchronous scope update above establishes the owner of this hydration.
    const scopeCurrent = captureAuthSession()
    const authAtStart = getAuthSessionEpoch()
    const cleared = clearedEpoch
    function publishReady() {
      workspaceEpoch.value = productReadAccountEpoch.value
      workspaceHydrationReady.value = true
    }
    async function finish(error?: unknown, failed = false): Promise<void> {
      let observed = epoch
      while (scopeCurrent() && cleared === clearedEpoch) {
        const latest = latestHydration
        if (latest && latest.epoch > observed) {
          observed = latest.epoch
          try { await latest.promise; failed = false }
          catch (newerError) { error = newerError; failed = true }
          continue
        }
        if (observed !== hydrationEpoch) break
        if (failed) throw error
        // Earlier same-owner reads join the newest result; only its own read publishes readiness.
        if (epoch === hydrationEpoch) publishReady()
        return
      }
      // A scope-generation bump from a concurrent refresh is not a new login.
      // The latest read adopts the current generation; superseded reads still fail.
      if (cleared !== clearedEpoch || authAtStart !== getAuthSessionEpoch()) throw new Error(SCOPE_MOVED)
      if (epoch === hydrationEpoch && (!failed || scopeMoved(error))) {
        publishReady()
        return
      }
      if (failed) throw error
      throw new Error(SCOPE_MOVED)
    }
    const promise = hydration.then(() => finish(), error => finish(error, true))
    latestHydration = { epoch, promise }
    return promise
  }

  function applyFromMeData(data: Record<string, unknown> | null | undefined): Promise<void> {
    if (!data || typeof data !== 'object') return Promise.resolve()
    return applySessionFields(data)
  }

  function applyFromLoginPayload(raw: Record<string, unknown>): Promise<void> {
    const payload = raw.data && typeof raw.data === 'object' && !Array.isArray(raw.data) ? (raw.data as Record<string, unknown>) : raw
    return applySessionFields(payload)
  }

  async function refreshFromServer() {
    const retryUnavailable = sessionCheckUnavailable.value
    let requestEpoch = hydrationEpoch
    const authEpoch = getAuthSessionEpoch(), cleared = clearedEpoch
    let scopeCurrent = captureAuthSession()
    const current = () => scopeCurrent() && authEpoch === getAuthSessionEpoch() && cleared === clearedEpoch
    async function followLatestHydration() {
      let error: unknown, failed = false
      while (current()) {
        const latest = latestHydration
        if (!latest || latest.epoch <= requestEpoch) {
          if (failed) throw error
          return
        }
        requestEpoch = latest.epoch
        try { await latest.promise; failed = false }
        catch (newerError) { error = newerError; failed = true }
      }
    }
    try {
      let sku = 'generic'
      try {
        sku = await fetchProductSku()
      } catch {
        /* ignore */
      }
      if (isEnterpriseEdition(sku)) {
        const valid = await validateEnterpriseSessionCached(retryUnavailable)
        if (!current()) return
        if (requestEpoch !== hydrationEpoch) {
          while (current() && requestEpoch !== hydrationEpoch) await followLatestHydration()
          return
        }
        if (!valid) {
          clear()
          return
        }
      }
      const res = await authApi.getCurrentUser()
      if (!current()) return
      if (requestEpoch !== hydrationEpoch) {
        while (current() && requestEpoch !== hydrationEpoch) await followLatestHydration()
        return
      }
      if (res?.success && res.data) {
        const hydration = applyFromMeData(res.data as Record<string, unknown>)
        requestEpoch = hydrationEpoch
        scopeCurrent = captureAuthSession()
        await hydration
        return
      }
      invalidateEnterpriseSessionCache()
      clear()
    } catch (caughtError) {
      let error = caughtError
      while (current() && requestEpoch !== hydrationEpoch) {
        try {
          await followLatestHydration()
          if (current() && requestEpoch === hydrationEpoch) return
        } catch (newerError) { error = newerError }
      }
      if (!current()) return
      // 仅当服务端明确判定会话失效（401/403）才清空资料；超时/被取代/网络抖动属瞬时失败，清空会隐藏依赖权限的入口。
      const status = (error as { status?: unknown } | null | undefined)?.status
      if (status !== 401 && status !== 403) { sessionCheckUnavailable.value = true; return }
      invalidateEnterpriseSessionCache()
      clear()
    }
  }

  function clear(hydrate = true) {
    hydrationEpoch++
    clearedEpoch++
    latestHydration = null
    sessionCheckUnavailable.value = false
    workspaceEpoch.value = -1
    workspaceHydrationReady.value = false
    accountKind.value = 'enterprise'
    companyBrand.value = ''
    marketIsAdmin.value = false
    marketIsEnterprise.value = false
    tenantId.value = null
    tenantName.value = ''
    marketUserId.value = null
    localUserId.value = null
    impersonatingMarketUserId.value = null
    impersonatingUsername.value = ''
    tier.value = null
    accountTier.value = null
    budgetRange.value = ''
    entitledIndustries.value = []
    marketMembershipTier.value = null
    permissions.value = []
    tenantIsOwner.value = false
    userRole.value = ''
    loaded.value = false
    setRuntimeTenantStorageScopeInput(null)
    void refreshTenantScopedClientStores({ tenantId: null, accountKind: 'enterprise' }, hydrate)
  }

  return {
    accountKind,
    companyBrand,
    marketIsAdmin,
    marketIsEnterprise,
    tenantId,
    tenantName,
    marketUserId,
    localUserId,
    impersonatingMarketUserId,
    impersonatingUsername,
    tier,
    accountTier,
    budgetRange,
    entitledIndustries,
    marketMembershipTier,
    permissions,
    tenantIsOwner,
    userRole,
    loaded,
    workspaceReady,
    workspaceHydrationReady,
    isAdminAccount,
    isImpersonating,
    displayBrand,
    applyFromMeData,
    applyFromLoginPayload,
    refreshFromServer,
    sessionCheckUnavailable,
    clear,
  }
})
