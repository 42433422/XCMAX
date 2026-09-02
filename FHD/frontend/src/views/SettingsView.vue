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
          <p class="settings-profile__name settings-profile__brand">{{ profileBrandTitle }}</p>
          <p class="settings-profile__sub">{{ profileSubline }}</p>
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
            <router-link v-else class="settings-profile__btn settings-profile__btn--primary" :to="loginRoute">
              {{ $t('settings.login') }}
            </router-link>
          </div>
        </aside>

        <div class="settings-layout__main">
          <header class="settings-page__hero">
            <h1 class="settings-page__title">{{ $t('settings.pageTitle') }}</h1>
          </header>

          <div class="settings-list">
            <details v-if="isLoggedIn" id="settings-profile-home" class="settings-card" data-tutorial-id="settings-profile-home" open>
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--indigo" aria-hidden="true">
                  <i class="fa fa-id-card"></i>
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

            <details id="settings-model-payment" class="settings-card" data-tutorial-id="settings-model-payment" open>
              <summary class="settings-row">
                <span class="settings-row__icon settings-row__icon--blue" aria-hidden="true">
                  <i class="fa fa-credit-card"></i>
                </span>
                <span class="settings-row__label">{{ $t('settings.modelService') }}</span>
                <span class="settings-row__meta">{{ $t('settings.modelServiceMeta') }}</span>
                <span class="settings-row__arrow" aria-hidden="true"></span>
              </summary>
              <div class="settings-card__body settings-card__body--flush">
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
              :memory-v2-status-filters="memoryV2StatusFilters" :memory-v2-type-options="memoryV2TypeOptions"
              :memory-v2-loading="memoryV2Loading" :memory-v2-error="memoryV2Error"
              :memory-v2-draft="memoryV2Draft" :memory-v2-creating="memoryV2Creating"
              :memory-v2-planner-context="memoryV2PlannerContext" :memory-v2-records="memoryV2Records"
              :memory-v2-edit="memoryV2Edit" :memory-v2-busy-id="memoryV2BusyId"
              :run-persy-infer="runPersyInfer" :load-memory-v2="loadMemoryV2"
              :create-memory-v2-candidate="createMemoryV2Candidate" :memory-v2-type-label="memoryV2TypeLabel"
              :memory-v2-status-label="memoryV2StatusLabel" :memory-v2-time="memoryV2Time"
              :memory-v2-display-value="memoryV2DisplayValue" :can-edit-memory-v2="canEditMemoryV2"
              :save-memory-v2-edit="saveMemoryV2Edit" :cancel-memory-v2-edit="cancelMemoryV2Edit"
              :confirm-memory-v2="confirmMemoryV2" :reject-memory-v2="rejectMemoryV2"
              :start-memory-v2-edit="startMemoryV2Edit" :delete-memory-v2="deleteMemoryV2"
              v-model:memory-v2-status-filter="memoryV2StatusFilter" v-model:memory-v2-type-filter="memoryV2TypeFilter"
            />

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
              v-model:sidebar-theme-preset="sidebarThemePreset" v-model:company-brand-draft="companyBrandDraft"
              v-model:assistant-name="assistantName" v-model:app-locale="appLocale"
              v-model:deployment-mode="deploymentMode" v-model:postgres-url-draft="postgresUrlDraft"
              v-model:host-pack-expanded="hostPackExpanded"
            />

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

          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onActivated, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useModsStore } from '@/stores/mods'
import { useIndustryStore } from '../stores/industry'
import { readStoredSidebarTheme, applySidebarTheme } from '@/utils/sidebarTheme'
import HostModBridgeView from '@/components/HostModBridgeView.vue'
import { useSettingsAccount } from '@/composables/settings/useSettingsAccount'
import { useSettingsMods } from '@/composables/settings/useSettingsMods'
import { useSettingsMemory } from '@/composables/settings/useSettingsMemory'
import { useSettingsBasics } from '@/composables/settings/useSettingsBasics'
import SettingsAuditLogsCard from './settings-view/SettingsAuditLogsCard.vue'
import SettingsIntentCard from './settings-view/SettingsIntentCard.vue'
import SettingsMemoryV2Card from './settings-view/SettingsMemoryV2Card.vue'
import SettingsBasicCard from './settings-view/SettingsBasicCard.vue'
import SettingsVersionsCard from './settings-view/SettingsVersionsCard.vue'
import SettingsAboutCard from './settings-view/SettingsAboutCard.vue'

const route = useRoute()
const modsStore = useModsStore()
const industryStore = useIndustryStore()

const {
  localUser,
  sessionValid,
  accountLoading,
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
  memoryV2TypeOptions,
  memoryV2StatusFilters,
  memoryV2Records,
  memoryV2Summary,
  memoryV2PlannerContext,
  memoryV2Loading,
  memoryV2Creating,
  memoryV2BusyId,
  memoryV2Error,
  memoryV2StatusFilter,
  memoryV2TypeFilter,
  memoryV2Draft,
  memoryV2Edit,
  persyProfile,
  persyLoading,
  persyInferring,
  persyLastReason,
  persyUserId,
  persyFoldMeta,
  memoryV2UserId,
  memoryV2FoldMeta,
  loadPersyProfile,
  runPersyInfer,
  memoryV2TypeLabel,
  memoryV2StatusLabel,
  memoryV2EditableValue,
  memoryV2DisplayValue,
  parseMemoryV2InputValue,
  memoryV2Time,
  canEditMemoryV2,
  loadMemoryV2,
  createMemoryV2Candidate,
  confirmMemoryV2,
  rejectMemoryV2,
  startMemoryV2Edit,
  cancelMemoryV2Edit,
  saveMemoryV2Edit,
  deleteMemoryV2,
} = useSettingsMemory(localUser)

const {
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
    if (el instanceof HTMLDetailsElement) {
      el.open = true
    } else if (el) {
      const parentDetails = el.closest('details.settings-card')
      if (parentDetails instanceof HTMLDetailsElement) parentDetails.open = true
    }
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  })
}

watch(() => route.query.section, scrollToSettingsSection)

onMounted(async () => {
  scrollToSettingsSection()
  await loadLocalUser()
  void loadAuditLogs()
  void loadDesktopDatabaseStatus()
  const uname = String(localUser.value?.username || '').trim()
  if (!modsStore.isLoaded) {
    await modsStore.initialize(true, {
      accountUsername: uname,
    })
  }
  sidebarThemePreset.value = readStoredSidebarTheme()
  applySidebarTheme(sidebarThemePreset.value)
  await industryStore.initialize()
  await loadIndustries()
  const piniaIndustryId = industryStore.currentIndustry?.id
  if (piniaIndustryId !== undefined && piniaIndustryId !== null && String(piniaIndustryId).trim() !== '') {
    currentIndustry.value = String(piniaIndustryId).trim()
  }
  await loadCurrentIndustryDetail()
  await loadIntentPackages()
  void loadPreferences()
  loadAutoLaunch()
  void loadMemoryV2()
  void loadPersyProfile()
  loadDistillationVersions()
})

onActivated(() => {
  void loadLocalUser().then(() => {
    loadMemoryV2()
    loadPersyProfile()
  })
})
</script>

<style scoped src="./SettingsView.css"></style>