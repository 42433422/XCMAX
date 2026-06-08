import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, clearAuthTokens } from '../api'
import { ApiError } from '../infrastructure/http/client'
import { ACCESS_TOKEN_KEY, getAccessToken } from '../infrastructure/storage/tokenStore'
import { buildLevelProfileDict, normalizeMeResponse } from '../domain/accountLevel'
import type { CurrentUser } from '../domain/auth/types'

function displayName(user: CurrentUser | null | undefined): string {
  const username = typeof user?.username === 'string' ? user.username.trim() : ''
  const email = typeof user?.email === 'string' ? user.email.trim() : ''
  return username || (email ? email.split('@')[0] || email : '')
}

export interface MembershipState {
  /** 与后端 _membership_meta() 一致：free / vip / vip_plus / svip1..svip8 */
  tier: string
  /** 展示用文案，例如 "VIP" / "SVIP3" / "普通用户" */
  label: string
  /** 是否为付费会员（任何 tier !== "free"） */
  is_member?: boolean
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<CurrentUser | null>(null)
  const currentMode = ref<'client' | 'admin'>('client')
  const lastValidatedToken = ref('')
  /** 上次成功拉取 /api/auth/me 的时间，用于在路由频繁切换时避免对同一 token 永久复用陈旧的 user（例如支付后经验已入账） */
  const lastMeFetchedAt = ref(0)
  const ME_STALE_MS = 15_000
  const membership = ref<MembershipState | null>(null)
  /** 最近一次拉取 /api/payment/my-plan 失败（与「未开通会员」区分） */
  const membershipFetchFailed = ref(false)
  const isLoggedIn = computed(() => Boolean(user.value && getAccessToken()))
  const isAdmin = computed(() => user.value?.is_admin === true)
  const username = computed(() => displayName(user.value))

  const ADMIN_DIGEST_UNLOCK_KEY = 'modstore_admin_digest_unlock_expires'
  const adminDigestUnlockExpires = ref<string>(
    (typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(ADMIN_DIGEST_UNLOCK_KEY) : '') || '',
  )
  const adminUiUnlocked = computed(() => {
    const exp = adminDigestUnlockExpires.value
    if (!exp) return false
    const t = Date.parse(exp)
    return Number.isFinite(t) && Date.now() < t
  })
  function setAdminDigestUnlock(expiresIso: string): void {
    adminDigestUnlockExpires.value = expiresIso || ''
    if (typeof sessionStorage !== 'undefined') {
      if (expiresIso) sessionStorage.setItem(ADMIN_DIGEST_UNLOCK_KEY, expiresIso)
      else sessionStorage.removeItem(ADMIN_DIGEST_UNLOCK_KEY)
    }
  }
  function clearAdminDigestUnlock(): void {
    setAdminDigestUnlock('')
  }
  /** 当前会员档位标识（free / vip / vip_plus / svip1..svip8）。未登录或加载前为 "" */
  const membershipTier = computed(() => {
    const t = String(membership.value?.tier || '').trim().toLowerCase()
    return t || ''
  })
  function parseLevelProfile(profile: Record<string, unknown>) {
    const level = Number(profile.level) || 1
    const title = typeof profile.title === 'string' ? profile.title : ''
    const exp = Number(profile.experience) || 0
    const currentMin = Number(profile.current_level_min_exp) || 0
    const nextMinRaw = profile.next_level_min_exp
    const nextMin = nextMinRaw === null || nextMinRaw === undefined ? null : Number(nextMinRaw)
    const progress = Math.max(0, Math.min(1, Number(profile.progress) || 0))
    return { level, title, experience: exp, currentLevelMinExp: currentMin, nextLevelMinExp: nextMin, progress }
  }

  const levelProfile = computed(() => {
    if (!user.value) return null
    let profile = user.value.level_profile
    if (!profile || typeof profile !== 'object') {
      const exp = Number(user.value.experience) || 0
      profile = buildLevelProfileDict(exp)
    }
    return parseLevelProfile(profile as Record<string, unknown>)
  })

  function resetSession(): void {
    user.value = null
    membership.value = null
    membershipFetchFailed.value = false
    lastValidatedToken.value = ''
    lastMeFetchedAt.value = 0
  }

  async function refreshMembership(): Promise<void> {
    if (!getAccessToken()) {
      membership.value = null
      membershipFetchFailed.value = false
      return
    }
    try {
      const r: any = await api.paymentMyPlan()
      membershipFetchFailed.value = false
      const m = r?.membership && typeof r.membership === 'object' ? r.membership : null
      if (m && typeof m.tier === 'string') {
        membership.value = {
          tier: String(m.tier),
          label: String(m.label || ''),
          is_member: Boolean(m.is_member),
        }
      } else {
        membership.value = { tier: 'free', label: '普通用户', is_member: false }
      }
    } catch {
      membershipFetchFailed.value = true
      membership.value = null
    }
  }

  async function refreshSession(force = false): Promise<any | null> {
    const token = getAccessToken()
    if (!token) {
      resetSession()
      return null
    }
    const now = Date.now()
    if (
      !force &&
      token === lastValidatedToken.value &&
      user.value &&
      now - lastMeFetchedAt.value < ME_STALE_MS
    ) {
      return user.value
    }
    try {
      const raw = await api.me()
      const me = normalizeMeResponse(raw)
      user.value = me
      lastValidatedToken.value = token
      lastMeFetchedAt.value = Date.now()
      // 拿到会员档位用于导航栏用户名颜色等场景；失败不阻塞登录态
      void refreshMembership()
      return user.value
    } catch (e) {
      // 网络抖动 / 502：勿清空本地 JWT，便于重试或稍后在登录页用 refresh。
      // 仅凭证被拒（401/403）时与登录过期一致，扔掉令牌。
      const authRejected = e instanceof ApiError && (e.status === 401 || e.status === 403)
      if (authRejected) {
        clearAuthTokens()
        resetSession()
      } else {
        user.value = null
        lastValidatedToken.value = ''
        lastMeFetchedAt.value = 0
      }
      return null
    }
  }

  async function loginWithPassword(usernameValue: string, password: string): Promise<any> {
    const res = await api.login(usernameValue, password)
    await refreshSession(true)
    return res
  }

  async function loginWithCode(email: string, code: string): Promise<any> {
    const res = await api.loginWithCode(email, code)
    await refreshSession(true)
    return res
  }

  function hasToken(): boolean {
    const raw = localStorage.getItem(ACCESS_TOKEN_KEY)
    return Boolean(raw && raw !== 'undefined' && raw !== 'null')
  }

  function logout(): void {
    clearAuthTokens()
    resetSession()
    clearAdminDigestUnlock()
    currentMode.value = 'client'
  }

  return {
    user,
    currentMode,
    isLoggedIn,
    isAdmin,
    username,
    levelProfile,
    membership,
    membershipFetchFailed,
    membershipTier,
    hasToken,
    refreshSession,
    refreshMembership,
    loginWithPassword,
    loginWithCode,
    logout,
    adminUiUnlocked,
    setAdminDigestUnlock,
    clearAdminDigestUnlock,
  }
})
