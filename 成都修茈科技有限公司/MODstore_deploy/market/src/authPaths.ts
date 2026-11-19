import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router'

function firstQueryValue(raw: unknown): unknown {
  return Array.isArray(raw) ? raw[0] : raw
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

/**
 * 注册只完成账号开立，不代表已获得产品权益。
 * 新用户的唯一默认下一步是选择 XCAGI 账号授权；VIP/SVIP 额度会员不是账号权限。
 */
const DEFAULT_POST_REGISTER = {
  name: 'account-plans',
  query: { plan: 'saas-trial-30' },
}

export function pickRegistrationNextFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'query'>): RouteLocationRaw {
  const source = xcagiRegistrationSource(route)
  return source
    ? { ...DEFAULT_POST_REGISTER, query: { ...DEFAULT_POST_REGISTER.query, source } }
    : DEFAULT_POST_REGISTER
}

export function pickRedirectFromRoute(route: Pick<RouteLocationNormalizedLoaded, 'query'>): RouteLocationRaw {
  const raw = firstQueryValue(route.query.redirect)
  if (typeof raw === 'string' && raw.length > 0) return safeRedirectPath(raw)
  return xcagiRegistrationSource(route) ? pickRegistrationNextFromRoute(route) : DEFAULT_POST_AUTH
}
