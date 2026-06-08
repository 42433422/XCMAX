import type { Router } from 'vue-router'
import { DEFAULT_POST_AUTH, safeRedirectPath } from '../authPaths'
import {
  applyFhdMarketToken,
  extractFhdMarketTokenFromRoute,
  fhdHandoffNeedsStrip,
  FHD_MARKET_QUERY_KEY,
} from '../infrastructure/storage/fhdMarketHandoff'
import { useAuthStore } from '../stores/auth'

export function installAuthGuards(router: Router): void {
  router.beforeEach(async (to) => {
    const matched = Array.isArray(to.matched) ? to.matched : []
    const requiresAuth = matched.some((record) => record.meta.auth) || Boolean(to.meta.auth)
    const requiresAdmin = matched.some((record) => record.meta.admin) || Boolean(to.meta.admin)

    const auth = useAuthStore()
    const handoffToken = extractFhdMarketTokenFromRoute(to)
    if (handoffToken) {
      applyFhdMarketToken(handoffToken)
      const userAfterHandoff = await auth.refreshSession(true)
      // 仅在 /api/auth/me 校验通过后再剥掉 URL 中的令牌，避免失败时地址栏仍可读但至少不把「假登录」写进历史。
      if (userAfterHandoff && fhdHandoffNeedsStrip(to)) {
        const query = { ...to.query } as Record<string, string | string[] | undefined>
        delete query[FHD_MARKET_QUERY_KEY]
        return {
          path: to.path,
          query,
          hash: '',
          replace: true,
        }
      }
    }

    if ((String(to.name) === 'home' || String(to.name) === 'about') && to.hash === '#ai-market') {
      return { name: 'ai-store', replace: true }
    }

    const guestNames = new Set(['login', 'login-email', 'register', 'forgot-password'])
    if (guestNames.has(String(to.name))) {
      if (auth.hasToken()) {
        const user = await auth.refreshSession()
        if (user) {
          const q = to.query.redirect
          const raw = Array.isArray(q) ? q[0] : q
          if (typeof raw === 'string' && raw.length > 0) {
            return safeRedirectPath(raw)
          }
          return DEFAULT_POST_AUTH
        }
      }
    }

    if (requiresAuth && !auth.hasToken()) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    if (requiresAdmin) {
      const user = await auth.refreshSession()
      if (!user) return { name: 'login' }
      if (!user?.is_admin) return { name: 'home' }
    }
    return undefined
  })
}
