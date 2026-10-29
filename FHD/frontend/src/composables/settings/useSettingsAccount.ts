import { ref, computed, getCurrentScope, onScopeDispose } from 'vue'
import { productReadAccountEpoch } from '@/utils/productReadAccountScope'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { authApi, type User } from '@/api/auth'
import { LS_MARKET_USER_JSON } from '@/api/marketAccount'
import { buildFullApiUrl } from '@/api/core'
import { useAccountProfileStore } from '@/stores/accountProfile'
import adminAuditApi, { type AuditLogEntry } from '@/api/adminAudit'
import { appAlert, appConfirm } from '@/utils/appDialog'
import { errorMessage } from './utils'
import { readValid, invalidateEnterpriseSessionCache } from '@/utils/authSessionCache'

export function useSettingsAccount() {
  const { t } = useI18n()
  const accountProfileStore = useAccountProfileStore()
  const router = useRouter()
  const route = useRoute()

  const localUser = ref<User | null>(null)
  const sessionValid = ref(false)
  const accountLoading = ref(true)
  const logoutLoading = ref(false)
  const accountError = ref(false)
  let accountEpoch = 0
  let accountRequest: Promise<void> | null = null
  if (getCurrentScope()) onScopeDispose(() => { ++accountEpoch; accountRequest = null })
  const companyBrandDraft = ref('')
  const companyBrandSaving = ref(false)
  const avatarInputRef = ref<HTMLInputElement | null>(null)
  const avatarUploading = ref(false)
  const avatarCacheBust = ref(0)
  const profileDisplayNameDraft = ref('')
  const profileEmailDraft = ref('')
  const profileSaving = ref(false)

  function unwrapUserFromMe(res: unknown): User | null {
    if (!res || typeof res !== 'object') return null
    const o = res as Record<string, unknown>
    const data = o.data as Record<string, unknown> | undefined
    const u = (data?.user ?? o.user) as User | undefined
    if (!u || typeof u !== 'object') return null
    const username = String(u.username || '').trim()
    return username ? u : null
  }

  function readMarketUserFromStorage(): User | null {
    try {
      const raw = window.localStorage.getItem(LS_MARKET_USER_JSON)
      if (!raw) return null
      const u = JSON.parse(raw) as Record<string, unknown>
      const username = String(u.username || '').trim()
      if (!username) return null
      return {
        id: Number(u.id) || 0,
        username,
        display_name: String(u.display_name || username).trim() || username,
        email: String(u.email || '').trim(),
        role: 'user',
        is_active: true,
      }
    } catch {
      return null
    }
  }

  function userFromSessionValidatePayload(res: unknown): User | null {
    if (!res || typeof res !== 'object') return null
    const o = res as Record<string, unknown>
    const data = o.data as Record<string, unknown> | undefined
    const username = String(data?.username || '').trim()
    if (!username) return readMarketUserFromStorage()
    const uid = data?.user_id
    return {
      id: uid != null ? Number(uid) : 0,
      username,
      display_name: username,
      email: '',
      role: 'user',
      is_active: true,
    }
  }

  function applyAccountMetaFromAuthPayload(res: unknown) {
    if (!res || typeof res !== 'object') return
    const o = res as Record<string, unknown>
    const base = o.data && typeof o.data === 'object' && !Array.isArray(o.data) ? (o.data as Record<string, unknown>) : {}
    void accountProfileStore.applyFromMeData({
      ...base,
      account_kind: o.account_kind ?? base.account_kind,
      company_brand: o.company_brand ?? base.company_brand,
      market_is_admin: o.market_is_admin ?? base.market_is_admin,
      market_is_enterprise: o.market_is_enterprise ?? base.market_is_enterprise,
      impersonating_market_user_id: o.impersonating_market_user_id ?? base.impersonating_market_user_id,
      impersonating_username: o.impersonating_username ?? base.impersonating_username,
    }).catch(() => undefined)
  }

  const isLoggedIn = computed(() => Boolean(localUser.value) || sessionValid.value)

  const isLocalAdmin = computed(() => {
    const role = String(localUser.value?.role || '').toLowerCase()
    return role === 'admin' || role === 'superadmin'
  })

  const auditLogsLoading = ref(false)
  const auditLogs = ref<AuditLogEntry[]>([])
  const auditLogsTotal = ref(0)
  const auditLogsError = ref('')

  async function loadAuditLogs() {
    if (!isLocalAdmin.value) return
    auditLogsLoading.value = true
    auditLogsError.value = ''
    try {
      const res = await adminAuditApi.list(30, 0)
      auditLogs.value = res?.data?.items || []
      auditLogsTotal.value = res?.data?.total || 0
    } catch (e: unknown) {
      auditLogsError.value = errorMessage(e, t('settings.auditLoadFailed'))
    } finally {
      auditLogsLoading.value = false
    }
  }

  function downloadAuditCsv() {
    window.open(adminAuditApi.csvDownloadUrl(500), '_blank', 'noopener,noreferrer')
  }

  function syncProfileDraftsFromUser(u: User | null) {
    if (!u) {
      profileDisplayNameDraft.value = ''
      profileEmailDraft.value = ''
      return
    }
    profileDisplayNameDraft.value = String(u.display_name || u.username || '').trim()
    profileEmailDraft.value = String(u.email || '').trim()
  }

  function loadLocalUser(): Promise<void> {
    if (logoutLoading.value) return Promise.resolve()
    if (accountRequest) return accountRequest
    const epoch = ++accountEpoch
    const scope = productReadAccountEpoch.value
    const isCurrent = () => epoch === accountEpoch && scope === productReadAccountEpoch.value
    accountLoading.value = true
    accountError.value = false
    accountRequest = (async () => {
      try {
        let payload: unknown
        let user: User | null = null
        try {
          payload = await authApi.getCurrentUser()
          user = unwrapUserFromMe(payload)
        } catch { /* Session validation distinguishes missing profile from logout. */ }
        if (!isCurrent()) return
        if (!user) {
          payload = await authApi.validateSession()
          if (!isCurrent()) return
          sessionValid.value = readValid(payload)
          user = sessionValid.value ? userFromSessionValidatePayload(payload) : null
        } else {
          sessionValid.value = true
        }
        localUser.value = user
        if (sessionValid.value) {
          applyAccountMetaFromAuthPayload(payload)
          companyBrandDraft.value = accountProfileStore.companyBrand || ''
        }
        if (!sessionValid.value) { invalidateEnterpriseSessionCache(); accountProfileStore.clear() }
        syncProfileDraftsFromUser(user)
      } catch (error) {
        if (!isCurrent()) return
        const status = (error as { status?: number } | null)?.status
        if (status === 401 || status === 403) {
          localUser.value = null
          sessionValid.value = false
          invalidateEnterpriseSessionCache()
          accountProfileStore.clear()
          syncProfileDraftsFromUser(null)
        } else accountError.value = true
      } finally {
        if (epoch === accountEpoch) {
          accountLoading.value = false
          accountRequest = null
        }
      }
    })()
    return accountRequest
  }

  const profileBrandTitle = computed(() => {
    const brand = String(accountProfileStore.displayBrand || '').trim()
    if (brand) return brand
    const u = localUser.value
    if (!u) return t(accountLoading.value ? 'settings.accountChecking' : accountError.value ? 'settings.accountUnavailable' : sessionValid.value ? 'settings.user' : 'settings.notLoggedIn')
    const name = String(u.display_name || u.username || '').trim()
    return name || t('settings.user')
  })

  const profileSubline = computed(() => {
    const u = localUser.value
    if (!u) return t(accountLoading.value ? 'settings.accountChecking' : accountError.value ? 'settings.accountUnavailable' : sessionValid.value ? 'settings.marketAccount' : 'settings.loginSyncHint')
    const username = String(u.username || '').trim()
    const brand = String(accountProfileStore.displayBrand || '').trim()
    if (brand) {
      const display = String(u.display_name || '').trim()
      if (display && display !== brand) return `${username} · ${display}`
      return username || t('settings.marketAccount')
    }
    const display = String(u.display_name || '').trim()
    if (display && username && display !== username) return username
    if (u.id != null) return `ID ${u.id}`
    return username
  })

  const showCompanyBrandEditor = computed(() => accountProfileStore.accountKind === 'enterprise')

  const companyBrandDirty = computed(() => {
    const draft = companyBrandDraft.value.trim()
    const current = String(accountProfileStore.companyBrand || '').trim()
    return draft !== current
  })

  async function saveCompanyBrand() {
    companyBrandSaving.value = true
    try {
      const brand = companyBrandDraft.value.trim()
      const res = await authApi.updateCompanyBrand(brand)
      const raw = res as Record<string, unknown>
      if (raw?.success === false) {
        throw new Error(String(raw.message || t('settings.saveFailed')))
      }
      accountProfileStore.companyBrand = brand
      await accountProfileStore.refreshFromServer()
      companyBrandDraft.value = accountProfileStore.companyBrand || brand
      await appAlert(t('settings.companyBrandSaved'))
    } catch (e) {
      await appAlert(t('settings.saveFailedWithDetail', { detail: e instanceof Error ? e.message : String(e) }))
    } finally {
      companyBrandSaving.value = false
    }
  }

  const avatarInitial = computed(() => {
    if (!localUser.value) return ''
    const name = profileBrandTitle.value
    const ch = name.charAt(0)
    return ch ? ch.toUpperCase() : ''
  })

  const profileAvatarUrl = computed(() => {
    const u = localUser.value
    const local = String(u?.avatar_url || '').trim()
    if (local) {
      const base = local.startsWith('http') ? local : buildFullApiUrl(local)
      const sep = base.includes('?') ? '&' : '?'
      return `${base}${sep}v=${avatarCacheBust.value}`
    }
    try {
      const raw = window.localStorage.getItem(LS_MARKET_USER_JSON)
      if (!raw) return ''
      const market = JSON.parse(raw) as Record<string, unknown>
      const url = String(market.avatar_url || market.avatar || '').trim()
      return url.startsWith('http') ? url : ''
    } catch {
      return ''
    }
  })

  const profileHomeSummary = computed(() => {
    const name = profileDisplayNameDraft.value.trim() || localUser.value?.username || ''
    return name ? `${name} · ${t('settings.profileHomeSummary')}` : t('settings.profileHomeSummary')
  })

  const profileFormDirty = computed(() => {
    const u = localUser.value
    if (!u) return false
    const dn = profileDisplayNameDraft.value.trim()
    const em = profileEmailDraft.value.trim()
    const curDn = String(u.display_name || u.username || '').trim()
    const curEm = String(u.email || '').trim()
    return dn !== curDn || em !== curEm
  })

  function onAvatarClick() {
    if (!isLoggedIn.value || avatarUploading.value) return
    avatarInputRef.value?.click()
  }

  async function onAvatarFileChange(ev: Event) {
    const input = ev.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file || !isLoggedIn.value) return
    if (file.size > 4 * 1024 * 1024) {
      await appAlert(t('settings.avatarTooLarge'))
      return
    }
    avatarUploading.value = true
    try {
      const res = await authApi.uploadAvatar(file)
      const url = String(res?.data?.avatar_url || '/api/auth/avatar').trim()
      if (localUser.value) {
        localUser.value = { ...localUser.value, avatar_url: url || '/api/auth/avatar' }
      }
      avatarCacheBust.value = Date.now()
      await appAlert(t('settings.avatarUpdated'))
    } catch (e) {
      await appAlert(t('settings.avatarUploadFailed', { detail: e instanceof Error ? e.message : String(e) }))
    } finally {
      avatarUploading.value = false
    }
  }

  async function saveProfile() {
    if (!localUser.value || !profileFormDirty.value) return
    profileSaving.value = true
    try {
      const res = await authApi.updateProfile({
        display_name: profileDisplayNameDraft.value.trim(),
        email: profileEmailDraft.value.trim(),
      })
      const updated = res?.data?.user
      if (updated && localUser.value) {
        localUser.value = { ...localUser.value, ...updated }
        syncProfileDraftsFromUser(localUser.value)
      }
      await appAlert(t('settings.profileSaved'))
    } catch (e) {
      await appAlert(t('settings.saveFailedWithDetail', { detail: e instanceof Error ? e.message : String(e) }))
    } finally {
      profileSaving.value = false
    }
  }

  const loginRoute = computed(() => ({
    name: 'login' as const,
    query: { redirect: route.fullPath },
  }))

  async function onLogout() {
    if (logoutLoading.value) return
    if (!(await appConfirm(t('settings.logoutConfirm'), { danger: true }))) return
    if (logoutLoading.value) return
    logoutLoading.value = true
    ++accountEpoch
    accountRequest = null
    accountLoading.value = false
    try {
      await authApi.logout()
      accountProfileStore.clear()
      localUser.value = null
      sessionValid.value = false
      await router.replace({ name: 'login', query: { redirect: '/' } })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      await appAlert(t('settings.logoutFailed', { detail: msg }))
    } finally {
      logoutLoading.value = false
    }
  }

  return {
    localUser,
    sessionValid,
    accountLoading,
    accountError,
    logoutLoading,
    companyBrandDraft,
    companyBrandSaving,
    avatarInputRef,
    avatarUploading,
    profileDisplayNameDraft,
    profileEmailDraft,
    profileSaving,
    isLoggedIn,
    isLocalAdmin,
    auditLogsLoading,
    auditLogs,
    auditLogsTotal,
    auditLogsError,
    profileBrandTitle,
    profileSubline,
    showCompanyBrandEditor,
    companyBrandDirty,
    avatarInitial,
    profileAvatarUrl,
    profileHomeSummary,
    profileFormDirty,
    loginRoute,
    loadAuditLogs,
    downloadAuditCsv,
    syncProfileDraftsFromUser,
    loadLocalUser,
    saveCompanyBrand,
    onAvatarClick,
    onAvatarFileChange,
    saveProfile,
    onLogout,
  }
}
