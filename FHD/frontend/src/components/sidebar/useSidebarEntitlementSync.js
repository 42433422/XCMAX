/**
 * 权益同步状态徽标：读取本地权益快照 + 下线兜底构造 + 「已更新」一次性提示
 * （拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useModsStore } from '@/stores/mods'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { primeCsrfCookie } from '@/api/core'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'

export function useSidebarEntitlementSync() {
  const accountProfileStore = useAccountProfileStore()
  const modsStore = useModsStore()
  const { modsForUi } = storeToRefs(modsStore)
  const { displayBrand } = storeToRefs(accountProfileStore)

  const entitlementSyncStatus = ref(null)
  const entitlementSyncStatusError = ref('')
  const entitlementSyncLoading = ref(false)
  const entitlementSyncNoticeUntil = ref(0)
  let entitlementSyncPollTimer = null
  let entitlementSyncNoticeTimer = null

  const shouldShowEntitlementSyncStatus = computed(() => {
    if (isAdminConsoleSpa()) return false
    if (!accountProfileStore.loaded) return false
    return Boolean(accountProfileStore.marketUserId || displayBrand.value)
  })

  const entitlementSyncHasFreshNotice = computed(() => entitlementSyncNoticeUntil.value > Date.now())

  const entitlementSyncStatusTone = computed(() => {
    if (entitlementSyncStatusError.value) return 'error'
    if (entitlementSyncLoading.value && !entitlementSyncStatus.value) return 'muted'
    if (entitlementSyncHasFreshNotice.value) return 'info'
    if (entitlementSyncStatus.value?.has_snapshot) return 'ok'
    return 'muted'
  })

  const entitlementSyncStatusText = computed(() => {
    if (!shouldShowEntitlementSyncStatus.value) return ''
    if (entitlementSyncStatusError.value) return '权益未同步'
    if (entitlementSyncLoading.value && !entitlementSyncStatus.value) return '权益同步中'
    if (entitlementSyncHasFreshNotice.value) return '权益已更新'
    if (entitlementSyncStatus.value?.has_snapshot) return '权益已同步'
    return ''
  })

  const entitlementSyncStatusTitle = computed(() => {
    if (entitlementSyncStatusError.value) return entitlementSyncStatusError.value
    const snap = entitlementSyncStatus.value?.snapshot || {}
    const profile = snap.profile || {}
    const mods = Array.isArray(snap.mod_ids) ? snap.mod_ids.join('、') : ''
    return [
      snap.username ? `账号 ${snap.username}` : '',
      profile.tier ? `等级 ${profile.tier}` : '',
      profile.industry_id ? `行业 ${profile.industry_id}` : '',
      mods ? `Mod ${mods}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
  })

  function entitlementSyncStorageKey() {
    const accountKey = accountProfileStore.marketUserId || accountProfileStore.impersonatingMarketUserId || displayBrand.value || 'current'
    return `xcagi_entitlements_seen_${accountKey}`
  }

  function accountEntitlementSignature() {
    return JSON.stringify({
      kind: accountProfileStore.accountKind || '',
      brand: displayBrand.value || '',
      marketUserId: accountProfileStore.marketUserId || '',
      tier: accountProfileStore.tier || '',
      accountTier: accountProfileStore.accountTier || '',
      budgetRange: accountProfileStore.budgetRange || '',
      membership: accountProfileStore.marketMembershipTier || '',
      industries: accountProfileStore.entitledIndustries || [],
    })
  }

  function fallbackEntitlementSyncStatus(updatedAtMs = 0) {
    return {
      has_snapshot: true,
      updated_at_ms: updatedAtMs,
      account: {
        market_user_id: accountProfileStore.marketUserId,
        username: displayBrand.value || '',
        account_kind: accountProfileStore.accountKind,
        market_is_enterprise: accountProfileStore.marketIsEnterprise,
        market_is_admin: accountProfileStore.marketIsAdmin,
      },
      snapshot: {
        market_user_id: accountProfileStore.marketUserId == null ? '' : String(accountProfileStore.marketUserId),
        username: displayBrand.value || '',
        is_admin: accountProfileStore.marketIsAdmin,
        is_enterprise: accountProfileStore.marketIsEnterprise,
        profile: {
          tier: accountProfileStore.tier || accountProfileStore.accountKind || '',
          account_tier: accountProfileStore.accountTier || '',
          budget_range: accountProfileStore.budgetRange || '',
          industry_id: (accountProfileStore.entitledIndustries || [])[0] || '',
          entitled_industries: accountProfileStore.entitledIndustries || [],
        },
        mod_ids: (modsForUi.value || []).map((m) => String(m.id || '')).filter(Boolean),
        meta: {
          updated_at_ms: updatedAtMs,
          target: 'account_profile',
          push_mode: 'pull_fallback',
        },
      },
    }
  }

  function markEntitlementSyncNotice(updatedAtMs) {
    if (!updatedAtMs) return
    const isFresh = Math.abs(Date.now() - updatedAtMs) <= 24 * 60 * 60 * 1000
    try {
      localStorage.setItem(entitlementSyncStorageKey(), String(updatedAtMs))
    } catch {
      /* ignore storage failures */
    }
    if (!isFresh) return
    entitlementSyncNoticeUntil.value = Date.now() + 45_000
    if (entitlementSyncNoticeTimer != null) {
      window.clearTimeout(entitlementSyncNoticeTimer)
    }
    entitlementSyncNoticeTimer = window.setTimeout(() => {
      entitlementSyncNoticeUntil.value = 0
      entitlementSyncNoticeTimer = null
    }, 45_000)
  }

  async function refreshEntitlementSyncStatus(options = {}) {
    if (!shouldShowEntitlementSyncStatus.value || entitlementSyncLoading.value) return
    entitlementSyncLoading.value = true
    entitlementSyncStatusError.value = ''
    const beforeSignature = accountEntitlementSignature()
    try {
      if (options.pull) {
        await primeCsrfCookie()
        await xcmaxAdminApi.pullSync()
        await accountProfileStore.refreshFromServer()
      }
      let statusData = null
      try {
        const res = await xcmaxAdminApi.getCurrentEntitlementsSyncStatus()
        statusData = res?.data || null
      } catch {
        const afterSignature = accountEntitlementSignature()
        const changedAtMs = beforeSignature && afterSignature && beforeSignature !== afterSignature ? Date.now() : 0
        statusData = fallbackEntitlementSyncStatus(changedAtMs)
        if (changedAtMs > 0) {
          markEntitlementSyncNotice(changedAtMs)
          window.dispatchEvent(
            new CustomEvent('xcagi:account-entitlements-updated', {
              detail: { updated_at_ms: changedAtMs, snapshot: statusData.snapshot },
            }),
          )
        }
      }
      entitlementSyncStatus.value = statusData
      const updatedAtMs = Number(statusData?.updated_at_ms || 0)
      if (updatedAtMs > 0) {
        let seen = ''
        try {
          seen = localStorage.getItem(entitlementSyncStorageKey()) || ''
        } catch {
          seen = ''
        }
        if (String(updatedAtMs) !== seen) {
          markEntitlementSyncNotice(updatedAtMs)
          window.dispatchEvent(
            new CustomEvent('xcagi:account-entitlements-updated', {
              detail: { updated_at_ms: updatedAtMs, snapshot: statusData?.snapshot || null },
            }),
          )
        }
      }
    } catch (e) {
      entitlementSyncStatusError.value = e instanceof Error ? e.message : String(e || '权益同步失败')
    } finally {
      entitlementSyncLoading.value = false
    }
  }

  function stopEntitlementSyncPolling() {
    if (entitlementSyncPollTimer != null) {
      window.clearInterval(entitlementSyncPollTimer)
      entitlementSyncPollTimer = null
    }
  }

  function startEntitlementSyncPolling() {
    if (!shouldShowEntitlementSyncStatus.value || entitlementSyncPollTimer != null) return
    // 权益快照由服务器主动推送到本机；侧边栏轮询只读本地快照。
    // 旧逻辑每 30 秒强制访问远端同步端口，离线部署会持续产生连接失败日志，
    // 同时把“本地状态读取”错误地变成了外网依赖。
    void refreshEntitlementSyncStatus()
    entitlementSyncPollTimer = window.setInterval(() => {
      void refreshEntitlementSyncStatus()
    }, 30_000)
  }

  function syncEntitlementSyncPolling() {
    if (shouldShowEntitlementSyncStatus.value) {
      startEntitlementSyncPolling()
    } else {
      stopEntitlementSyncPolling()
      entitlementSyncStatus.value = null
      entitlementSyncStatusError.value = ''
      entitlementSyncNoticeUntil.value = 0
    }
  }

  function clearEntitlementSyncNoticeTimer() {
    if (entitlementSyncNoticeTimer != null) {
      window.clearTimeout(entitlementSyncNoticeTimer)
      entitlementSyncNoticeTimer = null
    }
  }

  watch(shouldShowEntitlementSyncStatus, () => {
    syncEntitlementSyncPolling()
  })

  return {
    shouldShowEntitlementSyncStatus,
    entitlementSyncStatusTone,
    entitlementSyncStatusText,
    entitlementSyncStatusTitle,
    refreshEntitlementSyncStatus,
    stopEntitlementSyncPolling,
    syncEntitlementSyncPolling,
    clearEntitlementSyncNoticeTimer,
  }
}
