<template>
  <div class="page-view settings-page" id="view-settings">
    <div class="page-content settings-page__scroll">
      <div class="settings-layout">
        <aside class="settings-profile" :aria-label="$t('settings.profileAria')">
          <button
            type="button"
            class="settings-profile__avatar"
            :class="{ 'is-guest': !isLoggedIn, 'is-loading': accountLoading || avatarUploading }"
            :disabled="!isLoggedIn || accountLoading || avatarUploading"
            :title="isLoggedIn ? $t('settings.changeAvatar') : $t('settings.avatarAfterLogin')"
            @click="onAvatarClick"
          >
            <img v-if="profileAvatarUrl" :src="profileAvatarUrl" alt="" class="settings-profile__avatar-img" />
            <img
              v-else-if="isLoggedIn"
              :src="defaultUserAvatarSrc"
              alt=""
              class="settings-profile__avatar-img settings-profile__avatar-img--default"
            />
            <span v-else-if="avatarInitial" class="settings-profile__avatar-letter">{{ avatarInitial }}</span>
            <i v-else class="fa fa-user" aria-hidden="true"></i>
            <span v-if="isLoggedIn" class="settings-profile__avatar-hint">{{ $t('settings.changeAvatarShort') }}</span>
          </button>
          <input
            ref="avatarInputRef"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            class="settings-profile__avatar-input"
            tabindex="-1"
            aria-hidden="true"
            @change="onAvatarFileChange"
          />
          <p class="settings-profile__name settings-profile__brand">{{ adminSessionOnly ? '管理员' : profileBrandTitle }}</p>
          <p class="settings-profile__sub">{{ adminSessionOnly ? '已用管理员账号登录' : profileSubline }}</p>
          <div class="settings-profile__actions">
            <button
              v-if="isLoggedIn"
              type="button"
              class="settings-profile__btn settings-profile__btn--ghost"
              :disabled="logoutLoading"
              @click="onLogout"
            >
              {{ logoutLoading ? $t('settings.loggingOut') : $t('settings.logout') }}
            </button>
            <button v-else-if="accountError && !adminSessionOnly" type="button" class="settings-profile__btn" :disabled="accountLoading" @click="loadLocalUser()">{{ $t('chat.retry') }}</button>
            <router-link v-else-if="!adminSessionOnly && !accountLoading && !accountError" class="settings-profile__btn settings-profile__btn--primary" :to="loginRoute">
              {{ $t('settings.login') }}
            </router-link>
          </div>

          <nav class="settings-nav" aria-label="设置分区">
            <a
              v-for="group in SETTINGS_GROUPS"
              :key="group.id"
              :href="`#${group.id}`"
              class="settings-nav__item"
              :class="{ 'is-active': activeGroup === group.id }"
              :aria-current="activeGroup === group.id ? 'true' : undefined"
              @click.prevent="goGroup(group.id)"
            >
              <i v-if="!group.iconSrc" class="fa settings-nav__icon" :class="group.icon" aria-hidden="true"></i>
              <img v-else class="settings-nav__icon settings-nav__icon--art" :src="group.iconSrc" alt="" />
              <span class="settings-nav__label">{{ group.label }}</span>
            </a>
          </nav>
        </aside>

        <div class="settings-layout__main">
          <header class="settings-page__hero">
            <h1 class="settings-page__title">{{ $t('settings.pageTitle') }}</h1>
          </header>

          <div class="settings-list">
            <section v-show="!compactSettings || activeGroup === 'settings-group-account'" id="settings-group-account" class="settings-group" aria-labelledby="settings-group-account-title">
              <h2 id="settings-group-account-title" class="settings-group__title">账号</h2>
            <details v-if="isLoggedIn" id="settings-profile-home" class="settings-card" data-tutorial-id="settings-profile-home">
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
                  <img class="settings-row__icon-art" :src="settingsProfileArtSrc" alt="" />
                </span>
                <span class="settings-row__label">{{ $t('settings.profileHome') }}</span>
                <span class="settings-row__meta">{{ profileHomeSummary }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>
              <div class="settings-card__body settings-card__body--list">
                <div class="settings-profile-form">
                  <div class="settings-profile-form__editable">
                    <label class="settings-profile-form__field">
                      <span class="settings-profile-form__label">{{ $t('settings.displayName') }}</span>
                      <input
                        v-model="profileDisplayNameDraft"
                        class="settings-profile-form__input"
                        type="text"
                        maxlength="64"
                        :placeholder="$t('settings.displayNamePlaceholder')"
                        autocomplete="name"
                      />
                    </label>
                    <label class="settings-profile-form__field">
                      <span class="settings-profile-form__label">{{ $t('settings.email') }}</span>
                      <input
                        v-model="profileEmailDraft"
                        class="settings-profile-form__input"
                        type="email"
                        maxlength="128"
                        :placeholder="$t('settings.emailPlaceholder')"
                        autocomplete="email"
                      />
                    </label>
                  </div>
                  <div class="settings-profile-form__readonly" aria-readonly="true">
                    <span class="settings-profile-form__label">{{ $t('settings.loginName') }}</span>
                    <span class="settings-profile-form__readonly-value">{{ localUser?.username || '—' }}</span>
                    <p class="settings-profile-form__hint muted">
                      {{ $t('settings.loginNameHint') }}
                    </p>
                  </div>
                  <div class="settings-profile-form__actions">
                    <button
                      type="button"
                      class="settings-profile-form__submit"
                      :disabled="!profileFormDirty || profileSaving"
                      @click="saveProfile"
                    >
                      {{ profileSaving ? $t('settings.saving') : $t('settings.saveProfile') }}
                    </button>
                  </div>
                </div>
              </div>
            </details>

            <router-link v-if="canManageTenantRoles" class="settings-card settings-row settings-rbac-link"
              :to="{ name: 'tenant-roles' }">
              <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
                <img class="settings-row__icon-art" :src="settingsRolesArtSrc" alt="" />
              </span>
              <span class="settings-row__label">角色与权限</span>
              <span class="settings-row__meta">管理本企业的角色、权限和用户分配</span>
              <span class="settings-row__arrow" aria-hidden="true"></span>
            </router-link>
            </section>

            <section v-show="!compactSettings || activeGroup === 'settings-group-intelligence'" id="settings-group-intelligence" class="settings-group" aria-labelledby="settings-group-intelligence-title">
              <h2 id="settings-group-intelligence-title" class="settings-group__title">智能与数据</h2>
            <details id="settings-model-payment" class="settings-card" data-tutorial-id="settings-model-payment">
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
                  <img class="settings-row__icon-art" :src="settingsModelServiceArtSrc" alt="" />
                </span>
                <span class="settings-row__label">{{ $t('settings.modelService') }}</span>
                <span class="settings-row__meta">{{ $t('settings.modelServiceMeta') }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>
              <div class="settings-card__body settings-card__body--flush">
                <SettingsPlatformModelCard :can-manage="accountProfile.isAdminAccount && !accountProfile.isImpersonating" />
                <div v-if="isLoggedIn && !accountProfile.isImpersonating" class="settings-model-service-empty" :aria-busy="accountRuntime.busy">
                  <p class="settings-model-service-empty__title">当前账号运行验收</p>
                  <p v-if="accountRuntime.status?.managed_by === 'deployment'" class="muted">当前运行配置由部署方管理，此处会检查已有验收结果。配置或安装版本变化后，请由部署方重新完成验收。</p>
                  <p v-else class="muted">登录和恢复窗口只读取验收状态。首次主动执行任务前，或点击“运行验收”时按需验收，过程可能产生模型用量。相同配置与安装版本的有效结果会复用；失败或中断后可在这里重新验收。</p>
                  <button type="button" class="btn btn-sm btn-secondary" data-testid="runtime-check" :disabled="accountRuntime.loading || accountRuntime.checking" @click="accountRuntime.status?.qualification === 'in_progress' || accountRuntime.status?.managed_by === 'deployment' ? accountRuntime.refresh() : accountRuntime.retry()">{{ accountRuntime.checking ? '验收中…' : accountRuntime.loading ? '读取中…' : accountRuntime.status?.qualification === 'in_progress' || accountRuntime.status?.managed_by === 'deployment' ? '刷新状态' : '运行验收' }}</button>
                  <p v-if="accountRuntime.message" :role="accountRuntime.failed ? 'alert' : 'status'">{{ accountRuntime.message }}</p>
                </div>
                <HostModBridgeView
                  v-if="showModelPaymentBridge"
                  embedded
                  mod-id="xcagi-model-payment-bridge"
                  view="ModelPaymentView"
                  :title="$t('settings.modelService')"
                />
                <div v-else class="settings-model-service-empty">
                  <p class="settings-model-service-empty__title">
                    {{ $t('settings.modelServiceMissingTitle') }}
                  </p>
                  <p class="muted settings-model-service-empty__lead">
                    {{ $t('settings.modelServiceMissingLead') }}
                  </p>
                  <ul class="settings-model-service-empty__list muted">
                    <li>{{ $t('settings.modelServiceMissingWhy') }}</li>
                    <li>{{ $t('settings.modelServiceMissingHow') }}</li>
                    <li>{{ $t('settings.modelServiceMissingNote') }}</li>
                  </ul>
                  <div class="settings-model-service-empty__actions">
                    <router-link class="btn btn-sm btn-primary" :to="{ name: 'mod-store' }">
                      {{ $t('settings.modelServiceOpenModStore') }}
                    </router-link>
                    <button type="button" class="btn btn-sm btn-secondary" @click="openSettingsExtensions">
                      {{ $t('settings.modelServiceOpenExtensions') }}
                    </button>
                  </div>
                </div>
              </div>
            </details>

            <SettingsAuditLogsCard
              :is-logged-in="isLoggedIn" :is-local-admin="isLocalAdmin"
              :audit-logs-loading="auditLogsLoading" :audit-logs-error="auditLogsError"
              :audit-logs="auditLogs" :audit-logs-total="auditLogsTotal"
              :load-audit-logs="loadAuditLogs" :download-audit-csv="downloadAuditCsv"
            />

            <SettingsIntentCard
              :current-intent-industry-label="currentIntentIndustryLabel" :current-industry-unit="currentIndustryUnit"
              :current-industry-config="currentIndustryConfig" :intent-package-entries="intentPackageEntries"
            />

            <SettingsMemoryV2Card
              :persy-fold-meta="persyFoldMeta" :persy-loading="persyLoading" :persy-profile="persyProfile"
              :persy-inferring="persyInferring" :persy-last-reason="persyLastReason"
              :persy-error="persyError" :reload-persy-profile="loadPersyProfile" :run-persy-infer="runPersyInfer"
            />
            </section>

            <section v-show="!compactSettings || activeGroup === 'settings-group-system'" id="settings-group-system" class="settings-group" aria-labelledby="settings-group-system-title">
              <h2 id="settings-group-system-title" class="settings-group__title">系统与外观</h2>
            <SettingsBasicCard
              :basic-settings-summary="basicSettingsSummary" :sidebar-theme-options="sidebarThemeOptions"
              :on-sidebar-theme-change="onSidebarThemeChange" :show-company-brand-editor="showCompanyBrandEditor"
              :company-brand-saving="companyBrandSaving" :company-brand-dirty="companyBrandDirty"
              :save-company-brand="saveCompanyBrand" :on-locale-change="onLocaleChange"
              :system-display-name="systemDisplayName" :desktop-database-visible="desktopDatabaseVisible"
              :database-storage-label="databaseStorageLabel" :current-db-path="currentDbPath"
              :on-deployment-mode-change="onDeploymentModeChange" :display-deployment-modes="displayDeploymentModes"
              :deployment-mode-badge="deploymentModeBadge" :performance-mode-selected="performanceModeSelected"
              :deployment-saving="deploymentSaving" :deployment-status-message="deploymentStatusMessage"
              :deployment-transition-text="deploymentTransitionText" :deployment-sync-command="deploymentSyncCommand"
              :client-mods-ui-off="clientModsUiOff" :mod-settings-fold-meta="modSettingsFoldMeta"
              :mod-routes-status-text="modRoutesStatusText" :show-mod-routes-retry="showModRoutesRetry"
              :mod-routes-retrying="modRoutesRetrying" :retry-mod-routes-load="retryModRoutesLoad"
              :host-bridge-mods="hostBridgeMods" :host-bridge-installed-count="hostBridgeInstalledCount"
              :host-bridge-expected-count="hostBridgeExpectedCount" :go-host-pack-onboarding="goHostPackOnboarding"
              :uninstalling-mod-id="uninstallingModId" :on-uninstall-mod="onUninstallMod"
              :workflow-employee-mods="workflowEmployeeMods" :go-mod-store="goModStore"
              :selectable-extension-mods="selectableExtensionMods" :active-mod-id="activeModId"
              :on-active-mod-change="onActiveModChange" :load-error="loadError" :loading="loading"
              :save-settings="saveSettings"
              :save-summary="settingsSaveSummary" :save-had-failures="settingsSaveHadFailures"
              v-model:sidebar-theme-preset="sidebarThemePreset" v-model:company-brand-draft="companyBrandDraft"
              v-model:assistant-name="assistantName" v-model:app-locale="appLocale"
              v-model:deployment-mode="deploymentMode" v-model:postgres-url-draft="postgresUrlDraft"
              v-model:host-pack-expanded="hostPackExpanded"
            />
            </section>

            <section v-show="!compactSettings || activeGroup === 'settings-group-about'" id="settings-group-about" class="settings-group" aria-labelledby="settings-group-about-title">
              <h2 id="settings-group-about-title" class="settings-group__title">关于</h2>
            <SettingsVersionsCard
              :loading-versions="loadingVersions" :versions-error="versionsError" :versions="versions"
              :sample-count="sampleCount" :sample-count-warning="sampleCountWarning"
            />

            <SettingsAboutCard
              :app-version-label="appVersionLabel" :about-display-line="aboutDisplayLine" :is-desktop-shell="isDesktopShell"
              :about-update-busy="aboutUpdateBusy" :about-update-message="aboutUpdateMessage"
              :about-update-error="aboutUpdateError" :auto-launch="autoLaunch" :auto-launch-busy="autoLaunchBusy"
              :auto-launch-message="autoLaunchMessage" :on-check-for-updates="onCheckForUpdates"
              :on-auto-launch-change="onAutoLaunchChange"
            />
            </section>

          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { isAdminConsoleSpa } from '@/utils/adminConsoleUrl'
const compactSettings = isAdminConsoleSpa()
import { computed, onBeforeUnmount, onMounted, onActivated, ref, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useAccountRuntimeStore } from '@/stores/accountRuntime'
import { readStoredSidebarTheme, applySidebarTheme } from '@/utils/sidebarTheme'
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import { useSettingsAccount } from '@/composables/settings/useSettingsAccount'
import { useStartupPageReady } from '@/composables/useStartupSplash'
import { useAccountProfileStore } from '@/stores/accountProfile'
import { useSettingsMods } from '@/composables/settings/useSettingsMods'
import { useSettingsMemory } from '@/composables/settings/useSettingsMemory'
import { useSettingsBasics } from '@/composables/settings/useSettingsBasics'
import SettingsAuditLogsCard from './settings-view/SettingsAuditLogsCard.vue'
import SettingsIntentCard from './settings-view/SettingsIntentCard.vue'
import SettingsMemoryV2Card from './settings-view/SettingsMemoryV2Card.vue'
import SettingsBasicCard from './settings-view/SettingsBasicCard.vue'
import SettingsVersionsCard from './settings-view/SettingsVersionsCard.vue'
import SettingsAboutCard from './settings-view/SettingsAboutCard.vue'
import SettingsPlatformModelCard from './settings-view/SettingsPlatformModelCard.vue'
import settingsProfileArtSrc from '@/assets/icons/settings/r1c1.png'
import settingsRolesArtSrc from '@/assets/icons/settings/r1c2.png'
import defaultUserAvatarSrc from '@/assets/avatars/user-default.png'
import navAccountArtSrc from '@/assets/icons/settings/r1c1.png'
import navIntelligenceArtSrc from '@/assets/icons/settings/r1c4.png'
import navSystemArtSrc from '@/assets/icons/settings/r2c2.png'
import navAboutArtSrc from '@/assets/icons/settings/r5c1.png'
import settingsModelServiceArtSrc from '@/assets/icons/settings/r1c3.png'

const route = useRoute()
const accountProfile = useAccountProfileStore()
const accountRuntime = useAccountRuntimeStore()

const {
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
} = useSettingsAccount()
const adminSessionOnly = computed(() => !isLoggedIn.value && accountProfile.isAdminAccount) // 管理员会话已过守卫，市场会话未绑定时只改展示
const canManageTenantRoles = computed(
  () => accountProfile.accountKind === 'enterprise' && accountProfile.tenantId !== null &&
    accountProfile.marketIsEnterprise && accountProfile.permissions.includes('tenant.manage_roles'),
)

const {
  clientModsUiOff,
  loadError,
  isLoaded,
  mods,
  modRoutes,
  activeModId,
  modelPaymentBridgeInstalled,
  showModelPaymentBridge,
  uninstallingModId,
  hostPackExpanded,
  hostBridgeMods,
  hostBridgeInstalledCount,
  hostBridgeExpectedCount,
  selectableExtensionMods,
  workflowEmployeeMods,
  activeModMeta,
  activeModIndustry,
  modRoutesRetrying,
  modRoutesStatusText,
  showModRoutesRetry,
  modSettingsFoldMeta,
  installedAccountCustomMod,
  deliveryBrandName,
  industries,
  currentIndustry,
  currentIndustryUnit,
  currentIndustryConfig,
  currentIndustryLabel,
  currentIntentIndustryLabel,
  intentPackages,
  intentPackageEntries,
  systemDisplayName,
  aboutDisplayLine,
  openSettingsExtensions,
  goHostPackOnboarding,
  goModStore,
  retryModRoutesLoad,
  onActiveModChange,
  onUninstallMod,
  loadIndustries,
  loadCurrentIndustryDetail,
  updateIndustryKeywords,
  loadIntentPackages,
} = useSettingsMods()

const {
  persyProfile,
  persyLoading,
  persyError,
  persyInferring,
  persyLastReason,
  persyUserId,
  persyFoldMeta,
  loadPersyProfile,
  runPersyInfer,
} = useSettingsMemory(localUser)

const {
  appLocale,
  onLocaleChange,
  loading,
  loadingVersions,
  settingsSaveSummary,
  settingsSaveHadFailures,
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
  autoLaunch,
  autoLaunchBusy,
  autoLaunchMessage,
  loadAutoLaunch,
  onAutoLaunchChange,
} = useSettingsBasics()

function scrollToSettingsSection() {
  const section = String(route.query.section || '').trim()
  if (!section) return
  nextTick(() => {
    const el = document.getElementById(`settings-${section}`) || document.querySelector(`[data-tutorial-id="settings-${section}"]`)
    const groupId = el?.closest('.settings-group')?.id
    if (compactSettings && groupId) activeGroup.value = groupId
    if (el instanceof HTMLDetailsElement) {
      el.open = true
    } else if (el) {
      const parentDetails = el.closest('details.settings-card')
      if (parentDetails instanceof HTMLDetailsElement) parentDetails.open = true
    }
    void nextTick(() => el?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  })
}

watch(() => route.query.section, scrollToSettingsSection)

const preparePage = useStartupPageReady(async current => {
  persyLoading.value = true
  await loadLocalUser({ required: true, current })
  if (!current()) return
  void loadAuditLogs()
  void loadPersyProfile()
  void loadIntentPackages()
  // List and detail are independent aggregates; run them as one round trip window
  // instead of a serial list -> detail waterfall.
  await Promise.all([
    loadIndustries({ required: true, current }),
    loadCurrentIndustryDetail({ required: true, current }),
  ])
})

function prepareSettingsPage() {
  void preparePage().catch(() => {
    persyLoading.value = false
  })
}

const SETTINGS_GROUPS = [
  { id: 'settings-group-account', label: '账号', icon: 'fa-user-o', iconSrc: navAccountArtSrc },
  { id: 'settings-group-intelligence', label: '智能与数据', icon: 'fa-cubes', iconSrc: navIntelligenceArtSrc },
  { id: 'settings-group-system', label: '系统与外观', icon: 'fa-sliders', iconSrc: navSystemArtSrc },
  { id: 'settings-group-about', label: '关于', icon: 'fa-info-circle', iconSrc: navAboutArtSrc },
]
const activeGroup = ref(compactSettings ? 'settings-group-system' : SETTINGS_GROUPS[0].id)
let scrollSpyFrame = 0

function resolveGroupFromScroll(): string {
  const groups = SETTINGS_GROUPS.map(group => document.getElementById(group.id)).filter(
    (el): el is HTMLElement => Boolean(el),
  )
  if (!groups.length) return activeGroup.value
  let current = groups[0].id
  for (const el of groups) {
    if (el.getBoundingClientRect().top <= 140) current = el.id
  }
  return current
}

function onSettingsScroll() {
  if (compactSettings) return
  if (scrollSpyFrame) return
  scrollSpyFrame = window.requestAnimationFrame(() => {
    scrollSpyFrame = 0
    activeGroup.value = resolveGroupFromScroll()
  })
}

function goGroup(id: string) {
  activeGroup.value = id
  if (!compactSettings) document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  try {
    history.replaceState(null, '', `#${id}`)
  } catch {
    /* 忽略 hash 写入失败 */
  }
}

function setupGroupSpy() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  // 滚动容器可能是页面自身或内层内容区，捕获阶段监听可覆盖两种情况。
  document.addEventListener?.('scroll', onSettingsScroll, { passive: true, capture: true })
  window.addEventListener?.('resize', onSettingsScroll, { passive: true })
  if (!compactSettings) activeGroup.value = resolveGroupFromScroll()
  const hashId = String(window.location?.hash || '').replace(/^#/, '')
  if (SETTINGS_GROUPS.some(group => group.id === hashId)) {
    nextTick(() => goGroup(hashId))
  }
}

function teardownGroupSpy() {
  if (typeof document === 'undefined' || typeof window === 'undefined') return
  document.removeEventListener?.('scroll', onSettingsScroll, { capture: true } as EventListenerOptions)
  window.removeEventListener?.('resize', onSettingsScroll)
  if (scrollSpyFrame) {
    window.cancelAnimationFrame?.(scrollSpyFrame)
    scrollSpyFrame = 0
  }
}

onMounted(setupGroupSpy)
onBeforeUnmount(teardownGroupSpy)

onMounted(() => {
  sidebarThemePreset.value = readStoredSidebarTheme()
  applySidebarTheme(sidebarThemePreset.value)
  scrollToSettingsSection()
  prepareSettingsPage()
  void accountRuntime.refresh()
  void loadDesktopDatabaseStatus()
  void loadPreferences()
  loadAutoLaunch()
  loadDistillationVersions()
})

let activatedOnce = false
onActivated(() => {
  if (!activatedOnce) { activatedOnce = true; return }
  prepareSettingsPage()
  void accountRuntime.refresh()
})

</script>

<style scoped src="./SettingsView.css"></style>
