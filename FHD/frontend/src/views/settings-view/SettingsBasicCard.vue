<template>
  <details class="settings-card" data-tutorial-id="settings-basic" open>
    <summary class="settings-row">
      <span class="settings-row__icon settings-row__icon--green" aria-hidden="true">
        <i class="fa fa-sliders"></i>
      </span>
      <span class="settings-row__label">{{ $t('settings.basicSettings') }}</span>
      <span class="settings-row__meta">{{ basicSettingsSummary }}</span>
      <span class="settings-row__arrow" aria-hidden="true"></span>
    </summary>

    <div class="settings-card__body settings-card__body--list">
      <div class="settings-item-list">
        <div class="settings-item">
          <span class="settings-item__icon settings-row__icon--cyan" aria-hidden="true">
            <i class="fa fa-columns"></i>
          </span>
          <label class="settings-item__label" for="settings-sidebar-theme">{{ $t('settings.sidebarTheme') }}</label>
          <select
            id="settings-sidebar-theme"
            v-model="sidebarThemePreset"
            class="settings-item__control settings-item__control--select"
            @change="onSidebarThemeChange"
          >
            <option v-for="theme in sidebarThemeOptions" :key="theme.value" :value="theme.value">
              {{ theme.label }}
            </option>
          </select>
        </div>

        <div v-if="showCompanyBrandEditor" class="settings-item">
          <span class="settings-item__icon settings-row__icon--amber" aria-hidden="true">
            <i class="fa fa-building"></i>
          </span>
          <label class="settings-item__label" for="settings-company-brand">{{ $t('settings.companyBrand') }}</label>
          <div class="settings-item__control-group">
            <input
              id="settings-company-brand"
              v-model="companyBrandDraft"
              class="settings-item__control settings-item__control--text"
              type="text"
              maxlength="64"
              :placeholder="$t('settings.companyBrandPlaceholder')"
            />
            <button
              type="button"
              class="settings-item__save-btn"
              :disabled="companyBrandSaving || !companyBrandDirty"
              @click="saveCompanyBrand"
            >
              {{ companyBrandSaving ? $t('settings.saving') : $t('settings.save') }}
            </button>
          </div>
        </div>

        <div class="settings-item">
          <span class="settings-item__icon settings-row__icon--indigo" aria-hidden="true">
            <i class="fa fa-user-circle"></i>
          </span>
          <label class="settings-item__label" for="settings-assistant-name">{{ $t('settings.assistantName') }}</label>
          <input
            id="settings-assistant-name"
            v-model="assistantName"
            class="settings-item__control settings-item__control--text"
            type="text"
            maxlength="24"
            :placeholder="$t('settings.assistantNamePlaceholder')"
          />
        </div>

        <div class="settings-item">
          <span class="settings-item__icon settings-row__icon--indigo" aria-hidden="true">
            <i class="fa fa-language"></i>
          </span>
          <label class="settings-item__label" for="settings-locale">{{ $t('settings.language') }}</label>
          <select
            id="settings-locale"
            v-model="appLocale"
            class="settings-item__control settings-item__control--select"
            @change="onLocaleChange"
          >
            <option value="zh-CN">{{ $t('settings.localeZhCN') }}</option>
            <option value="en-US">{{ $t('settings.localeEnUS') }}</option>
          </select>
        </div>

        <div class="settings-item settings-item--readonly">
          <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
            <i class="fa fa-desktop"></i>
          </span>
          <span class="settings-item__label">{{ $t('settings.systemName') }}</span>
          <span class="settings-item__value">{{ systemDisplayName }}</span>
        </div>

        <div v-if="desktopDatabaseVisible" class="settings-item settings-item--readonly">
          <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
            <i class="fa fa-database"></i>
          </span>
          <span class="settings-item__label">{{ $t('settings.dataStorage') }}</span>
          <span class="settings-item__value">{{ databaseStorageLabel }}</span>
        </div>

        <div v-if="desktopDatabaseVisible" class="settings-item settings-item--readonly">
          <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
            <i class="fa fa-folder-open-o"></i>
          </span>
          <span class="settings-item__label">{{ $t('settings.dbPath') }}</span>
          <span class="settings-item__value settings-item__value--mono" :title="currentDbPath">{{ currentDbPath }}</span>
        </div>

        <div class="settings-item">
          <span class="settings-item__icon settings-row__icon--violet" aria-hidden="true">
            <i class="fa fa-cloud"></i>
          </span>
          <label class="settings-item__label" for="settings-ai-mode">{{ $t('settings.aiDeployMode') }}</label>
          <select
            id="settings-ai-mode"
            v-model="deploymentMode"
            class="settings-item__control settings-item__control--select"
            @change="onDeploymentModeChange"
          >
            <option v-for="mode in displayDeploymentModes" :key="mode.id" :value="mode.id">
              {{
                $t('settings.deploymentModeOption', {
                  label: mode.label,
                  badge: mode.badge,
                })
              }}
            </option>
          </select>
        </div>

        <div class="settings-item settings-item--readonly">
          <span class="settings-item__icon settings-row__icon--cyan" aria-hidden="true">
            <i class="fa fa-random"></i>
          </span>
          <span class="settings-item__label">{{ $t('settings.networkPerf') }}</span>
          <span class="settings-item__value">{{ deploymentModeBadge }}</span>
        </div>

        <div v-if="performanceModeSelected" class="settings-item settings-item--stacked">
          <span class="settings-item__icon settings-row__icon--slate" aria-hidden="true">
            <i class="fa fa-database"></i>
          </span>
          <label class="settings-item__label" for="settings-postgres-url">{{ $t('settings.postgresConnection') }}</label>
          <input
            id="settings-postgres-url"
            v-model="postgresUrlDraft"
            class="settings-item__control settings-item__control--text settings-item__control--wide"
            type="password"
            autocomplete="off"
            placeholder="postgresql+psycopg://user:password@host:5432/xcagi"
          />
          <p class="settings-item__hint">
            {{ $t('settings.performanceModeHint') }}
          </p>
        </div>

        <transition name="settings-fade">
          <div
            v-if="deploymentSaving || deploymentStatusMessage"
            class="deployment-transition"
            :class="{ 'deployment-transition--done': !deploymentSaving }"
          >
            <span v-if="deploymentSaving" class="deployment-transition__spinner" aria-hidden="true"></span>
            <i v-else class="fa fa-check-circle deployment-transition__done" aria-hidden="true"></i>
            <span>{{ deploymentSaving ? deploymentTransitionText : deploymentStatusMessage }}</span>
          </div>
        </transition>

        <p v-if="deploymentSyncCommand" class="deployment-sync-command" :title="deploymentSyncCommand">
          {{ deploymentSyncCommand }}
        </p>
      </div>

      <details class="settings-card settings-card--nested" data-tutorial-id="settings-mobile-pairing" open>
        <summary class="settings-row settings-row--nested">
          <span class="settings-row__icon settings-row__icon--cyan" aria-hidden="true">
            <i class="fa fa-qrcode"></i>
          </span>
          <span class="settings-row__label">{{ $t('settings.mobilePairing') }}</span>
          <span class="settings-row__meta">{{ $t('settings.mobilePairingMeta') }}</span>
          <span class="settings-row__arrow" aria-hidden="true"></span>
        </summary>
        <div class="settings-card__body settings-card__body--nested">
          <MobilePairingQrCard />
        </div>
      </details>

      <details v-if="!clientModsUiOff" class="settings-card settings-card--nested" data-tutorial-id="settings-extensions">
        <summary class="settings-row settings-row--nested">
          <span class="settings-row__icon settings-row__icon--orange" aria-hidden="true">
            <i class="fa fa-puzzle-piece"></i>
          </span>
          <span class="settings-row__label">{{ $t('settings.extensions') }}</span>
          <span class="settings-row__meta">{{ modSettingsFoldMeta }}</span>
          <span class="settings-row__arrow" aria-hidden="true"></span>
        </summary>
        <div class="settings-card__body settings-card__body--nested">
          <p v-if="modRoutesStatusText" class="muted mod-routes-status text-warning">
            {{ modRoutesStatusText }}
          </p>
          <button
            v-if="showModRoutesRetry"
            type="button"
            class="btn btn-secondary btn-sm"
            :disabled="modRoutesRetrying"
            @click="retryModRoutesLoad"
          >
            {{ modRoutesRetrying ? $t('settings.retrying') : $t('settings.retryLoadMods') }}
          </button>

          <section v-if="hostBridgeMods.length" class="mod-fold-section">
            <div class="mod-fold-section-head">
              <span class="mod-ui-off-label">{{ $t('settings.hostBridgePack') }}</span>
              <span class="mod-host-pack-stat">
                {{
                  $t('settings.hostReady', {
                    installed: hostBridgeInstalledCount,
                    expected: hostBridgeExpectedCount,
                  })
                }}
              </span>
            </div>
            <div class="mod-host-pack-bar">
              <button type="button" class="btn btn-secondary btn-sm" @click="hostPackExpanded = !hostPackExpanded">
                {{ hostPackExpanded ? $t('settings.collapse') : $t('settings.inventory') }}
              </button>
              <button type="button" class="btn btn-link btn-sm" @click="goHostPackOnboarding">
                {{ $t('settings.installAll') }}
              </button>
            </div>
            <ul v-if="hostPackExpanded" class="mod-host-pack-list">
              <li v-for="mod in hostBridgeMods" :key="mod.id" class="mod-host-pack-row">
                <span class="mod-host-pack-name">{{ mod.name || mod.id }}</span>
                <button
                  type="button"
                  class="btn btn-danger btn-sm mod-single-uninstall"
                  :disabled="uninstallingModId === mod.id || isProtectedClientModId(mod.id)"
                  @click="onUninstallMod(mod.id)"
                >
                  {{ uninstallingModId === mod.id ? $t('settings.uninstalling') : $t('settings.uninstall') }}
                </button>
              </li>
            </ul>
          </section>

          <section v-if="workflowEmployeeMods.length" class="mod-fold-section mod-fold-section--inline">
            <span class="mod-ui-off-label">{{ $t('settings.workflowEmployees') }}</span>
            <span class="muted">{{ $t('settings.workflowCount', { count: workflowEmployeeMods.length }) }}</span>
            <button type="button" class="btn btn-link btn-sm" @click="goModStore">
              {{ $t('settings.modStore') }}
            </button>
          </section>

          <section class="mod-fold-section">
            <div class="mod-fold-section-head">
              <span class="mod-ui-off-label">{{ $t('settings.industryExtensions') }}</span>
              <button type="button" class="btn btn-link btn-sm" @click="goModStore">
                {{ $t('settings.modStore') }}
              </button>
            </div>
            <div v-if="selectableExtensionMods.length" class="mod-single-list">
              <div
                v-for="mod in selectableExtensionMods"
                :key="mod.id"
                class="mod-single-item"
                :class="{ active: activeModId === mod.id }"
              >
                <label class="mod-single-main">
                  <input
                    type="radio"
                    name="active-mod-id"
                    :value="mod.id"
                    :checked="activeModId === mod.id"
                    @change="onActiveModChange(mod.id)"
                  />
                  <span class="mod-single-text">{{ mod.name || mod.id }}</span>
                </label>
                <button
                  type="button"
                  class="btn btn-danger btn-sm mod-single-uninstall"
                  :disabled="uninstallingModId === mod.id || isProtectedClientModId(mod.id)"
                  @click="onUninstallMod(mod.id)"
                >
                  {{ uninstallingModId === mod.id ? $t('settings.uninstalling') : $t('settings.uninstall') }}
                </button>
              </div>
            </div>
            <p v-else class="muted mod-single-empty">
              <template v-if="loadError">{{ $t('settings.loadModsFailed') }}</template>
              <template v-else>{{ $t('settings.noIndustryExt') }}</template>
            </p>
          </section>
        </div>
      </details>

      <div class="settings-card__footer">
        <button class="settings-primary-btn" type="button" @click="saveSettings" :disabled="loading || deploymentSaving">
          {{
            deploymentSaving ? $t('settings.switchingDeployMode') : loading ? $t('settings.saving') : $t('settings.saveSettings')
          }}
        </button>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import type { DeploymentModeId } from '@/constants/deploymentModes.generated'
