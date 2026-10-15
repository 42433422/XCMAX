import type { Router } from 'vue-router'
import { authApi } from '@/api/auth'
import { applyMarketTokensAfterFhdLogin, LS_MARKET_ACCESS_TOKEN, LS_MARKET_REFRESH_TOKEN, LS_MARKET_USER_JSON } from '@/api/marketAccount'
import { invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { DESKTOP_ADMIN_FORBIDDEN_MESSAGE, isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'
import { ADMIN_OPERATOR_HOME_ROUTE } from '@/constants/adminOperatorNav'
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate'
import type { LoginViewState } from './useLoginViewState'

let latestLoginAttempt = 0
export function useLoginViewSession(state: LoginViewState, options: { router: Router }) {
  const { username, phone, errorMessage, isEnterpriseEdition, redirectPath } = state
  const { router } = options
  const accountProfileStore = useAccountProfileStore()

  async function completeLoginSuccess(raw: Record<string, unknown>) {
    clearHostPackSkippedSession()
    const attempt = ++latestLoginAttempt
    const hydration = accountProfileStore.applyFromLoginPayload(raw)
    const epoch = productReadAccountEpoch.value
    const currentAttempt = () => attempt === latestLoginAttempt && epoch === productReadAccountEpoch.value
    try {
      await hydration
    } catch {
      if (!currentAttempt()) return
      // Only discard this attempt's client bootstrap. A remote logout could
      // arrive after a retry and clear its new cookie. Router readiness gates
      // still require strict hydration if the authenticated cookie survives.
      invalidateEnterpriseSessionCache()
      accountProfileStore.clear(false)
      try {
        for (const key of [LS_MARKET_ACCESS_TOKEN, LS_MARKET_REFRESH_TOKEN, LS_MARKET_USER_JSON]) localStorage.removeItem(key)
      } catch { /* private mode */ }
      errorMessage.value = '工作空间资料加载失败，请检查网络后重新登录。'
      return
    }
    if (!currentAttempt()) return
    // SSOT：桌面壳禁止管理员会话（派生 account_kind=admin 时拒入）。
    // 管理端 SPA（:5011）本身就是网页运维台，不得套用桌面禁令。
    if (!isAdminConsoleSpa() && isDesktopShell() && accountProfileStore.isAdminAccount) {
      try {
        await authApi.logout().catch(() => undefined)
      } catch {
        /* ignore */
      }
      errorMessage.value = DESKTOP_ADMIN_FORBIDDEN_MESSAGE
      return
    }
    const loginUser = raw?.data && typeof raw.data === 'object' && !Array.isArray(raw.data) ? (raw.data as Record<string, unknown>) : raw
    const accountUsername = String(loginUser?.username || username.value || phone.value || '').trim()
    await router.replace(
      isAdminConsoleSpa() && (redirectPath.value === '/' || !redirectPath.value) ? `/${ADMIN_OPERATOR_HOME_ROUTE}` : redirectPath.value,
    )
    if (!currentAttempt()) return
    // The login payload does not include effective RBAC permissions.
    void accountProfileStore.refreshFromServer()

    // Token handoff and MOD discovery are optional post-login bootstrap work.
    // They must never hold the login button in "正在登录" or delay the first
    // usable ERP screen when the market/MOD service is slow or offline.
    void applyMarketTokensAfterFhdLogin(raw).catch((marketErr) => {
      console.warn('[Login] market token handoff after auth:', marketErr)
    })
    if (isEnterpriseEdition.value) {
      void (async () => {
        try {
          const { readEntitledModIdsFromAuthPayload, useModsStore } = await import('@/stores/mods')
          if (!currentAttempt()) return
          const entitled = readEntitledModIdsFromAuthPayload(raw)
          await useModsStore().initialize(true, {
            entitledModIds: entitled,
            forceFromEntitlements: entitled.length > 0,
            accountUsername,
          })
        } catch (modErr) {
          console.warn('[Login] mods refresh after auth:', modErr)
        }
      })()
    }
  }

  return { completeLoginSuccess }
}
