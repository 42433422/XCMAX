import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router'

export function safeRedirectPath(raw: unknown): string {
  if (typeof raw !== 'string') return '/workbench/home'
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return '/workbench/home'

  const withoutBase = trimmed.startsWith('/market/')
    ? trimmed.slice('/market'.length)
    : trimmed === '/market'
      ? '/'
      : trimmed

  if (
    withoutBase === '/' ||
    withoutBase === '/index.html' ||
    withoutBase.startsWith('/login') ||
    /^\/(?:about|services|solutions|cases|case-edu|case-park|case-manufacture|news|honors|contact|baidu_verify_codeva-hVYlSoeYiP)\.html(?:[?#].*)?$/.test(
      withoutBase,
    )
  ) {
    return '/workbench/home'
  }
  return withoutBase
}

/**
 * 登录/注册成功后无 ``redirect`` 时的落地页。
 * 使用命名路由，保证在 ``https://xiu-ci.com/market/`` 等子路径（Vite ``base=/market/``）下解析正确。
 */
export const DEFAULT_POST_AUTH: RouteLocationRaw = { name: 'workbench-home' }

export function pickRedirectFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'query'>): RouteLocationRaw {
  const q = route.query.redirect
  const raw = Array.isArray(q) ? q[0] : q
  if (typeof raw === 'string' && raw.length > 0) return safeRedirectPath(raw)
  return DEFAULT_POST_AUTH
}
