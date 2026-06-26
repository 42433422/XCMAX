import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, setTokens as apiSetTokens } from '../api'

const TOKEN_KEY = 'modstore_token'
const REFRESH_TOKEN_KEY = 'modstore_refresh_token'

export interface AuthUser {
  id?: number | string
  username?: string
  email?: string
  is_admin?: boolean
  [key: string]: unknown
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<AuthUser | null>(null)
  const currentMode = ref<'client' | 'admin'>('client')
  /** 已成功用 /api/auth/me 校验过的 token；用于路由守卫高频访问时避免重复请求。 */
  const lastValidatedToken = ref('')
  const lastMeFetchedAt = ref(0)
  /** 15 秒内对同一 token 不重复请求 /api/auth/me。 */
  const ME_STALE_MS = 15_000

  const token = computed(() => getToken())
  const isLoggedIn = computed(() => Boolean(user.value && getToken()))
  const isAdmin = computed(() => user.value?.is_admin === true)

  function getToken(): string {
    const raw = localStorage.getItem(TOKEN_KEY)
    if (!raw || raw === 'undefined' || raw === 'null') return ''
    // P0-4：token 过期预检，避免使用失效 token 发请求
    if (isTokenExpired(raw)) {
      localStorage.removeItem(TOKEN_KEY)
      return ''
    }
    return raw
  }

  /** P0-4：解码 JWT payload 检查 exp 是否过期（不验证签名，仅客户端预检）。 */
  function isTokenExpired(token: string): boolean {
    try {
      const parts = token.split('.')
      if (parts.length !== 3) return false
      const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
      if (typeof payload.exp !== 'number') return false
      return Date.now() >= payload.exp * 1000 - 30_000
    } catch {
      return false
    }
  }

  function setToken(value: string): void {
    if (value) {
      localStorage.setItem(TOKEN_KEY, value)
    } else {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(REFRESH_TOKEN_KEY)
    }
  }

  /** P0-4：登录/注册成功后存储 access + refresh token（后端响应 web_tokens 字段）。 */
  function storeTokens(accessToken: string, refreshToken?: string): void {
    apiSetTokens(accessToken, refreshToken)
    lastValidatedToken.value = ''
  }

  function hasToken(): boolean {
    return Boolean(getToken())
  }

  function resetSession(): void {
    user.value = null
    lastValidatedToken.value = ''
    lastMeFetchedAt.value = 0
  }

  /**
   * 获取或刷新当前登录用户。
   * - 无 token：清空 user，返回 null。
   * - 有 token 且最近 15 秒内已校验过：直接返回 cache。
   * - 否则调用 /api/auth/me；失败则清 token+session。
   */
  async function refreshSession(force = false): Promise<AuthUser | null> {
    const t = getToken()
    if (!t) {
      resetSession()
      return null
    }
    const now = Date.now()
    if (
      !force &&
      t === lastValidatedToken.value &&
      user.value &&
      now - lastMeFetchedAt.value < ME_STALE_MS
    ) {
      return user.value
    }
    try {
      const me = (await api.me()) as AuthUser
      user.value = me
      lastValidatedToken.value = t
      lastMeFetchedAt.value = Date.now()
      return user.value
    } catch {
      setToken('')
      resetSession()
      return null
    }
  }

  /** 应用启动时调用：若有 token 则尝试拉一次用户信息，便于刷新页面后保留登录态。 */
  async function init(): Promise<void> {
    if (getToken()) {
      await refreshSession(true)
    }
  }

  function logout(): void {
    setToken('')
    resetSession()
    currentMode.value = 'client'
  }

  function setMode(mode: 'client' | 'admin'): void {
    currentMode.value = mode
  }

  return {
    user,
    currentMode,
    token,
    isLoggedIn,
    isAdmin,
    hasToken,
    getToken,
    setToken,
    storeTokens,
    init,
    refreshSession,
    logout,
    setMode,
  }
})
