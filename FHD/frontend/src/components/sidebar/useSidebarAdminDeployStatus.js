/**
 * 管理端部署状态徽标：轮询 xcmaxAdminApi.checkDeployUpdates 并派生 tone/text/title
 * （拆分自 components/Sidebar.vue，行为保持一致）。
 */
import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
import { xcmaxAdminApi } from '@/api/xcmaxAdmin'
import { displayVersion } from './useSidebarAppVersion'

export function useSidebarAdminDeployStatus() {
  const accountProfileStore = useAccountProfileStore()
  const { isAdminAccount } = storeToRefs(accountProfileStore)

  const adminDeployStatus = ref(null)
  const adminDeployStatusError = ref('')
  const adminDeployStatusLoading = ref(false)
  let adminDeployPollTimer = null

  const shouldShowAdminDeployStatus = computed(() => isAdminConsoleSpa() && isAdminAccount.value)

  const adminDeployDisplayVersion = computed(() =>
    displayVersion(adminDeployStatus.value?.update_hub?.version || adminDeployStatus.value?.admin_local?.version || ''),
  )

  const adminDeployStatusTone = computed(() => {
    if (adminDeployStatusError.value) return 'error'
    const flags = adminDeployStatus.value?.flags || {}
    if (flags.needs_push || flags.needs_pack) return 'warn'
    if (flags.enterprise_pending) return 'info'
    if (flags.up_to_date) return 'ok'
    return 'muted'
  })

  const adminDeployStatusText = computed(() => {
    if (!shouldShowAdminDeployStatus.value) return ''
    if (adminDeployStatusLoading.value && !adminDeployStatus.value) return '版本检测中'
    if (adminDeployStatusError.value) return '版本未知'
    const flags = adminDeployStatus.value?.flags || {}
    const version = adminDeployDisplayVersion.value
    if (flags.enterprise_pending) return `新版本 ${version || ''} 已推送`.trim()
    if (flags.needs_push || flags.needs_pack) return `${version || '新版本'} 待推送`
    if (flags.up_to_date) return `${version || '当前版本'} 最新`
    return version || ''
  })

  const adminDeployStatusTitle = computed(() => {
    if (adminDeployStatusError.value) return adminDeployStatusError.value
    const hub = adminDeployStatus.value?.update_hub || {}
    const local = adminDeployStatus.value?.admin_local || {}
    return [
      local.version ? `管理端 ${displayVersion(local.version)}` : '',
      hub.version ? `update 站 ${displayVersion(hub.version)}` : '',
      hub.git_sha ? `Git ${String(hub.git_sha).slice(0, 12)}` : '',
    ]
      .filter(Boolean)
      .join(' · ')
  })

  async function refreshAdminDeployStatus() {
    if (!shouldShowAdminDeployStatus.value || adminDeployStatusLoading.value) return
    adminDeployStatusLoading.value = true
    adminDeployStatusError.value = ''
    try {
      const res = await xcmaxAdminApi.checkDeployUpdates('stable')
      adminDeployStatus.value = res?.data || null
      if (!adminDeployStatus.value) throw new Error(res?.message || '版本检测失败')
    } catch (e) {
      adminDeployStatus.value = null
      adminDeployStatusError.value = e instanceof Error ? e.message : String(e || '版本检测失败')
    } finally {
      adminDeployStatusLoading.value = false
    }
  }

  function stopAdminDeployStatusPolling() {
    if (adminDeployPollTimer != null) {
      window.clearInterval(adminDeployPollTimer)
      adminDeployPollTimer = null
    }
  }

  function startAdminDeployStatusPolling() {
    if (!shouldShowAdminDeployStatus.value || adminDeployPollTimer != null) return
    void refreshAdminDeployStatus()
    adminDeployPollTimer = window.setInterval(() => {
      void refreshAdminDeployStatus()
    }, 180000)
  }

  function syncAdminDeployStatusPolling() {
    if (shouldShowAdminDeployStatus.value) {
      startAdminDeployStatusPolling()
    } else {
      stopAdminDeployStatusPolling()
      adminDeployStatus.value = null
      adminDeployStatusError.value = ''
    }
  }

  watch(shouldShowAdminDeployStatus, () => {
    syncAdminDeployStatusPolling()
  })

  return {
    shouldShowAdminDeployStatus,
    adminDeployStatusTone,
    adminDeployStatusText,
    adminDeployStatusTitle,
    refreshAdminDeployStatus,
    stopAdminDeployStatusPolling,
    syncAdminDeployStatusPolling,
  }
}
