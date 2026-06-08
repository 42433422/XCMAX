export type LocationLike = {
  pathname?: string
  search?: string
  hash?: string
}

/**
 * 构造登录回跳路径：避免把「当前已在 /login?redirect=…」整串再次嵌套进 redirect。
 */
export function safeRedirectFromLocation(loc: LocationLike = {}): string {
  const path = loc.pathname || '/'
  const search = loc.search || ''
  const hash = loc.hash || ''

  if (path !== '/login' && !path.endsWith('/login')) {
    return `${path}${search}${hash}`
  }

  try {
    const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : '')
    let inner = params.get('redirect')
    if (!inner || typeof inner !== 'string') return '/'
    inner = decodeURIComponent(inner.trim())
    for (let i = 0; i < 5 && inner.startsWith('/login'); i++) {
      const q = inner.indexOf('?')
      if (q < 0) {
        inner = '/'
        break
      }
      const nested = new URLSearchParams(inner.slice(q + 1)).get('redirect')
      inner = nested ? decodeURIComponent(nested.trim()) : '/'
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

export function normalizeLoginRedirect(redirect: string): string {
  if (!redirect.startsWith('/') || redirect.startsWith('//') || redirect.startsWith('/login')) {
    return '/'
  }
  return redirect
}

export function buildLoginLocation(loc: LocationLike = {}) {
  const redirect = normalizeLoginRedirect(safeRedirectFromLocation(loc))
  return {
    name: 'login' as const,
    query: { redirect },
  }
}
