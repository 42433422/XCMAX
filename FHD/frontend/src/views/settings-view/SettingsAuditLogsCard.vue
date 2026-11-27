<template>
  <details v-if="isLoggedIn && isLocalAdmin" class="settings-card" :data-tutorial-id="`settings-${SETTINGS_ENTRIES.audit.id}`">
    <summary class="settings-row">
      <span class="settings-row__icon settings-row__icon--art" aria-hidden="true">
        <img class="settings-row__icon-art" :src="auditArtSrc" alt="" />
      </span>
      <span class="settings-row__label">{{ $t(SETTINGS_ENTRIES.audit.labelKey) }}</span>
      <span class="settings-row__meta">{{ $t('settings.auditCount', { count: auditLogsTotal }) }}</span>
      <span class="settings-row__arrow" aria-hidden="true"></span>
    </summary>
    <div class="settings-card__body settings-card__body--list">
      <p v-if="auditLogsLoading" class="muted" style="padding: 12px 16px; margin: 0">
        {{ $t('settings.auditLoading') }}
      </p>
      <p v-else-if="auditLogsError" class="settings-profile-form__hint" role="alert" style="padding: 12px 16px">
        {{ auditLogsError }}
      </p>
      <ul v-else-if="auditLogs.length" class="settings-audit-list">
        <li v-for="(row, idx) in auditLogs" :key="idx" class="settings-audit-list__item">
          <span class="settings-audit-list__action">{{ row.action || '—' }}</span>
          <span class="settings-audit-list__meta">
            {{ row.timestamp || row.ts || '' }}
            · {{ row.user_id ?? '—' }} ·
            {{ row.success === false ? $t('settings.auditFailed') : $t('settings.auditSuccess') }}
          </span>
        </li>
      </ul>
      <p v-else class="muted" style="padding: 12px 16px; margin: 0">
        {{ $t('settings.auditEmpty') }}
      </p>
      <div class="settings-profile-form__actions" style="padding: 0 16px 16px">
        <button type="button" class="settings-profile-form__submit" @click="loadAuditLogs">
          {{ $t('settings.refresh') }}
        </button>
        <button
          type="button"
          class="settings-profile-form__submit settings-profile-form__submit--ghost"
          @click="downloadAuditCsv"
        >
          {{ $t('settings.exportCsv') }}
        </button>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { SETTINGS_ENTRIES } from './settingsNavigation'
import type { AuditLogEntry } from '@/api/adminAudit'
import auditArtSrc from '@/assets/icons/settings/r2c3.png'

defineProps<{
  isLoggedIn: boolean
  isLocalAdmin: boolean
  auditLogsLoading: boolean
  auditLogsError: string
  auditLogs: AuditLogEntry[]
  auditLogsTotal: number
  loadAuditLogs: () => unknown
  downloadAuditCsv: () => unknown
}>()
</script>

<style scoped src="../SettingsView.css"></style>
