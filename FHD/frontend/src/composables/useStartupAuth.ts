import type { Router } from 'vue-router'
import { authApi } from '@/api/auth'
import { fetchSessionMarketHandoff, persistMarketTokensFromHandoff } from '@/api/marketAccount'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { readEntitledModIdsFromAuthPayload } from '@/stores/mods'
import type { useModsStore } from '@/stores/mods'
import { buildLoginLocation } from '@/utils/startupRedirect'
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate'
import { asRecord, asString } from '@/utils/typeGuards'
import { getAuthSessionEpoch, readValid } from '@/utils/authSessionCache'

export type StartupAuthResult = {
  ok: boolean
  entitledModIds: string[]
  accountUsername?: string
  /** The session could not be checked (timeout, dropped connection, 5xx); not a logout. */
  unavailable?: boolean
}

export function useStartupAuth(options: {
  router: Router
  modsStore: ReturnType<typeof useModsStore>
  dismissStartupSplashImmediate: () => void
}) {
  const { router, modsStore, dismissStartupSplashImmediate } = options

  async function syncMarketTokensFromSession(current: () => boolean = () => true) {
    try {
      const handoff = await fetchSessionMarketHandoff()
      if (current()) persistMarketTokensFromHandoff(handoff)
    } catch (error) {
      console.debug('[useStartupAuth] session-handoff skipped:', error instanceof Error ? error.message : error)
    }
  }

  async function ensureStartupAuthenticated(isAttemptCurrent: () => boolean = () => true): Promise<StartupAuthResult> {
    const epoch = getAuthSessionEpoch()
    const current = () => epoch === getAuthSessionEpoch() && isAttemptCurrent()
    try {
      const profile = (await import('@/stores/accountProfile')).useAccountProfileStore()
      if (profile.workspaceReady && profile.workspaceHydrationReady) {
        clearHostPackSkippedSession()
        void profile.refreshFromServer({ keepVisible: true })
        void syncMarketTokensFromSession(current)
        return { ok: true, entitledModIds: [], accountUsername: '' }
      }
      const res = await authApi.validateSession()
      if (!current()) return { ok: false, entitledModIds: [] }
      const resRow = asRecord(res)
      let valid = false
      try { valid = readValid(res) } catch { valid = false }
      if (valid) {
        clearHostPackSkippedSession()
        const profile = (await import('@/stores/accountProfile')).useAccountProfileStore()
        // Login already hydrated this account. A second remote profile read must not
        // keep the shell locked; RBAC refresh continues behind the workspace.
        if (profile.workspaceReady && profile.workspaceHydrationReady) void profile.refreshFromServer()
        else {
          await profile.refreshFromServer().catch(() => {
            /* ignore */
          })
        }
        if (!current()) return { ok: false, entitledModIds: [] }
        // Optional token synchronization must not block the authenticated workspace.
        void syncMarketTokensFromSession(current)
        let entitledModIds: string[] = []
        let accountUsername = ''
        try {
          entitledModIds = readEntitledModIdsFromAuthPayload(res)
          const data = res?.data && typeof res.data === 'object' && !Array.isArray(res.data) ? asRecord(res.data) : resRow
          const user = asRecord(data.user)
          accountUsername = asString(data.username || user.username).trim()
        } catch {
          /* ignore */
        }
        return { ok: true, entitledModIds, accountUsername }
      }
    } catch (error) {
      if (!current()) return { ok: false, entitledModIds: [] }
      const status = Number((error as { status?: unknown } | null)?.status)
      // Timeout, abort, or a dropped connection is not a logged-out session.
      if (status !== 401 && status !== 403) return { ok: false, entitledModIds: [], unavailable: true }
    }
    if (!current()) return { ok: false, entitledModIds: [] }
    dismissStartupSplashImmediate()
    const loc =
      typeof window !== 'undefined'
        ? {
            pathname: window.location.pathname,
            search: window.location.search,
            hash: window.location.hash,
          }
        : {}
    void router.replace(buildLoginLocation(loc, import.meta.env.BASE_URL))
    return { ok: false, entitledModIds: [] }
  }

  async function runEnterpriseStartupAuth(isPublicEntryRoute: () => boolean): Promise<boolean> {
    if (isPublicEntryRoute()) return true
    const epoch = getAuthSessionEpoch()
    // P0 优化3：fetchProductSku 与 auth 校验互相无依赖，并行执行节省 ~1RT
    const skuPromise = fetchProductSku().catch(() => 'generic' as string)
    const authPromise = ensureStartupAuthenticated()
    const [sku, authResult] = await Promise.all([skuPromise, authPromise])
    if (!authResult.ok || epoch !== getAuthSessionEpoch()) return false
    if (!isEnterpriseEdition(sku)) return true
    try {
      await modsStore.initialize(true, {
        entitledModIds: authResult.entitledModIds,
        forceFromEntitlements: authResult.entitledModIds.length > 0,
        accountUsername: authResult.accountUsername,
      })
    } catch (e) {
      console.warn('[useStartupAuth] mods initialize after auth:', e)
    }
    return true
  }

  return {
    ensureStartupAuthenticated,
    runEnterpriseStartupAuth,
    syncMarketTokensFromSession,
  }
}
