import { computed, ref, watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import type { AccountKind } from '@/api/auth'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { isDesktopShell } from '@/utils/desktopShell'

/**
 * LoginView 的全部响应式状态与基础计算属性（与拆分前逐项对应）。
 * 各行为 composable 共享同一组 ref，保证与拆分前同一实例。
 */
export function useLoginViewState(route: RouteLocationNormalizedLoaded) {
  const username = ref('')
  const accountKind = ref<AccountKind>(isAdminConsoleSpa() ? 'admin' : 'enterprise')
  const password = ref('')
  const showPassword = ref(false)
  const loading = ref(false)
  /** 桌面壳：隐藏「管理员登录」入口（管理端仅网页 SSOT） */
  const showAdminEntry = computed(() => !isAdminConsoleSpa() && !isDesktopShell())
  const errorMessage = ref('')
  const altLoginHint = ref('')
  const oidcEnabled = ref(false)
  const loginMode = ref<'password' | 'phone' | 'qr'>('password')
  const phone = ref('')
  const smsCode = ref('')
  const sendingCode = ref(false)
  const qrDataUrl = ref('')
  const qrPollTimer = ref<number | null>(null)
  const qrExpiresAt = ref(0)
  const qrId = ref('')
  const qrPollSecret = ref('')
  const usernameFocused = ref(false)
  const passwordFocused = ref(false)
  const rememberPassword = ref(false)
  const autoLogin = ref(false)

  watch(rememberPassword, (enabled) => {
    if (!enabled) autoLogin.value = false
  })

  watch(autoLogin, (enabled) => {
    if (enabled) rememberPassword.value = true
  })

  function peelNestedLoginRedirect(raw: string): string {
    let v = raw.trim()
    for (let i = 0; i < 5 && v.startsWith('/login'); i++) {
      const q = v.indexOf('?')
      if (q < 0) return '/'
      const nested = new URLSearchParams(v.slice(q + 1)).get('redirect')
      // URLSearchParams already decodes the nested value. Decoding it again
      // would turn an encoded '&' in onboarding's return path into a new key.
      v = nested ? nested.trim() : '/'
    }
    const pathOnly = v.split('?')[0].split('#')[0]
    return pathOnly === '/onboarding' ? v : pathOnly
  }

  const redirectPath = computed(() => {
    const raw = route.query.redirect
    const value = Array.isArray(raw) ? raw[0] : raw
    if (!value || typeof value !== 'string') return '/'
    let v = value.trim()
    try {
      if (!v.startsWith('/')) v = decodeURIComponent(v)
    } catch {
      /* keep */
    }
    v = peelNestedLoginRedirect(v)
    if (!v.startsWith('/') || v.startsWith('//') || v.startsWith('/login')) return '/'
    return v
  })

  const canSubmit = computed(() => {
    if (loading.value) return false
    if (loginMode.value === 'phone') {
      return phone.value.trim().length >= 5 && smsCode.value.trim().length >= 6
    }
    if (loginMode.value === 'qr') return false
    return username.value.trim().length > 0 && password.value.length > 0
  })

  const qrCountdown = computed(() => {
    const left = Math.max(0, qrExpiresAt.value - Math.floor(Date.now() / 1000))
    return left
  })

  const productSku = ref<string>('generic')
  const baseUrl = import.meta.env.BASE_URL
  const isEnterpriseEdition = computed(() => productSku.value === 'enterprise')

  return {
    username,
    accountKind,
    password,
    showPassword,
    loading,
    showAdminEntry,
    errorMessage,
    altLoginHint,
    oidcEnabled,
    loginMode,
    phone,
    smsCode,
    sendingCode,
    qrDataUrl,
    qrPollTimer,
    qrExpiresAt,
    qrId,
    qrPollSecret,
    usernameFocused,
    passwordFocused,
    rememberPassword,
    autoLogin,
    peelNestedLoginRedirect,
    redirectPath,
    canSubmit,
    qrCountdown,
    productSku,
    baseUrl,
    isEnterpriseEdition,
  }
}

export type LoginViewState = ReturnType<typeof useLoginViewState>
