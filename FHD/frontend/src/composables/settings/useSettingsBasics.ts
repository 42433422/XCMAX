import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '@/api'
import {
  DEFAULT_DEPLOYMENT_MODE,
  DEPLOYMENT_MODES,
  type DeploymentMode,
  type DeploymentModeId,
} from '@/constants/deploymentModes.generated'
import { SIDEBAR_THEME_OPTIONS, persistSidebarTheme } from '@/utils/sidebarTheme'
import packageJson from '../../../package.json'
import { appAlert } from '@/utils/appDialog'
import { setAppLocale } from '@/i18n'
import {
  errorMessage,
  type ApiMessageResult,
  type DistillationVersion,
  type DesktopDeploymentResponse,
  type DesktopDeploymentUpdateResponse,
} from './utils'

const ASSISTANT_NAME_KEY = 'assistantName'
const DEFAULT_ASSISTANT_NAME = '修茈'

export function useSettingsBasics() {
  const { t, te, locale } = useI18n()

  const appLocale = ref<'zh-CN' | 'en-US'>(locale.value === 'en-US' ? 'en-US' : 'zh-CN')

  function onLocaleChange() {
    setAppLocale(appLocale.value)
  }

  const loading = ref(false)
  const loadingVersions = ref(false)
  const aiMode = ref('online')
  const deploymentModes = ref<DeploymentMode[]>([...DEPLOYMENT_MODES])
  const deploymentMode = ref<DeploymentModeId>(DEFAULT_DEPLOYMENT_MODE)
  const deploymentSaving = ref(false)
  const deploymentStatusMessage = ref('')
  const deploymentSyncCommand = ref('')
  const deploymentRestartRequired = ref(false)
  const postgresUrlDraft = ref('')
  const postgresConfigured = ref(false)
  const assistantName = ref('修茈')
  const versions = ref<DistillationVersion[]>([])
  const sampleCount = ref(0)
  const versionsError = ref('')
  const sampleCountWarning = ref('')
  const aboutUpdateBusy = ref(false)
  const aboutUpdateMessage = ref('')
  const aboutUpdateError = ref(false)
  const currentDbPath = ref('')
  const databaseStorageLabel = ref('')
  const desktopDatabaseVisible = ref(false)

  function isDeploymentModeId(value: unknown): value is DeploymentModeId {
    return DEPLOYMENT_MODES.some((mode) => mode.id === value)
  }

  function normalizeDeploymentModeId(value: unknown): DeploymentModeId {
    return isDeploymentModeId(value) ? value : DEFAULT_DEPLOYMENT_MODE
  }

  const selectedDeploymentMode = computed(
    () =>
      deploymentModes.value.find((mode) => mode.id === deploymentMode.value) ||
      DEPLOYMENT_MODES.find((mode) => mode.id === DEFAULT_DEPLOYMENT_MODE) ||
      DEPLOYMENT_MODES[0],
  )

  const deploymentModeBadge = computed(() => {
    const mode = selectedDisplayDeploymentMode.value
    return mode ? `${mode.badge} · ${mode.summary}` : ''
  })

  const performanceModeSelected = computed(() => deploymentMode.value === 'performance')

  const deploymentTransitionText = computed(() =>
    performanceModeSelected.value ? t('settings.deployTransitionPerf') : t('settings.deployTransitionDefault'),
  )

  function localizeDeploymentMode(mode: DeploymentMode): DeploymentMode {
    const base = `settings.deploymentModes.${mode.id}`
    if (!te(`${base}.label`)) return mode
    return {
      ...mode,
      label: String(t(`${base}.label`)),
      badge: String(t(`${base}.badge`)),
      summary: String(t(`${base}.summary`)),
    }
  }

  const displayDeploymentModes = computed(() => deploymentModes.value.map(localizeDeploymentMode))

  const selectedDisplayDeploymentMode = computed(() => {
    const selected = selectedDeploymentMode.value
    return selected ? localizeDeploymentMode(selected) : selected
  })

  function storageLabel(mode: string): string {
    return mode === 'local_sqlite'
      ? t('settings.storageLocalSqlite')
      : mode === 'remote_postgresql'
        ? t('settings.storageRemotePg')
        : t('settings.storageLocal')
  }

  function onDeploymentModeChange() {
    const selected = selectedDeploymentMode.value
    if (selected?.aiMode === 'online' || selected?.aiMode === 'offline') {
      aiMode.value = selected.aiMode
    }
    deploymentStatusMessage.value = performanceModeSelected.value ? t('settings.performanceNeedsPg') : ''
  }

  async function loadDesktopDatabaseStatus() {
    let triedDeploymentEndpoint = false
    try {
      triedDeploymentEndpoint = true
      const deploymentRes = await api.get<DesktopDeploymentResponse>('/api/desktop/deployment')
      const deployment = (deploymentRes?.data ?? deploymentRes) as DesktopDeploymentResponse
      if (deployment?.success && deployment.desktopMode !== false) {
        desktopDatabaseVisible.value = true
        if (Array.isArray(deployment.modes) && deployment.modes.length) {
          deploymentModes.value = deployment.modes
        }
        deploymentMode.value = normalizeDeploymentModeId(deployment.currentMode)
        onDeploymentModeChange()
        const db = deployment.database || {}
        const mode = String(db.storageMode || '')
        databaseStorageLabel.value = storageLabel(mode)
        currentDbPath.value = String(db.sqlitePath || db.databaseUrlRedacted || '')
        postgresConfigured.value = Boolean(String(db.postgresUrlRedacted || '').trim())
        deploymentSyncCommand.value = String(deployment.syncPlan?.syncCommand || '')
        deploymentRestartRequired.value = Boolean(deployment.restartRequired)
        return
      }
    } catch {
      // 老后端或 Web 模式下继续走 /api/desktop/status 兼容路径。
    }

    try {
      const res = await api.get<{
        data?: Record<string, unknown>
        desktopMode?: boolean
        storageMode?: string
      }>('/api/desktop/status')
      const data = (res?.data ?? res) as Record<string, unknown>
      if (!data || data.desktopMode === false) {
        desktopDatabaseVisible.value = false
        databaseStorageLabel.value = ''
        currentDbPath.value = ''
        return
      }
      desktopDatabaseVisible.value = true
      const mode = String(data.storageMode || '')
      databaseStorageLabel.value = storageLabel(mode)
      if (data.database) {
        currentDbPath.value = String(data.database)
      }
    } catch {
      if (!triedDeploymentEndpoint) {
        deploymentStatusMessage.value = ''
      }
      desktopDatabaseVisible.value = false
      databaseStorageLabel.value = ''
      currentDbPath.value = ''
    }
  }

  const sidebarThemePreset = ref('office-default')

  const appVersionLabel = computed(() => String(packageJson.version || '1.0.0'))
  const isDesktopShell = computed(() => Boolean(window.xcagiDesktop))

  const sidebarThemeOptions = computed(() =>
    SIDEBAR_THEME_OPTIONS.map((theme) => ({
      ...theme,
      label: t(`settings.sidebarThemes.${theme.value}`),
    })),
  )

  const selectedSidebarAccent = computed(() => {
    const selected = SIDEBAR_THEME_OPTIONS.find((item) => item.value === sidebarThemePreset.value)
    return selected?.accent || '#0f6cbd'
  })

  const normalizedAssistantName = computed(() => {
    const normalized = assistantName.value?.trim()
    return normalized || DEFAULT_ASSISTANT_NAME
  })

  const basicSettingsSummary = computed(() => {
    const mode =
      selectedDisplayDeploymentMode.value?.label || (aiMode.value === 'offline' ? t('settings.offline') : t('settings.aiModeOnline'))
    return `${normalizedAssistantName.value} · ${mode}`
  })

  async function loadPreferences() {
    try {
      const data = await api.get<{ success?: boolean; preferences?: Record<string, unknown> }>('/api/preferences', { user_id: 'default' })
      if (!data?.success || !data?.preferences) return
      const prefs = data.preferences

      // 与 aiMode 无关的偏好先行读取，避免被 early return 跳过
      const preferredAssistantName = prefs.assistantName
      if (typeof preferredAssistantName === 'string') {
        assistantName.value = preferredAssistantName
      } else {
        assistantName.value = window.localStorage.getItem(ASSISTANT_NAME_KEY) || DEFAULT_ASSISTANT_NAME
      }
      window.localStorage.setItem(ASSISTANT_NAME_KEY, normalizedAssistantName.value)

      const preferredMode = prefs.aiMode
      if (preferredMode === 'online' || preferredMode === 'offline') {
        aiMode.value = preferredMode
        return
      }
      const legacyModel = String(prefs.aiModel || '').toLowerCase()
      aiMode.value = legacyModel === 'local' ? 'offline' : 'online'
      if (legacyModel) {
        // 兼容历史键：读取后自动迁移为新键，避免后续逻辑分叉。
        await api.post('/api/preferences', {
          user_id: 'default',
          key: 'aiMode',
          value: aiMode.value,
        })
      }
    } catch (e) {
      console.error('加载设置失败:', e)
      assistantName.value = window.localStorage.getItem(ASSISTANT_NAME_KEY) || DEFAULT_ASSISTANT_NAME
    }
  }

  async function saveSettings() {
    loading.value = true
    try {
      if (desktopDatabaseVisible.value && performanceModeSelected.value && !postgresUrlDraft.value.trim() && !postgresConfigured.value) {
        await appAlert(t('settings.performancePgRequired'))
        return
      }
      const deploymentResult = await saveDeploymentSettings()
      const saveResults = await Promise.all([
        api.post<ApiMessageResult>('/api/preferences', {
          user_id: 'default',
          key: 'aiMode',
          value: aiMode.value,
        }),
        api.post<ApiMessageResult>('/api/preferences', {
          user_id: 'default',
          key: ASSISTANT_NAME_KEY,
          value: normalizedAssistantName.value,
        }),
      ])
      const failed = saveResults.find((item) => !item?.success)
      if (failed) throw new Error(failed?.message || t('settings.saveFailed'))
      assistantName.value = normalizedAssistantName.value
      window.localStorage.setItem(ASSISTANT_NAME_KEY, normalizedAssistantName.value)
      window.dispatchEvent(
        new CustomEvent('assistant-name-updated', {
          detail: {
            name: normalizedAssistantName.value,
          },
        }),
      )
      const restartHint = deploymentResult?.restartRequired ? t('settings.settingsSavedRestartHint') : ''
      await appAlert(t('settings.settingsSaved', { hint: restartHint }))
    } catch (e: unknown) {
      console.error('保存设置失败:', e)
      await appAlert(t('settings.saveFailedWithDetail', { detail: errorMessage(e, t('settings.unknownError')) }))
    } finally {
      loading.value = false
    }
  }

  async function saveDeploymentSettings(): Promise<DesktopDeploymentUpdateResponse | null> {
    if (!desktopDatabaseVisible.value) return null
    deploymentSaving.value = true
    deploymentStatusMessage.value = ''
    deploymentSyncCommand.value = ''
    try {
      const payload: { mode: DeploymentModeId; postgresUrl?: string } = {
        mode: deploymentMode.value,
      }
      const pgUrl = postgresUrlDraft.value.trim()
      if (pgUrl) payload.postgresUrl = pgUrl
      const result = await api.put<DesktopDeploymentUpdateResponse>('/api/desktop/deployment', payload)
      const data = (result?.data ?? result) as DesktopDeploymentUpdateResponse
      if (!data?.success) throw new Error(t('settings.deploymentSaveFailed'))
      const db = data.database || {}
      databaseStorageLabel.value = storageLabel(String(db.storageMode || ''))
      currentDbPath.value = String(db.sqlitePath || db.databaseUrlRedacted || currentDbPath.value || '')
      postgresConfigured.value = postgresConfigured.value || Boolean(pgUrl || String(db.postgresUrlRedacted || '').trim())
      deploymentRestartRequired.value = Boolean(data.restartRequired)
      deploymentSyncCommand.value = String(data.syncPlan?.syncCommand || '')
      deploymentStatusMessage.value = performanceModeSelected.value ? t('settings.deploymentSavedPerf') : t('settings.deploymentSaved')
      return data
    } finally {
      deploymentSaving.value = false
    }
  }

  function onSidebarThemeChange() {
    persistSidebarTheme(sidebarThemePreset.value)
  }

  async function loadDistillationVersions() {
    loadingVersions.value = true
    versionsError.value = ''
    sampleCountWarning.value = ''
    try {
      const data = await api.get<{
        success?: boolean
        message?: string
        versions?: DistillationVersion[]
        distillation_samples?: number
        sample_count_error?: string
      }>('/api/distillation/versions')
      if (!data?.success) throw new Error(data?.message || t('settings.loadFailed'))
      versions.value = Array.isArray(data.versions) ? data.versions : []
      sampleCount.value = Number(data.distillation_samples || 0)
      if (data?.sample_count_error) {
        sampleCountWarning.value = t('settings.sampleCountError', {
          detail: data.sample_count_error,
        })
      }
    } catch (e: unknown) {
      console.error('加载蒸馏版本失败:', e)
      versions.value = []
      sampleCount.value = 0
      versionsError.value = t('settings.versionsLoadFailed', {
        detail: errorMessage(e, t('settings.networkOrServiceError')),
      })
    } finally {
      loadingVersions.value = false
    }
  }

  async function onCheckForUpdates() {
    if (!window.xcagiDesktop?.checkForUpdates) {
      aboutUpdateMessage.value = t('settings.updateUnavailable')
      aboutUpdateError.value = true
      return
    }
    aboutUpdateBusy.value = true
    aboutUpdateMessage.value = ''
    aboutUpdateError.value = false
    try {
      // 手动检查时清掉「稍后提醒」，否则同版本角标会一直被 sessionStorage 压住
      try {
        sessionStorage.removeItem('xcagi_desktop_update_dismiss_version')
      } catch {
        /* ignore */
      }
      await window.xcagiDesktop.checkForUpdates()
      aboutUpdateMessage.value = t('settings.updateCheckStarted')
    } catch (e: unknown) {
      aboutUpdateMessage.value = `${t('settings.updateCheckFailed')}：${errorMessage(e, t('settings.unknownError'))}`
      aboutUpdateError.value = true
    } finally {
      aboutUpdateBusy.value = false
    }
  }

  return {
    appLocale,
    onLocaleChange,
    loading,
    loadingVersions,
    aiMode,
    deploymentModes,
    deploymentMode,
    deploymentSaving,
    deploymentStatusMessage,
    deploymentSyncCommand,
    deploymentRestartRequired,
    postgresUrlDraft,
    postgresConfigured,
    assistantName,
    versions,
    sampleCount,
    versionsError,
    sampleCountWarning,
    aboutUpdateBusy,
    aboutUpdateMessage,
    aboutUpdateError,
    currentDbPath,
    databaseStorageLabel,
    desktopDatabaseVisible,
    isDeploymentModeId,
    normalizeDeploymentModeId,
    selectedDeploymentMode,
    deploymentModeBadge,
    performanceModeSelected,
    deploymentTransitionText,
    localizeDeploymentMode,
    displayDeploymentModes,
    selectedDisplayDeploymentMode,
    storageLabel,
    onDeploymentModeChange,
    loadDesktopDatabaseStatus,
    sidebarThemePreset,
    appVersionLabel,
    isDesktopShell,
    sidebarThemeOptions,
    selectedSidebarAccent,
    normalizedAssistantName,
    basicSettingsSummary,
    loadPreferences,
    saveSettings,
    saveDeploymentSettings,
    onSidebarThemeChange,
    loadDistillationVersions,
    onCheckForUpdates,
  }
}
