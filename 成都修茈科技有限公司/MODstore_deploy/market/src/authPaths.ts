import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router'

export const XCAGI_DESKTOP_REGISTRATION_SOURCE = 'xcagi-desktop'

function firstQueryValue(raw: unknown): unknown {
  return Array.isArray(raw) ? raw[0] : raw
}

/**
 * 桌面端和 Web 端共用同一注册页。只接受固定来源值，禁止把任意回跳 URL
 * 从公开查询参数带入桌面端流程。
 */
export function isXcagiDesktopRegistration(
  route: Pick<RouteLocationNormalizedLoaded, 'query'>,
): boolean {
  return firstQueryValue(route.query.source) === XCAGI_DESKTOP_REGISTRATION_SOURCE
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
 * 新用户的唯一默认下一步是选择企业套餐。
 */
export const DEFAULT_POST_REGISTER: RouteLocationRaw = {
  name: 'plans',
  query: { plan: 'plan_enterprise' },
}

export function pickRegistrationNextFromRoute(
  route: Pick<RouteLocationNormalizedLoaded, 'query'>,
): RouteLocationRaw {
  const source = firstQueryValue(route.query.source)
  return {
    name: 'plans',
    query: {
      plan: 'plan_enterprise',
      ...(source === XCAGI_DESKTOP_REGISTRATION_SOURCE
        ? { source: XCAGI_DESKTOP_REGISTRATION_SOURCE }
        : {}),
    },
  }
}

export function pickRedirectFromRoute(
  route: Pick<RouteLocationNormalizedLoaded, 'query'>,
): RouteLocationRaw {
  const raw = firstQueryValue(route.query.redirect)
  if (typeof raw === 'string' && raw.length > 0) return safeRedirectPath(raw)
  return DEFAULT_POST_AUTH
}
