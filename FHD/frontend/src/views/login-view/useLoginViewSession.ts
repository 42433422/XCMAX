import type { Router } from 'vue-router'
import { authApi } from '@/api/auth'
import { applyMarketTokensAfterFhdLogin } from '@/api/marketAccount'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { DESKTOP_ADMIN_FORBIDDEN_MESSAGE, isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'
import { ADMIN_OPERATOR_HOME_ROUTE } from '@/constants/adminOperatorNav'
import { clearHostPackSkippedSession } from '@/utils/hostPackOnboardingGate'
import type { LoginViewState } from './useLoginViewState'

// LoginView 的登录成功会话处理（与拆分前逐字一致）
export function useLoginViewSession(state: LoginViewState, options: { router: Router }) {
  const { username, phone, errorMessage, isEnterpriseEdition, redirectPath } = state
  const { router } = options
  const accountProfileStore = useAccountProfileStore()

  async function completeLoginSuccess(raw: Record<string, unknown>) {
    clearHostPackSkippedSession()
    await accountProfileStore.applyFromLoginPayload(raw)
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
