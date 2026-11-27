<template>
  <details class="settings-card">
    <summary class="settings-row">
      <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
        <img class="settings-row__icon-art" :src="aboutArtSrc" alt="" />
      </span>
      <span class="settings-row__label">{{ $t(SETTINGS_ENTRIES.about.labelKey) }}</span>
      <span class="settings-row__meta">{{ appVersionLabel }}</span>
      <span class="settings-row__arrow" aria-hidden="true"></span>
    </summary>
    <div class="settings-card__body settings-card__body--compact">
      <p class="settings-about-line">{{ aboutDisplayLine }}</p>
      <p class="muted settings-about-version">
        {{ $t('settings.currentVersion', { version: appVersionLabel }) }}
      </p>
      <div class="settings-about-actions">
        <button
          v-if="isDesktopShell"
          type="button"
          class="btn btn-sm btn-secondary"
          :disabled="aboutUpdateBusy"
          @click="onCheckForUpdates"
        >
          {{ aboutUpdateBusy ? $t('settings.checkingUpdates') : $t('settings.checkForUpdates') }}
        </button>
        <label v-if="isDesktopShell" class="settings-about-autolaunch" :title="$t('settings.autoLaunchHint')">
          <input
            type="checkbox"
            :checked="autoLaunch"
            :disabled="autoLaunchBusy"
            @change="onAutoLaunchChange(($event.target as HTMLInputElement).checked)"
          />
          <span>{{ $t('settings.desktopLaunchAtStartup') }}</span>
        </label>
        <p v-else class="muted settings-about-web-hint">
          {{ $t('settings.updateWebHint') }}
        </p>
      </div>
      <p
        v-if="autoLaunchMessage"
        class="settings-about-update-msg"
        :class="{ 'is-error': autoLaunchMessage !== $t('settings.autoLaunchUpdated') }"
      >
        {{ autoLaunchMessage }}
      </p>
      <p v-if="aboutUpdateMessage" class="settings-about-update-msg" :class="{ 'is-error': aboutUpdateError }">
        {{ aboutUpdateMessage }}
      </p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { SETTINGS_ENTRIES } from './settingsNavigation'
import aboutArtSrc from '@/assets/icons/settings/r5c1.png'

defineProps<{
  appVersionLabel: string
  aboutDisplayLine: string
  isDesktopShell: boolean
  aboutUpdateBusy: boolean
  aboutUpdateMessage: string
  aboutUpdateError: boolean
  autoLaunch: boolean
  autoLaunchBusy: boolean
  autoLaunchMessage: string
  onCheckForUpdates: () => unknown
  onAutoLaunchChange: (checked: boolean) => unknown
}>()
</script>

<style scoped src="../SettingsView.css"></style>
