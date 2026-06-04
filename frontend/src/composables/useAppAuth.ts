import { useRouter } from 'vue-router'
import { authApi } from '@/api/auth'

export function useAppAuth() {
  const router = useRouter()

  function safeRedirectFromLocation(): string {
    const path = window.location.pathname || '/'
    const search = window.location.search || ''
    const hash = window.location.hash || ''

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

  function buildLoginLocation() {
    let redirect = safeRedirectFromLocation()
    if (!redirect.startsWith('/') || redirect.startsWith('//') || redirect.startsWith('/login')) {
      redirect = '/'
    }
    return {
      name: 'login',
      query: { redirect },
    }
  }

  async function ensureAuthenticated(): Promise<boolean> {
    try {
      const res = await authApi.validateSession()
      if (res?.success === true || res?.valid === true || res?.data?.valid === true) return true
    } catch {
      // Fall through to the local login page.
    }
    void router.replace(buildLoginLocation())
    return false
  }

  return {
    safeRedirectFromLocation,
    buildLoginLocation,
    ensureAuthenticated,
  }
}
