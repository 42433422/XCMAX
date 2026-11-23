import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router'

function firstQueryValue(raw: unknown): unknown {
  return Array.isArray(raw) ? raw[0] : raw
}

export function accountLicensePlanId(raw: unknown): string | undefined {
  const plan = firstQueryValue(raw)
  return typeof plan === 'string' && ['saas-personal-free', 'saas-trial-30', 'saas-permanent-standard'].includes(plan) ? plan : undefined
}

export function xcagiRegistrationSource({ query }: Pick<RouteLocationNormalizedLoaded, 'query'>) {
  const source = firstQueryValue(query.source)
  return source === 'xcagi-desktop' || source === 'xcagi-mobile' ? source : undefined
}

export function safeRedirectPath(raw: unknown): string {
  if (typeof raw !== 'string') return '/workbench/home'
  const trimmed = raw.trim()
  if (!trimmed.startsWith('/') || trimmed.startsWith('//')) return '/workbench/home'
  if (trimmed === '/market') return '/'

  const withoutBase = trimmed.startsWith('/market/') ? trimmed.slice('/market'.length) : trimmed

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

/** 注册保留已选商品；无购买意图时先进入免费个人体验。 */
export function pickRegistrationNextFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'query'>): RouteLocationRaw {
  const redirect = safeRedirectPath(firstQueryValue(route.query.redirect))
  if (/^\/account-plans(?:[?#]|$)/.test(redirect)) return redirect
  if (redirect.startsWith('/plans?') && accountLicensePlanId(new URLSearchParams(redirect.slice(7).split('#')[0]).get('plan'))) return redirect
  const source = xcagiRegistrationSource(route)
  const plan = accountLicensePlanId(route.query.plan) || 'saas-personal-free'
  return { name: 'account-plans', query: { plan, ...(source ? { source } : {}) } }
}

export function pickRedirectFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'query'>): RouteLocationRaw {
  const raw = firstQueryValue(route.query.redirect)
  if (typeof raw === 'string' && raw.length > 0) return safeRedirectPath(raw)
  return xcagiRegistrationSource(route) ? pickRegistrationNextFromRoute(route) : DEFAULT_POST_AUTH
}
