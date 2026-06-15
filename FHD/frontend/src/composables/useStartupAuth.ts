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
        await syncMarketTokensFromSession()
        try {
          const { useAccountProfileStore } = await import('@/stores/accountProfile')
          await useAccountProfileStore().refreshFromServer()
        } catch {
          /* ignore */
        }
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
    let sku = 'generic'
    try {
      sku = await fetchProductSku()
    } catch {
      /* ignore */
    }
    const authResult = await ensureStartupAuthenticated()
    if (!authResult.ok) return false
    let sunbirdAccount = false
    try {
      const { isSunbirdAccountUsername } = await import('@/constants/accountModBinding')
      sunbirdAccount = isSunbirdAccountUsername(authResult.accountUsername)
    } catch {
      /* ignore */
    }
    if (!isEnterpriseEdition(sku) && !sunbirdAccount) return true
    try {
      await modsStore.initialize(true, {
        entitledModIds: authResult.entitledModIds,
        forceFromEntitlements: sunbirdAccount || authResult.entitledModIds.length > 0,
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