import type { ModInfo } from '@/types/modInfo'
import { isProtectedClientModId } from '@/constants/protectedMods'
import MobilePairingQrCard from '@/components/settings/MobilePairingQrCard.vue'

defineProps<{
  basicSettingsSummary: string
  sidebarThemeOptions: Array<{ value: string; label: string }>
  onSidebarThemeChange: () => unknown
  showCompanyBrandEditor: boolean
  companyBrandSaving: boolean
  companyBrandDirty: boolean
  saveCompanyBrand: () => unknown
  onLocaleChange: () => unknown
  systemDisplayName: string
  desktopDatabaseVisible: boolean
  databaseStorageLabel: string
  currentDbPath: string
  onDeploymentModeChange: () => unknown
  displayDeploymentModes: Array<{ id: string; label: string; badge: string }>
  deploymentModeBadge: string
  performanceModeSelected: boolean
  deploymentSaving: boolean
  deploymentStatusMessage: string
  deploymentTransitionText: string
  deploymentSyncCommand: string
  clientModsUiOff: boolean
  modSettingsFoldMeta: string
  modRoutesStatusText: string
  showModRoutesRetry: boolean
  modRoutesRetrying: boolean
  retryModRoutesLoad: () => unknown
  hostBridgeMods: ModInfo[]
  hostBridgeInstalledCount: number
  hostBridgeExpectedCount: number
  goHostPackOnboarding: () => unknown
  uninstallingModId: string
  onUninstallMod: (modId: string) => unknown
  workflowEmployeeMods: ModInfo[]
  goModStore: () => unknown
  selectableExtensionMods: ModInfo[]
  activeModId: string | null
  onActiveModChange: (modId: string) => unknown
  loadError: string | null
  loading: boolean
  saveSettings: () => unknown
}>()

// v-model 转发回父级
const sidebarThemePreset = defineModel<string>('sidebarThemePreset', { required: true })
const companyBrandDraft = defineModel<string>('companyBrandDraft', { required: true })
const assistantName = defineModel<string>('assistantName', { required: true })
const appLocale = defineModel<'zh-CN' | 'en-US'>('appLocale', { required: true })
const deploymentMode = defineModel<DeploymentModeId>('deploymentMode', { required: true })
const postgresUrlDraft = defineModel<string>('postgresUrlDraft', { required: true })
const hostPackExpanded = defineModel<boolean>('hostPackExpanded', { required: true })
</script>

<style scoped src="../SettingsView.css"></style>
