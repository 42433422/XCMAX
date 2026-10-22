export type LocationLike = {
  pathname?: string
  search?: string
  hash?: string
}

/** Remove only the current SPA mount prefix; callers still validate the target. */
export function stripAppBase(target: string, base = '/'): string {
  const prefix = base.replace(/\/+$/, '')
  if (!prefix || prefix === '/' || !prefix.startsWith('/') || prefix.startsWith('//')) return target
  if (target === prefix) return '/'
  if (target.startsWith(`${prefix}/`)) return target.slice(prefix.length)
  if (target.startsWith(`${prefix}?`) || target.startsWith(`${prefix}#`)) return `/${target.slice(prefix.length)}`
  return target
}

/**
 * 构造登录回跳路径：避免把「当前已在 /login?redirect=…」整串再次嵌套进 redirect。
 */
export function safeRedirectFromLocation(loc: LocationLike = {}, base = '/'): string {
  const path = stripAppBase(loc.pathname || '/', base)
  const search = loc.search || ''
  const hash = loc.hash || ''

  if (path !== '/login' && !path.endsWith('/login')) {
    return `${path}${search}${hash}`
  }

  try {
    const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : '')
    let inner = params.get('redirect')
    if (!inner || typeof inner !== 'string') return '/'
    inner = stripAppBase(decodeURIComponent(inner.trim()), base)
    for (let i = 0; i < 5 && inner.startsWith('/login'); i++) {
      const q = inner.indexOf('?')
      if (q < 0) {
        inner = '/'
        break
      }
      const nested = new URLSearchParams(inner.slice(q + 1)).get('redirect')
      inner = nested ? stripAppBase(decodeURIComponent(nested.trim()), base) : '/'
    }
    const cleanPath = inner.split('?')[0].split('#')[0]
    if (cleanPath.startsWith('/') && !cleanPath.startsWith('//') && !cleanPath.startsWith('/login')) {
      return cleanPath
    }
  } catch {
    /* ignore */
  }
  return '/'
}

export function normalizeLoginRedirect(redirect: string, base = '/'): string {
  redirect = stripAppBase(redirect, base)
  if (!redirect.startsWith('/') || redirect.startsWith('//') || redirect.includes('\\') || Array.from(redirect).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) || redirect.startsWith('/login')) {
    return '/'
  }
  return redirect
}

export function buildLoginLocation(loc: LocationLike = {}, base = '/') {
  const redirect = normalizeLoginRedirect(safeRedirectFromLocation(loc, base))
  return {
    name: 'login' as const,
    query: { redirect },
  }
}
