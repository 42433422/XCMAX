import type { Router } from 'vue-router'
import { authApi } from '@/api/auth'
import { fetchSessionMarketHandoff, persistMarketTokensFromHandoff } from '@/api/marketAccount'
import { fetchProductSku, isEnterpriseEdition } from '@/utils/productSku'
import { readEntitledModIdsFromAuthPayload } from '@/stores/mods'
import type { useModsStore } from '@/stores/mods'
import { buildLoginLocation } from '@/utils/startupRedirect'
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate'
import { asRecord, asArray, asString } from '@/utils/typeGuards'

export type StartupAuthResult = {
  ok: boolean
  entitledModIds: string[]
  accountUsername?: string
}

export function useStartupAuth(options: {
  router: Router
  modsStore: ReturnType<typeof useModsStore>
  dismissStartupSplashImmediate: () => void
}) {
  const { router, modsStore, dismissStartupSplashImmediate } = options

  async function syncMarketTokensFromSession() {
    try {
      const handoff = await fetchSessionMarketHandoff()
      persistMarketTokensFromHandoff(handoff)
    } catch (error) {
      console.debug(
        '[useStartupAuth] session-handoff skipped:',
        error instanceof Error ? error.message : error
      )
    }
  }

  async function ensureStartupAuthenticated(): Promise<StartupAuthResult> {
    try {
      const res = await authApi.validateSession()
      const resRow = asRecord(res)
      const dataRow = asRecord(res?.data)
      if (
        res?.success === true
        || resRow.valid === true
        || dataRow.valid === true
      ) {
        clearHostPackSkippedSession()
        // P0 优化3：Market token 同步与账户资料刷新彼此无依赖，并行执行节省 ~1RT
        const marketPromise = syncMarketTokensFromSession()
        const profilePromise = import('@/stores/accountProfile')
          .then((m) => m.useAccountProfileStore().refreshFromServer())
          .catch(() => { /* ignore */ })
        await Promise.all([marketPromise, profilePromise])
        let entitledModIds: string[] = []
        let accountUsername = ''
        try {
          entitledModIds = readEntitledModIdsFromAuthPayload(res)
          const data = res?.data && typeof res.data === 'object' && !Array.isArray(res.data)
            ? asRecord(res.data)
            : resRow
          const user = asRecord(data.user)
          accountUsername = asString(data.username || user.username).trim()
        } catch {
          /* ignore */
        }
        return { ok: true, entitledModIds, accountUsername }
      }
    } catch {
      // Fall through to the local login page.
    }
    dismissStartupSplashImmediate()
    const loc =
      typeof window !== 'undefined'
        ? {
            pathname: window.location.pathname,
            search: window.location.search,
            hash: window.location.hash,
          }
        : {}
    void router.replace(buildLoginLocation(loc))
    return { ok: false, entitledModIds: [] }
  }

  async function runEnterpriseStartupAuth(isPublicEntryRoute: () => boolean): Promise<boolean> {
    if (isPublicEntryRoute()) return true
    // P0 优化3：fetchProductSku 与 auth 校验互相无依赖，并行执行节省 ~1RT
    const skuPromise = fetchProductSku().catch(() => 'generic' as string)
    const authPromise = ensureStartupAuthenticated()
    const [sku, authResult] = await Promise.all([skuPromise, authPromise])
    if (!authResult.ok) return false
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
